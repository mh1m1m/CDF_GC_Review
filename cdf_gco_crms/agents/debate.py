"""Six-cycle debate engine (Article 09): productive cycles per independent material objection.

The limit is six *productive* cycles per objection (``objection_engine.MAX_CYCLES``), not per observation.
This module decides what counts as productive before an argument is appended to the hash chain:

* an argument that repeats an earlier one (exact after normalisation, or semantically: ≥ 0.8 four-gram
  overlap or ≥ 0.85 content-word Jaccard with any prior claim of the same actor) is unproductive and ends the
  exchange — it never consumes a cycle;
* a continued exchange needs a substantive reason: a new evidence id, a new claim, or a stance change;
* a seventh productive cycle is rejected by the chain itself (``Objection.add`` raises);
* an objection that is still material at the bound is escalated, never silently closed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..assurance.challenge import content_words, four_grams
from ..assurance.objection_engine import MAX_CYCLES, canon

SEMANTIC_NGRAM = 0.8
SEMANTIC_JACCARD = 0.85
MIN_WORDS = 3


def ngram_overlap(a: str, b: str) -> float:
    ga, gb = four_grams(a), four_grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def jaccard(a: str, b: str) -> float:
    wa, wb = set(content_words(a)), set(content_words(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def is_semantic_duplicate(claim: str, prior: list[str]) -> tuple[bool, str]:
    """True when ``claim`` repeats one of ``prior`` exactly or semantically; the reason names the rule."""
    c = canon(claim)
    if not c or len(content_words(claim)) < MIN_WORDS:
        return True, "EMPTY_OR_TOO_SHORT"
    for p in prior:
        if canon(p) == c:
            return True, "EXACT_REPEAT"
        if ngram_overlap(claim, p) >= SEMANTIC_NGRAM:
            return True, "NGRAM_REPEAT"
        if jaccard(claim, p) >= SEMANTIC_JACCARD:
            return True, "JACCARD_REPEAT"
    return False, ""


@dataclass
class Exchange:
    """The running exchange on one objection; feeds the chain and the role payloads."""
    challenge_id: str
    turns: list[dict] = field(default_factory=list)
    unproductive: list[dict] = field(default_factory=list)
    cap_hit: bool = False

    def claims(self, actor: str) -> list[str]:
        return [t["claim"] for t in self.turns if t["actor"] == actor]

    def refs(self, actor: str) -> set[str]:
        return {r for t in self.turns if t["actor"] == actor for r in t["evidence_refs"]}

    def productive(self, actor: str, claim: str, refs: list[str], *, stance: str | None = None) -> tuple[bool, str]:
        """Is this turn a substantive continuation? New claim, or old claim with new evidence, or a stance change."""
        dup, why = is_semantic_duplicate(claim, self.claims(actor))
        new_refs = set(refs) - self.refs(actor)
        stances = [t.get("stance") for t in self.turns if t["actor"] == actor and t.get("stance")]
        stance_changed = bool(stance and stances and stance != stances[-1])
        if dup and not new_refs and not stance_changed:
            return False, why or "NO_NEW_CONTENT"
        if len(self.turns) >= MAX_CYCLES:
            self.cap_hit = True
            return False, "CYCLE_BOUND"
        return True, ""

    def add(self, objection, actor: str, claim: str, refs: list[str], *, stance: str | None = None,
            execution_id: str | None = None) -> bool:
        """Append to the chain when productive; record the attempt otherwise. Returns whether it was appended."""
        ok, why = self.productive(actor, claim, refs, stance=stance)
        if not ok:
            self.unproductive.append({"actor": actor, "reason": why, "claim_digest": canon(claim)[:80]})
            return False
        try:
            objection.add(actor, claim, refs)
        except ValueError as exc:
            self.unproductive.append({"actor": actor, "reason": f"CHAIN_REFUSED: {exc}", "claim_digest": canon(claim)[:80]})
            if "six" in str(exc):
                self.cap_hit = True
            return False
        self.turns.append({"actor": actor, "claim": claim, "evidence_refs": sorted(set(refs)), "stance": stance,
                           "execution_id": execution_id, "cycle": len(self.turns) + 1})
        return True

    def for_payload(self) -> list[dict]:
        return [{"cycle": t["cycle"], "actor": t["actor"], "claim": t["claim"], "evidence_refs": t["evidence_refs"],
                 "stance": t["stance"]} for t in self.turns]

    def to_dict(self) -> dict:
        return {"challenge_id": self.challenge_id, "productive_cycles": len(self.turns), "cap_hit": self.cap_hit,
                "unproductive_attempts": list(self.unproductive), "turns": self.for_payload()}
