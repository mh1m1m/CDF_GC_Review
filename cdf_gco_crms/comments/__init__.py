"""Comment shape and checks of protocol v7.15 (07.1, 07.2, 07.4A, 08.2A, 08.2B, G-SUB-12, P14, R3(c)(d))."""
from .v715 import (CLOSURE_LABEL, IMPROVEMENT_LABEL, Ceilings, CEILINGS, check_comment, compose_comment,
                   p14_findings, r3_shape_ok, words)

__all__ = ["CLOSURE_LABEL", "IMPROVEMENT_LABEL", "Ceilings", "CEILINGS", "check_comment", "compose_comment",
           "p14_findings", "r3_shape_ok", "words"]
