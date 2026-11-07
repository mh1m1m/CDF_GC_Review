"""Header-driven round-block discovery (protocol 10.3, "Block discovery").

Blocks are located by the text of their headers, never by column letter. The
parser rejects duplicate, incomplete, out-of-order or unknown blocks
(G-DASH-01): nothing may be appended to a workbook it cannot read.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import round_schema as S


class SchemaError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class RoundSchema:
    blocks: dict[int, dict[str, int]]          # round -> role -> column (1-based)
    header_text: dict[int, str]                # column -> full header text as found
    last_col: int
    warnings: list[str] = field(default_factory=list)

    @property
    def rounds(self) -> list[int]:
        return sorted(self.blocks)

    @property
    def current_round(self) -> int:
        return max(self.blocks) if self.blocks else 0

    def col(self, r: int, role: str) -> int | None:
        return self.blocks.get(r, {}).get(role)

    def block_columns(self, r: int) -> list[int]:
        return sorted(self.blocks[r].values())


def discover(ws, header_row: int = 1) -> RoundSchema:
    max_col = ws.max_column
    headers: dict[int, str] = {}
    for c in range(1, max_col + 1):
        v = ws.cell(row=header_row, column=c).value
        if v is not None and str(v).strip() != "":
            headers[c] = S.nfc(str(v))
    last = max(headers) if headers else 0
    warnings: list[str] = []

    # fixed block A–E
    for c, expected in enumerate(S.FIXED_HEADERS, start=1):
        got = headers.get(c, "")
        if got.split("\n", 1)[0].strip() != S.nfc(expected):
            raise SchemaError("FIXED_BLOCK", f"column {c}: expected {expected!r}, found {got!r}")

    blocks: dict[int, dict[str, int]] = {}
    c = 6
    expected_round = 1
    while c <= last:
        roles = S.ROUND1_ROLES if expected_round == 1 else S.ROUNDN_ROLES
        found: dict[str, int] = {}
        for i, role in enumerate(roles):
            col = c + i
            parsed = S.parse_round_header(headers.get(col))
            if parsed is None:
                if col > last and i == 0:
                    break
                raise SchemaError("INCOMPLETE_OR_UNKNOWN_BLOCK",
                                  f"column {col}: header {headers.get(col)!r} is not the "
                                  f"{S.ROLE_NAMES[role]} of round {expected_round}")
            prole, prnd, legacy = parsed
            if prnd in blocks:
                raise SchemaError("DUPLICATE_BLOCK", f"round {prnd} appears twice (column {col})")
            if prnd != expected_round:
                raise SchemaError("OUT_OF_ORDER_BLOCK",
                                  f"column {col}: round {prnd} found where round {expected_round} was expected")
            if prole != role:
                raise SchemaError("INCOMPLETE_OR_UNKNOWN_BLOCK",
                                  f"column {col}: role {S.ROLE_NAMES[prole]!r} found where "
                                  f"{S.ROLE_NAMES[role]!r} was expected (round {prnd})")
            if legacy:
                warnings.append(f"column {col}: hyphen-minus used instead of en dash (legacy variant)")
            found[role] = col
        if not found:
            break
        blocks[expected_round] = found
        c += len(roles)
        expected_round += 1

    if not blocks:
        raise SchemaError("NO_ROUND_BLOCK", "no round-1 block (F–H) found")
    return RoundSchema(blocks=blocks, header_text=headers, last_col=last, warnings=warnings)


def capacity_warning(schema: RoundSchema, max_columns: int = 16384) -> str | None:
    remaining = (max_columns - schema.last_col) // 4
    if remaining < 10:
        return f"only {remaining} further round blocks fit in the worksheet"
    return None
