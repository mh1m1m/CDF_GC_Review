"""Deployment-mode guards run before opening any case database."""
from pathlib import Path
from .contracts import InstitutionalAccessDenied, OperatingMode


def require_public_runtime(mode: str, database: Path):
    if mode!=OperatingMode.PUBLIC_SYNTHETIC_DEMO.value:
        raise InstitutionalAccessDenied('PRIVATE_HTTP_ACTIVATION_DISABLED_PENDING_INSTITUTIONAL_ACCEPTANCE')
    if any(part in ('private','institutional','restricted') for part in database.parts):
        raise InstitutionalAccessDenied('PUBLIC_DATABASE_IN_PRIVATE_STORAGE_NAMESPACE')


def bind_public_database(store):
    # No case content is selected before mode/case-namespace checks succeed.
    store.db.execute('CREATE TABLE IF NOT EXISTS runtime_mode (mode TEXT PRIMARY KEY)')
    modes={r[0] for r in store.db.execute('SELECT mode FROM runtime_mode')}
    if modes and modes!={OperatingMode.PUBLIC_SYNTHETIC_DEMO.value}:
        raise InstitutionalAccessDenied('DATABASE_MODE_MISMATCH')
    from ..documents.policy import uploads_public
    # Uploaded-document cases (UPL-) are allowed only while the owner keeps uploads switched on.
    extra = " AND case_id NOT LIKE 'UPL-%'" if uploads_public() else ""
    if store.db.execute("SELECT 1 FROM cases WHERE case_id NOT LIKE 'SYN-%'" + extra + " LIMIT 1").fetchone():
        raise InstitutionalAccessDenied('INSTITUTIONAL_CASES_IN_PUBLIC_DATABASE')
    store.db.execute('INSERT INTO runtime_mode VALUES (?) ON CONFLICT DO NOTHING',(OperatingMode.PUBLIC_SYNTHETIC_DEMO.value,))
    store.db.commit()


def bind_private_database(store):
    store.db.execute('CREATE TABLE IF NOT EXISTS runtime_mode (mode TEXT PRIMARY KEY)')
    modes={r[0] for r in store.db.execute('SELECT mode FROM runtime_mode')}
    if modes and modes!={OperatingMode.PRIVATE_INSTITUTIONAL.value}:
        raise InstitutionalAccessDenied('DATABASE_MODE_MISMATCH')
    store.db.execute('INSERT INTO runtime_mode VALUES (?) ON CONFLICT DO NOTHING',(OperatingMode.PRIVATE_INSTITUTIONAL.value,))
    store.db.commit()
