"""Review stages in fresh chats: MAT-01, CHALLENGE, MAT-02, MAT-03, ADJUDICATE and READ (Art. 19A, 19B, 20, 00A.8).

A chat assistant cannot isolate roles inside one conversation, so each stage runs in a fresh conversation that sees
only a *packet*: the stage's instructions, the protocol articles it needs (extracted from the protocol file), its
inputs, and the exact JSON it must return. ``stage-record`` validates that JSON and files it in the draft (round 1) or
the round file (round n). ``gate`` decides whether the package may be issued: every required stage present, current
and passing (G-RT-1, G-ENG-3, G-MAT). Nothing here decides a disposition, a position or a score: the stages do, and
the GCO user decides what the protocol leaves to a human.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

STAGES = ("MAT-01", "CHALLENGE", "MAT-02", "MAT-03", "ADJUDICATE", "READ", "HUMAN-REVIEW")
POSITIONS = ("KEEP", "REVISE", "ROUTE", "ASK", "ESCALATE")
DISPOSITIONS = ("UPHELD_UNCHANGED", "UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE", "ROUTED_OUTSIDE_GCO",
                "WITHHELD_FOR_EVIDENCE", "ESCALATED_TO_GCO_REVIEWER")
THRESHOLDS = {"R1": (">=", 0.95), "R2": ("<=", 0.10), "R3": (">=", 0.90), "R4": (">=", 0.95), "R5": (">=", 0.90),
              "R6": ("==", 0.0), "R7": (">=", 0.95)}
MAX_READ_CYCLES = 3
ARTICLES = {
    "MAT-01": ("ANNEX G", "ANNEX F", "ARTICLE 03A", "ARTICLE 07", "ARTICLE 19B"),
    "CHALLENGE": ("ARTICLE 19A", "ARTICLE 03A", "ARTICLE 04", "ARTICLE 05"),
    "MAT-02": ("ANNEX G", "ARTICLE 19B", "ARTICLE 03A"),
    "MAT-03": ("ANNEX G", "ARTICLE 19B", "ARTICLE 03A"),
    "ADJUDICATE": ("ARTICLE 19A", "ARTICLE 19B", "ARTICLE 03A"),
    "READ": ("ARTICLE 20", "ARTICLE 03A", "ARTICLE 07", "ANNEX F", "ANNEX G"),
}
_STOP = re.compile(r"^(ARTICLE |ANNEX |PART [IVX]+ |END OF PROTOCOL)")


def K():
    import cdfkit
    return cdfkit


# ------------------------------------------------------------------ protocol extracts and the MAT profile line
def extract(protocol_text: str, heading: str) -> str:
    lines = protocol_text.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading + " ")), None)
    if start is None:
        return f"[{heading}: not found in the protocol file]"
    out = [lines[start]]
    for ln in lines[start + 1:]:
        if heading == "ANNEX G" and ln.startswith("END OF ANNEX G"):
            out.append(ln)
            break
        if _STOP.match(ln):
            break
        out.append(ln)
    return "\n".join(out).strip()


def mat_profile(protocol_text: str) -> dict:
    """19B.2 / G.0.4: id, version, SHA-256 of Annex G from its heading to its END line, status."""
    lines = protocol_text.split("\n")
    m = re.search(r"^VERSION: ([0-9.]+)", protocol_text, re.M)
    version = m.group(1) if m else "unknown"
    try:
        a = next(i for i, ln in enumerate(lines) if ln.startswith("ANNEX G "))
        b = next(i for i in range(a, len(lines)) if lines[i].startswith("END OF ANNEX G"))
    except StopIteration:
        return {"id": None, "line": "none", "status": "NONE"}
    text = "\n".join(lines[a:b + 1])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    validated = "VALIDATED" if re.search(r"^G\.0\.5 .*\bVALIDATED\b", text, re.M) else "PROVISIONAL"
    approved = "APPROVED" if re.search(r"^G\.0\.5 .*\bAPPROVED\b", text, re.M) and \
        not re.search(r"^G\.0\.5 .*NOT_APPROVED", text, re.M) else "NOT_APPROVED"
    return {"id": "MAT-PROFILE-G", "version": version, "sha256": digest, "status": f"{validated} {approved}",
            "line": f"MAT-PROFILE-G {version} {digest[:12]} {validated} {approved}"}


# ------------------------------------------------------------------ observations, ids and fingerprints
def obs_list(spec: dict) -> tuple[list[dict], str]:
    rnd = int(spec.get("round") or 1)
    key = "observations" if rnd == 1 else "new_observations"
    return spec.setdefault(key, []), key


def ensure_ids(spec: dict) -> bool:
    obs, _ = obs_list(spec)
    rnd = int(spec.get("round") or 1)
    used = {o.get("id") for o in obs if o.get("id")}
    changed = False
    n = 0
    for o in obs:
        if not o.get("id"):
            while True:
                n += 1
                cand = f"D{n:02d}" if rnd == 1 else f"R{rnd}-{n:02d}"
                if cand not in used:
                    break
            o["id"], changed = cand, True
            used.add(cand)
    return changed


def comment_text(o: dict) -> str:
    return K().plain(K().compose_comment(o))


def obs_fingerprint(o: dict) -> str:
    return hashlib.sha256(json.dumps([o.get("quote"), o.get("title"), comment_text(o)], ensure_ascii=False)
                          .encode("utf-8")).hexdigest()[:16]


def read_rows(state, R: int) -> list[dict]:
    """What the independent reader sees (also cdfkit dump): rows commented in round R."""
    from cdf_gco_crms.word.document_comments import rows_for_round
    follow, born = rows_for_round(state, R)
    wanted = {o.internal_id for o in follow + born}
    rows = []
    for o in state.ordered():
        if o.internal_id not in wanted:
            continue
        row = {"reader_no": o.reader_no, "title": o.title, "location": K().plain(o.location),
               "quote": K().plain(o.quote)}
        if o.birth_round == R:
            row["comment"] = K().plain(o.comment)
        if R > 1 and o.cells.get(R) and o.cells[R].feedback:
            row["follow_up"] = f"{o.value(R)}: {K().plain(o.cells[R].feedback)}"
        rows.append(row)
    return rows


def read_fingerprint(rows: list[dict]) -> str:
    keep = [[r.get("title"), r.get("comment"), r.get("follow_up")] for r in rows]
    return hashlib.sha256(json.dumps(keep, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ packets
INTRO = ("CDF–GCO–CRMS stage packet: {stage}\n\n"
         "You are running ONE stage of the CDF–GCO–CRMS protocol in a fresh conversation. You see only this packet; "
         "do not ask for the drafting conversation, the register or other stages' records. Work only from the "
         "protocol extracts and the inputs below. Never invent a source, an approval or an article number. Return "
         "exactly one JSON object in the format at the end, and nothing else.\n")

ROLE = {
    "MAT-01": "ROLE: MAT advisor, stage MAT-01 (Art. 19B.3), after drafting. Read each observation as the reviewer "
              "described in Annex G would, applying G.3 (keep, ask or delete), G.5 to G.9 and Annex F. For each "
              "observation give one position: KEEP, REVISE (with suggested_text), ROUTE (to whom, 03A.2), ASK (turn "
              "into a question to the deciding role, G.6) or ESCALATE (a material matter for the GCO user, 04.7). "
              "Your advice is advisory only (19B.1): it is not a decision and not a statement of MAT the person. "
              "Never advise shortening a material observation below its risk and remedy (19B.5). Address owners by "
              "role or unit only (G.5.2).",
    "CHALLENGE": "ROLES: objector then advocate (Art. 19A.2), kept apart. For each observation: (1) as the objector "
                 "(the receiving department), raise at most one objection, only on an admitted ground of 19A.4, "
                 "with its evidence (a paragraph number or a clause), or state that there is none; (2) as the "
                 "advocate, answer it and, where right, propose a revision. Count productive cycles (19A.5, at most "
                 "six). Do NOT adjudicate: the adjudicator is another stage. Do not judge the prose (Art. 20 does).",
    "MAT-02": "ROLE: MAT advisor, stage MAT-02 (19B.3), after each objection. Your earlier MAT-01 output is disclosed "
              "below (19B.3 requires this disclosure). For each objection give one position (KEEP, REVISE, ROUTE, "
              "ASK, ESCALATE) on the observation in the light of the objection, applying Annex G. Advisory only.",
    "MAT-03": "ROLE: MAT advisor, stage MAT-03 (19B.3), after the advocate's response, in a fresh context: you see "
              "the observation, the objection and the response only, not any earlier MAT output. Give one position "
              "per observation, applying Annex G. Advisory only.",
    "ADJUDICATE": "ROLE: adjudicator (19A.2, 19A.6). For each observation weigh the objection, the response and their "
                  "evidence, and the jurisdiction of each side, and propose exactly one disposition of 19A.6. The MAT "
                  "material below is ADVISORY_ONLY_NOT_EVIDENCE (19B.4): a disposition that rests on it alone is not "
                  "a disposition. Observations without an objection are UPHELD_UNCHANGED unless the record shows "
                  "otherwise.",
    "READ": "ROLE: independent reader (Art. 20). You have not seen the drafting, the register or the challenge "
            "record. (1) Draw the sample of 20.2 with a random seed you state (a fresh one every cycle); include "
            "every comment when there are fewer than five. (2) Scan ALL comments for duplicate remedies, "
            "contradictions between remedies and broken \"#NN\" references (20.2). (3) Score each sampled comment "
            "R1 to R7 as 20.3 defines them (1 or 0; for R2 and R6, 1 means the defect is present). (4) Propose "
            "rewrites that only shorten, route or ask (20.4). Do not compute the pass: the kit does.",
}

SCHEMA = {
    "MAT-01": '{"stage": "MAT-01", "profile": "<the MAT PROFILE line above>", "positions": [{"id": "D01", '
              '"position": "KEEP|REVISE|ROUTE|ASK|ESCALATE", "advice": "...", "suggested_text": null}]}',
    "CHALLENGE": '{"stage": "CHALLENGE", "independence": "FRESH_CONTEXT_SAME_PLATFORM", "platform": "<Claude chat | '
                 'ChatGPT>", "records": [{"id": "D01", "objection": null, "ground": null, "evidence": null, '
                 '"response": null, "revision": null, "cycles": 0}]}',
    "MAT-02": '{"stage": "MAT-02", "profile": "<line>", "positions": [{"id": "D01", "position": "...", '
              '"advice": "...", "suggested_text": null}]}',
    "MAT-03": '{"stage": "MAT-03", "profile": "<line>", "positions": [{"id": "D01", "position": "...", '
              '"advice": "...", "suggested_text": null}]}',
    "ADJUDICATE": '{"stage": "ADJUDICATE", "dispositions": [{"id": "D01", "disposition": "UPHELD_UNCHANGED|'
                  'UPHELD_WITH_REVISION|NARROWED_TO_GCO_SCOPE|ROUTED_OUTSIDE_GCO|WITHHELD_FOR_EVIDENCE|'
                  'ESCALATED_TO_GCO_REVIEWER", "rationale": "...", "open_question": null}]}',
    "READ": '{"stage": "READ", "reader": "agent instance, fresh context, no drafting material supplied", '
            '"platform": "<Claude chat | ChatGPT>", "seed": 12345, "sample": ["01"], "scores": {"01": {"R1": 1, '
            '"R2": 0, "R3": 1, "R4": 1, "R5": 1, "R6": 0, "R7": 1}}, "scan_findings": [], "rewrites": '
            '[{"reader_no": "01", "proposed": "...", "why": "..."}]}',
}


def _obs_view(o: dict, full: bool = True) -> dict:
    v = {"id": o.get("id"), "location": o.get("location"), "quote": o.get("quote"), "title": o.get("title"),
         "form": o.get("form"), "comment": comment_text(o)}
    if full:
        v.update({k: o.get(k) for k in ("lens_category", "severity", "severity_basis", "materiality_test",
                                         "searched_clauses", "depends_on_unseen", "target_clauses", "edit_type",
                                         "conflicts_checked", "material_categories", "reason") if o.get(k)})
    return v


def build_packet(stage: str, spec: dict, protocol_text: str, docx: Path | None, workbook: Path | None) -> tuple[str, dict]:
    obs, _ = obs_list(spec)
    stages = spec.get("stages") or {}
    meta = {"stage": stage}
    parts = [INTRO.format(stage=stage), ROLE[stage]]
    prof = mat_profile(protocol_text)
    if stage.startswith("MAT"):
        if not prof.get("id"):
            raise ValueError("the protocol file has no Annex G: MAT PROFILE is none and the MAT stages are not run "
                             "(19B.2)")
        parts.append(f"\nMAT PROFILE: {prof['line']}  (while NOT_APPROVED the advice binds nothing, G-MAT-04)")
        meta["profile"] = prof
    parts.append("\n=== PROTOCOL EXTRACTS ===")
    for h in ARTICLES[stage]:
        parts.append(extract(protocol_text, h))
    parts.append("\n=== INPUTS ===")
    # 19A.3A (engine, cdf_gco_crms.protocol.stage_packets): every stage but READ carries the supplied sources with the
    # particulars of 19A.7; an extract missing a particular is refused; the meta records their SHA-256.
    from cdf_gco_crms.protocol.stage_packets import packet_sources
    src, src_meta = packet_sources(stage, spec.get("sources") or [])
    if src:
        parts.append("Supplied sources (classified under 19A.3 by the drafting agent; verbatim extracts with the "
                     "particulars of 19A.7; a provision quoted here counts as supplied, anything not quoted here does "
                     "not):\n" + json.dumps(src, ensure_ascii=False, indent=1))
        meta.update(src_meta)
    if stage in ("MAT-01", "CHALLENGE"):
        if docx is None:
            raise ValueError(f"{stage} needs --doc (the document, or its review Word file)")
        paras = [t for t in K().doc_paragraphs(docx) if t.strip()]
        parts.append("Document paragraphs (accepted view):\n" + "\n".join(f"[¶{i + 1}] {t}" for i, t in enumerate(paras)))
        parts.append("Observations:\n" + json.dumps([_obs_view(o) for o in obs], ensure_ascii=False, indent=1))
        meta["fingerprints"] = {o["id"]: obs_fingerprint(o) for o in obs}
    elif stage in ("MAT-02", "MAT-03", "ADJUDICATE"):
        ch = stages.get("CHALLENGE")
        if not ch:
            raise ValueError(f"{stage} needs the CHALLENGE record first (stage-record CHALLENGE)")
        recs = {r["id"]: r for r in ch["records"]}
        objected = [o for o in obs if (recs.get(o["id"]) or {}).get("objection")]
        if stage == "MAT-02":
            m1 = stages.get("MAT-01")
            parts.append("Your earlier MAT-01 output (disclosed, 19B.3):\n" +
                         json.dumps(m1["positions"] if m1 else [], ensure_ascii=False, indent=1))
            parts.append("Observations with objections (responses withheld):\n" + json.dumps(
                [{**_obs_view(o, False), "objection": recs[o["id"]]["objection"], "ground": recs[o["id"]].get("ground"),
                  "evidence": recs[o["id"]].get("evidence")} for o in objected], ensure_ascii=False, indent=1))
        elif stage == "MAT-03":
            parts.append("Observation, objection and response (no earlier MAT output):\n" + json.dumps(
                [{**_obs_view(o, False), "objection": recs[o["id"]]["objection"],
                  "response": recs[o["id"]].get("response"), "revision": recs[o["id"]].get("revision")}
                 for o in objected], ensure_ascii=False, indent=1))
        else:
            advice = {}
            for st in ("MAT-02", "MAT-03"):
                for p in (stages.get(st) or {}).get("positions", []):
                    advice.setdefault(p["id"], []).append({"stage": st, "position": p["position"],
                                                           "advice": p.get("advice")})
            parts.append("Observations, objections, responses and MAT material (ADVISORY_ONLY_NOT_EVIDENCE):\n" +
                         json.dumps([{**_obs_view(o), "objection": (recs.get(o["id"]) or {}).get("objection"),
                                      "ground": (recs.get(o["id"]) or {}).get("ground"),
                                      "evidence": (recs.get(o["id"]) or {}).get("evidence"),
                                      "response": (recs.get(o["id"]) or {}).get("response"),
                                      "revision": (recs.get(o["id"]) or {}).get("revision"),
                                      "cycles": (recs.get(o["id"]) or {}).get("cycles"),
                                      "ADVISORY_ONLY_NOT_EVIDENCE": advice.get(o["id"], [])} for o in obs],
                                    ensure_ascii=False, indent=1))
        meta["ids"] = [o["id"] for o in (objected if stage != "ADJUDICATE" else obs)]
    elif stage == "READ":
        if workbook is None:
            raise ValueError("READ needs --workbook (the working-copy workbook that build or next wrote)")
        from cdf_gco_crms.ingestion.workbook_reader import parse_workbook
        st = parse_workbook(workbook).state
        rows = read_rows(st, st.current_round)
        parts.append(f"Comments of round {st.current_round} ({len(rows)}):\n" +
                     json.dumps(rows, ensure_ascii=False, indent=1))
        meta.update({"read_fingerprint": read_fingerprint(rows), "comments": [r["reader_no"] for r in rows],
                     "round": st.current_round,
                     "critical": [r["reader_no"] for r in rows if _severity_of(spec, r) == "CRITICAL"]})
        meta["suggested_seed"] = random.SystemRandom().randint(1, 10 ** 6)
    parts.append("\n=== RETURN EXACTLY THIS JSON SHAPE ===\n" + SCHEMA[stage])
    return "\n\n".join(parts) + "\n", meta


def _severity_of(spec: dict, row: dict) -> str | None:
    obs, _ = obs_list(spec)
    for o in obs:
        if (o.get("quote") or "").strip() == (row.get("quote") or "").strip():
            return (o.get("severity") or "").upper()
    return None


# ------------------------------------------------------------------ records
def validate(stage: str, result: dict, spec: dict, meta: dict | None) -> list[str]:
    p = []
    if result.get("stage") != stage:
        p.append(f"the result says stage {result.get('stage')!r}, expected {stage}")
    obs, _ = obs_list(spec)
    ids = [o["id"] for o in obs if o.get("id")]
    if stage in ("MAT-01", "MAT-02", "MAT-03"):
        want = ids if stage == "MAT-01" else (meta or {}).get("ids", [])
        got = {x.get("id") for x in result.get("positions", [])}
        miss = [i for i in want if i not in got]
        if miss:
            p.append(f"positions missing for {miss}")
        for x in result.get("positions", []):
            if x.get("position") not in POSITIONS:
                p.append(f"{x.get('id')}: position must be one of {POSITIONS}")
        prof = (meta or {}).get("profile") or {}
        if prof.get("line") and result.get("profile") and prof["line"] not in result["profile"]:
            p.append("the profile line in the result differs from the packet's (G-MAT-04)")
    elif stage == "CHALLENGE":
        got = {x.get("id") for x in result.get("records", [])}
        miss = [i for i in ids if i not in got]
        if miss:
            p.append(f"records missing for {miss}")
        for x in result.get("records", []):
            if x.get("objection") and not x.get("ground"):
                p.append(f"{x.get('id')}: an objection needs its ground (19A.4)")
            if int(x.get("cycles") or 0) > 6:
                p.append(f"{x.get('id')}: more than six productive cycles (19A.5): escalate instead")
    elif stage == "ADJUDICATE":
        got = {x.get("id") for x in result.get("dispositions", [])}
        miss = [i for i in ids if i not in got]
        if miss:
            p.append(f"dispositions missing for {miss}")
        for x in result.get("dispositions", []):
            if x.get("disposition") not in DISPOSITIONS:
                p.append(f"{x.get('id')}: disposition must be one of 19A.6")
    elif stage == "READ":
        comments = (meta or {}).get("comments", [])
        sample = [str(s) for s in result.get("sample", [])]
        known = {str(c) for c in comments}
        unknown = sorted({s for s in sample if s not in known})
        if unknown:
            p.append(f"sample holds numbers that are not comments of this packet: {unknown} (20.2)")
        sample = [s for s in sample if s in known]
        need = len(comments) if len(comments) < 5 else max(5, -(-len(comments) * 20 // 100))
        if len(set(sample)) < need:
            p.append(f"sample of {len(set(sample))} < {need} required by 20.2")
        for c in (meta or {}).get("critical", []):
            if c not in sample:
                p.append(f"CRITICAL comment #{c} not in the sample (20.2)")
        for s in sample:
            sc = (result.get("scores") or {}).get(s)
            if not sc or any(sc.get(r) not in (0, 1) for r in THRESHOLDS):
                p.append(f"#{s}: scores R1 to R7 (0 or 1) missing")
        if result.get("seed") in (None, ""):
            p.append("seed missing (20.2)")
    elif stage == "HUMAN-REVIEW":
        for k in ("reviewer_role", "date", "covers"):
            if not result.get(k):
                p.append(f"{k} missing (role, never a personal name; ISO date; 'all' or the list of #NN)")
        if result.get("reviewer_role") and re.search(r"(الأخ|الأستاذ|أبو |Mr\.|Ms\.)", result["reviewer_role"]):
            p.append("reviewer_role must be a role, not a person (G-MAT-05)")
    return p


def read_rates(result: dict) -> dict:
    sample = [str(s) for s in result.get("sample", [])]
    rates, ok = {}, True
    for r, (op, lim) in THRESHOLDS.items():
        vals = [int((result.get("scores") or {}).get(s, {}).get(r, 0)) for s in sample]
        v = round(sum(vals) / len(vals), 3) if vals else 0.0
        good = (v >= lim) if op == ">=" else (v <= lim) if op == "<=" else (v == lim)
        rates[r] = {"rate": v, "threshold": f"{op} {lim}", "pass": good}
        ok = ok and good
    scan = result.get("scan_findings") or []
    return {"rates": rates, "scan_findings": len(scan), "pass": ok and not scan}


# ------------------------------------------------------------------ the issue gate
def gate(spec: dict, state, round_no: int) -> list[str]:
    """Problems that block issue (00A.7, 00A.8, G-RT-1, G-ENG-3, G-MAT). Empty list: the stages allow issue."""
    p = []
    stages = spec.get("stages") or {}
    obs, _ = obs_list(spec)
    ids = [o.get("id") for o in obs]
    if obs and any(not i for i in ids):
        p.append("observations without id: run stage-packet first (it numbers them)")
    if obs:
        if not stages.get("MAT-01"):
            p.append("MAT-01 not recorded (19B.3; run it with the MAT profile of Annex G)")
        ch = stages.get("CHALLENGE")
        if not ch:
            p.append("CHALLENGE not recorded (19A, 00A.8(1))")
        else:
            recs = {r["id"]: r for r in ch["records"]}
            for i in ids:
                if i not in recs:
                    p.append(f"{i}: not covered by the CHALLENGE record (added after it? run the stages again)")
            objected = [i for i, r in recs.items() if r.get("objection") and i in ids]
            for st in ("MAT-02", "MAT-03"):
                got = {x["id"] for x in (stages.get(st) or {}).get("positions", [])}
                miss = [i for i in objected if i not in got]
                if miss:
                    p.append(f"{st} missing for objected observations {miss} (19B.3)")
        adj = stages.get("ADJUDICATE")
        if not adj:
            p.append("ADJUDICATE not recorded (19A.6)")
        else:
            disp = {d["id"]: d for d in adj["dispositions"]}
            snap = (ch or {}).get("meta", {}).get("fingerprints", {})
            for o in obs:
                if not o.get("id"):
                    continue                     # reported above: stage-packet numbers them
                d = disp.get(o["id"])
                if not d:
                    p.append(f"{o['id']}: no disposition")
                    continue
                kind = d["disposition"]
                if kind in ("ROUTED_OUTSIDE_GCO", "WITHHELD_FOR_EVIDENCE"):
                    # 19A.6A (engine): the GCO reviewer may retain it; draft 'decisions' records
                    # {"decision": "RETAIN", "reviewer_role", "date"} under its id; the adjudication stays unchanged.
                    from cdf_gco_crms.protocol.stage_packets import retention_problems
                    p += retention_problems([o["id"]], disp, spec.get("decisions") or {})
                elif kind == "ESCALATED_TO_GCO_REVIEWER" and not (spec.get("decisions") or {}).get(o["id"]):
                    p.append(f"{o['id']}: escalated: record the GCO user's decision in draft 'decisions'")
                elif kind in ("UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE") and \
                        snap.get(o["id"]) == obs_fingerprint(o) and not o.get("revision_declined_reason"):
                    p.append(f"{o['id']}: {kind} but the text is unchanged: apply the revision or record "
                             "revision_declined_reason")
    human = stages.get("HUMAN-REVIEW")
    reads = stages.get("READ_HISTORY") or []
    if human and human.get("covers") == "all":
        seen = (human.get("meta") or {}).get("obs_fingerprints")
        if seen is None or any(seen.get(o.get("id")) != obs_fingerprint(o) for o in obs):
            p.append("the HUMAN-REVIEW record is stale: comments changed after it (or it predates kit 1.2.0); "
                     "the GCO reviewer reads them again and HUMAN-REVIEW is recorded again (20.4)")
        return p
    if not reads:
        p.append("independent read not recorded (Art. 20; or a HUMAN-REVIEW record covering all comments)")
        return p
    last = reads[-1]
    fp_now = read_fingerprint(read_rows(state, round_no))
    if last.get("meta", {}).get("read_fingerprint") != fp_now:
        p.append("the independent read is stale: comments changed after it; build, then run READ again (20.4)")
    elif not last.get("computed", {}).get("pass"):
        fails = sum(1 for x in reads if not x.get("computed", {}).get("pass"))
        if fails >= MAX_READ_CYCLES:
            p.append("the independent read failed three cycles: escalate to a human GCO reviewer and record "
                     "HUMAN-REVIEW (20.4)")
        else:
            p.append(f"the independent read did not pass ({fails} of {MAX_READ_CYCLES} cycles): rewrite, build, "
                     "READ again")
    return p


# ------------------------------------------------------------------ commands
def cmd_stage_packet(a) -> int:
    k = K()
    path = Path(a.draft)
    spec = k.load_json(path)
    if ensure_ids(spec):
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        protocol_text = Path(a.protocol).read_text(encoding="utf-8")
        doc = Path(a.doc) if a.doc else None
        docx = k.review_docx(doc, Path(a.out)) if doc else None
        text, meta = build_packet(a.stage, spec, protocol_text, docx, Path(a.workbook) if a.workbook else None)
    except (OSError, ValueError) as exc:
        return k.fail(str(exc))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"PACKET-{a.stage}.md"
    dest.write_text(text, encoding="utf-8")
    meta["packet_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    pending = spec.setdefault("stage_packets", {})
    pending[a.stage] = meta
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    k.emit({"status": "OK", "packet": str(dest), "characters": len(text), "stage": a.stage,
            "profile": (meta.get("profile") or {}).get("line"),
            "next": f"save the packet where the user can download it; the user opens a fresh conversation "
                    f"(ChatGPT: Temporary Chat; Claude: a new chat outside any project, memory off), attaches it and "
                    f"pastes the FRESH-CHAT prompt; then: cdfkit.py stage-record {a.stage} <answer.json> --draft "
                    f"{path.name}"})
    return k.RC_OK


def cmd_stage_record(a) -> int:
    k = K()
    path = Path(a.draft)
    spec = k.load_json(path)
    try:
        raw = Path(a.result).read_text(encoding="utf-8").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        result = json.loads(raw)
    except (OSError, ValueError) as exc:
        return k.fail(f"cannot read the stage answer: {exc}")
    meta = (spec.get("stage_packets") or {}).get(a.stage)
    if a.stage != "HUMAN-REVIEW" and not meta:
        return k.fail(f"no packet was issued for {a.stage} from this draft: run stage-packet first")
    probs = validate(a.stage, result, spec, meta)
    if probs:
        k.emit({"status": "FAIL", "stage": a.stage, "problems": probs})
        return k.RC_FAIL
    import datetime as dt
    rec = {**result, "meta": meta or {}, "received_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if a.stage == "HUMAN-REVIEW":           # what the human reviewer saw: the record goes stale if a comment changes
        obs, _ = obs_list(spec)
        rec["meta"] = {**rec["meta"], "obs_fingerprints": {o["id"]: obs_fingerprint(o) for o in obs if o.get("id")}}
    stages = spec.setdefault("stages", {})
    out = {"status": "OK", "stage": a.stage}
    if a.stage == "READ":
        rec["computed"] = read_rates(result)
        stages.setdefault("READ_HISTORY", []).append(rec)
        out["read"] = rec["computed"]
        out["cycle"] = len(stages["READ_HISTORY"])
    else:
        stages[a.stage] = rec
    if a.stage == "ADJUDICATE":
        out["dispositions"] = {d["id"]: d["disposition"] for d in result["dispositions"]}
    if a.stage.startswith("MAT"):
        out["positions"] = {x["id"]: x["position"] for x in result["positions"]}
        out["note"] = "advisory only (19B.1): the drafting agent decides what to revise; MAT advice is never a decision"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    k.emit(out)
    return k.RC_OK
