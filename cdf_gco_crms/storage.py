"""Database connections: SQLite by default, PostgreSQL when ``CDF_DATABASE_URL`` is set.

The engine was written against ``sqlite3``. For a hosted deployment (Supabase Postgres) this module returns a
connection that offers the small part of the ``sqlite3`` API the engine uses, with the same transaction semantics:

* ``?`` placeholders; every number is sent untyped so Postgres infers its type from context, as SQLite would;
* a DML statement outside a transaction opens one, and ``commit()`` ends it (the ``sqlite3`` module's default);
* ``BEGIN IMMEDIATE`` takes a per-schema advisory lock, so writers are serialised as in SQLite;
* a failed statement inside a transaction rolls back to its own savepoint and leaves the transaction usable;
* one connection is shared by the threads of a process, but a transaction belongs to the thread that opened it:
  any other thread waits until it ends, instead of running inside it (``in_transaction`` is per thread);
* integrity failures raise ``sqlite3.IntegrityError`` and other failures ``sqlite3.OperationalError``;
* DDL is translated (``AUTOINCREMENT``, ``REAL``, ``BLOB``, triggers) and run under a lock, so concurrent cold
  starts cannot race on ``CREATE ... IF NOT EXISTS``.

Each store path maps to its own schema (``CDF_DATABASE_SCHEMA`` overrides it), which keeps test databases apart
and keeps the hosted tables out of Supabase's public Data API schema.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

__all__ = ["database_url", "is_postgres", "connect", "schema_for", "table_exists", "integrity_ok"]


def database_url() -> str:
    return os.getenv("CDF_DATABASE_URL", "").strip()


def is_postgres(db) -> bool:
    return isinstance(db, PgConnection)


def schema_for(path) -> str:
    explicit = os.getenv("CDF_DATABASE_SCHEMA", "").strip()
    if explicit:
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", explicit):
            raise ValueError("INVALID_DATABASE_SCHEMA")
        return explicit
    return "cdf_" + hashlib.sha256(str(Path(path).expanduser().resolve()).encode()).hexdigest()[:16]


def connect(path, *, readonly: bool = False):
    url = database_url()
    if url:
        return PgConnection(url, schema_for(path))
    if readonly:
        db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    else:
        db = sqlite3.connect(str(path), check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def table_exists(db, name: str) -> bool:
    if is_postgres(db):
        return db.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?",
                          (name,)).fetchone() is not None
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def integrity_ok(db) -> bool:
    if is_postgres(db):
        return db.execute("SELECT 1").fetchone()[0] == 1  # the provider runs page-level checks; we check reachability
    return db.execute("PRAGMA quick_check").fetchone()[0] == "ok"


# ------------------------------------------------------------------ PostgreSQL
class Row(tuple):
    """``sqlite3.Row`` equivalent: index or column-name access, ``keys()`` and ``dict(row)``."""

    def __new__(cls, values, index):
        row = super().__new__(cls, values)
        row._index = index
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._index)


class Cursor:
    def __init__(self, rows, rowcount, description):
        self._rows = rows
        self._pos = 0
        self.rowcount = rowcount
        self.description = description
        self.lastrowid = None

    def fetchone(self):
        if self._rows is None or self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self):
        if self._rows is None:
            return []
        rest = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rest

    def fetchmany(self, size=1):
        out = []
        for _ in range(size):
            row = self.fetchone()
            if row is None:
                break
            out.append(row)
        return out

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row


_DML = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)
_RESERVED = re.compile(r'(?<!["\w])window(?!["\w])')       # a column name in the engine, reserved in PostgreSQL
_TRIGGER = re.compile(
    r"CREATE\s+TRIGGER\s+IF\s+NOT\s+EXISTS\s+(\w+)\s+BEFORE\s+(UPDATE|DELETE)\s+ON\s+(\w+)\s+"
    r"BEGIN\s+SELECT\s+RAISE\s*\(\s*ABORT\s*,\s*'([^']*)'\s*\)\s*;\s*END\s*;?", re.I | re.S)
_DROP_TRIGGER = re.compile(r"^\s*DROP\s+TRIGGER\s+(IF\s+EXISTS\s+)?(\w+)\s*;?\s*$", re.I)


def _split_literals(sql: str):
    """Yield (is_literal, text) parts so rewrites never touch quoted strings."""
    parts, buf, i, n = [], [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            if buf:
                parts.append((False, "".join(buf)))
                buf = []
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            parts.append((True, sql[i:j + 1]))
            i = j + 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        parts.append((False, "".join(buf)))
    return parts


@lru_cache(maxsize=2048)
def translate(sql: str) -> str:
    out = []
    for literal, text in _split_literals(sql):
        if literal:
            out.append(text.replace("%", "%%"))
            continue
        text = text.replace("%", "%%").replace("?", "%s")
        text = _RESERVED.sub('"window"', text)
        out.append(text)
    return "".join(out)


def _ddl(script: str, triggers: dict) -> list[str]:
    def trigger(m):
        name, when, table, message = m.group(1), m.group(2).upper(), m.group(3), m.group(4)
        triggers[name.lower()] = table
        fn = f"{name}_fn"
        return (f"\x00CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $f$ BEGIN "
                f"RAISE EXCEPTION '{message}' USING ERRCODE = 'integrity_constraint_violation'; END $f$;\x00"
                f"CREATE OR REPLACE TRIGGER {name} BEFORE {when} ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}();\x00")

    script = _TRIGGER.sub(trigger, script)
    script = re.sub(r"--[^\n]*", "", script)
    script = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
                    script, flags=re.I)
    script = re.sub(r"(\(|,)\s*(\w+)\s+INTEGER\s+PRIMARY\s+KEY\b", r"\1\2 BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
                    script, flags=re.I)
    script = re.sub(r"\bINTEGER\b", "BIGINT", script, flags=re.I)
    script = re.sub(r"\bREAL\b", "DOUBLE PRECISION", script, flags=re.I)   # PostgreSQL REAL is single precision
    script = re.sub(r"\bBLOB\b", "BYTEA", script, flags=re.I)
    statements = []
    for chunk in script.split("\x00"):
        if "$f$" in chunk:
            statements.append(chunk.strip().rstrip(";"))
            continue
        statements += [s.strip() for s in chunk.split(";") if s.strip()]
    return [_RESERVED.sub('"window"', s) for s in statements]


def _param(value):
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, memoryview):
        return bytes(value)
    return value


def _sqlite_error(exc):
    import psycopg

    message = getattr(getattr(exc, "diag", None), "message_primary", None) or str(exc)
    if isinstance(exc, psycopg.errors.IntegrityError):
        return sqlite3.IntegrityError(message)
    return sqlite3.OperationalError(message)


class PgConnection:
    """The subset of ``sqlite3.Connection`` the engine uses, over psycopg 3."""

    def __init__(self, url: str, schema: str):
        import psycopg

        self._psycopg = psycopg
        self.schema = schema
        self._lock_key = int(hashlib.sha256(schema.encode()).hexdigest()[:15], 16)
        # prepare_threshold=None: safe behind a connection pooler.
        self._conn = psycopg.connect(url, autocommit=True, prepare_threshold=None)
        self._tx = False
        self._tx_owner: int | None = None
        # Held by the thread that opened the current transaction until it commits or rolls back; every other
        # thread takes it before using the connection, so it waits instead of joining someone else's transaction.
        self._tx_lock = threading.RLock()
        self._triggers: dict[str, str] = {}
        self._mutex = threading.RLock()
        self.row_factory = None          # accepted for compatibility; rows always support name and index access
        with self._mutex:
            # A hosted role is granted its schema in advance and needs no database-level CREATE right.
            if self._raw("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone() is None:
                self._raw(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            self._raw(f'SET search_path TO "{schema}"')

    # -- low level
    def _raw(self, sql, params=None):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def _begin(self, *, lock=True):
        self._tx_lock.acquire()                    # released by _end(); callers already hold it once
        try:
            self._raw("BEGIN")
        except BaseException:
            self._tx_lock.release()
            raise
        self._tx = True
        self._tx_owner = threading.get_ident()
        if lock:
            self._raw("SELECT pg_advisory_xact_lock(%s)", (self._lock_key,))

    def _end(self, statement: str):
        self._tx = False
        self._tx_owner = None
        try:
            self._raw(statement)
        finally:
            self._tx_lock.release()

    @property
    def in_transaction(self) -> bool:
        """True only for the thread whose transaction is open."""
        return self._tx and self._tx_owner == threading.get_ident()

    # -- sqlite3 API
    def execute(self, sql, params=()):
        with self._tx_lock, self._mutex:
            stripped = sql.strip().rstrip(";").strip()
            upper = stripped.upper()
            if upper.startswith("PRAGMA"):
                if "QUICK_CHECK" in upper or "INTEGRITY_CHECK" in upper:
                    return Cursor([Row(("ok",), {"quick_check": 0})], 1, None)
                return Cursor([], 0, None)
            if upper == "BEGIN IMMEDIATE" or upper == "BEGIN":
                if self._tx:
                    raise sqlite3.OperationalError("cannot start a transaction within a transaction")
                self._begin()
                return Cursor([], 0, None)
            dropped = _DROP_TRIGGER.match(stripped)
            if dropped:
                table = self._triggers.get(dropped.group(2).lower()) or self._trigger_table(dropped.group(2))
                sql = f"DROP TRIGGER IF EXISTS {dropped.group(2)} ON {table}" if table else "SELECT 1"
                params = ()
            if _DML.match(sql) and not self._tx:
                self._begin()
            text = translate(sql)
            values = tuple(_param(v) for v in (params or ()))
            savepoint = self._tx and not upper.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK"))
            try:
                if savepoint:
                    self._raw("SAVEPOINT cdf_stmt")
                cur = self._raw(text, values)
                rows = None
                if cur.description is not None:
                    index = {d.name: i for i, d in enumerate(cur.description)}
                    rows = [Row(r, index) for r in cur.fetchall()]
                if savepoint:
                    self._raw("RELEASE SAVEPOINT cdf_stmt")
                return Cursor(rows, cur.rowcount, cur.description)
            except self._psycopg.Error as exc:
                if savepoint:
                    try:
                        self._raw("ROLLBACK TO SAVEPOINT cdf_stmt")
                        self._raw("RELEASE SAVEPOINT cdf_stmt")
                    except self._psycopg.Error:
                        pass
                raise _sqlite_error(exc) from exc

    def _trigger_table(self, name):
        row = self._raw("SELECT event_object_table FROM information_schema.triggers WHERE trigger_schema=%s AND trigger_name=%s",
                        (self.schema, name.lower())).fetchone()
        return row[0] if row else None

    def executemany(self, sql, seq):
        for params in seq:
            self.execute(sql, params)

    def executescript(self, script):
        with self._tx_lock, self._mutex:
            if self._tx:
                self.commit()
            statements = _ddl(script, self._triggers)
            try:
                self._raw("BEGIN")
                self._raw("SELECT pg_advisory_xact_lock(%s)", (self._lock_key,))
                for statement in statements:
                    self._raw(statement)
                self._raw("COMMIT")
            except self._psycopg.Error as exc:
                self._raw("ROLLBACK")
                raise _sqlite_error(exc) from exc

    def commit(self):
        with self._tx_lock, self._mutex:
            if self._tx:
                try:
                    self._end("COMMIT")
                except self._psycopg.Error as exc:
                    raise _sqlite_error(exc) from exc

    def rollback(self):
        with self._tx_lock, self._mutex:
            if self._tx:
                self._end("ROLLBACK")

    def close(self):
        with self._mutex:
            if self._tx:
                self.rollback()
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        if kind is None:
            self.commit()
        else:
            self.rollback()
        return False
