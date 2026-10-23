"""Authority reference layer (v7.12): organisational-structure deck and authority matrix.

Extraction proves only that a passage occurs in a source file. It establishes
neither the legal applicability of the passage nor the approval of the source;
the status flags of INSTITUTIONAL-SOURCE-STATUS.json are carried as recorded
and never upgraded by this package.
"""
from .authority_matrix import Item, MatrixIndex, parse_matrix  # noqa: F401
from .index import ReferenceIndex, SourceStatus  # noqa: F401
from .org_structure import Mandate, OrgIndex, Sector, Unit, parse_org_text  # noqa: F401
from .textnorm import match_key, nfc, repair_ligatures  # noqa: F401
from .synthetic_index import load_reference_index, synthetic_reference_index  # noqa: F401
