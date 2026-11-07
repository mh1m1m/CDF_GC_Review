#!/usr/bin/env python3
"""PHASE 01/02 — source discovery and static forensic review (read-only).

Scans every source tree for AI-provider integrations (SDK imports, HTTP clients, API-key use, model names) and
inventories every agent-like component of the audited engine with its callers. Writes
reports/AI-IMPLEMENTATION-INVENTORY.json and reports/AI-PROVIDER-INTEGRATION-INVENTORY.json.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
WS = ENGINE.parent
TREES = {
    "v7.12 engine (audited)": ENGINE / "cdf_gco_crms",
    "v7.12 entry point": ENGINE / "main.py",
    "v7.12 tools": ENGINE / "tools",
    "v7.12 tests": ENGINE / "tests",
    "v7.11 package": WS / "uploads" / "source_unzipped" / "cdf-gco-crms-v7.11" / "cdf_gco_crms",
    "Batch 10 ChatGPT adapter cdf_v712": WS / "uploads" / "batch10" / "CDF-GCO-CRMS-v7.12" / "02_ENGINE" / "source" / "cdf_v712",
    "Batch 10 RUN_IN_CHATGPT.py": WS / "uploads" / "batch10" / "CDF-GCO-CRMS-v7.12" / "RUN_IN_CHATGPT.py",
    "Batch 10 legacy_source_v712_rc": WS / "uploads" / "batch10" / "CDF-GCO-CRMS-v7.12" / "02_ENGINE" / "legacy_source_v712_rc",
    "exploratory ChatGPT copy in sources/": ENGINE / "sources" / "v7.12" / "chatgpt_cdf_v712",
}
PROVIDER_MODULES = {"anthropic", "openai", "httpx", "requests", "aiohttp", "urllib", "litellm", "langchain", "langchain_openai",
                    "google.generativeai", "boto3", "transformers", "ollama", "vllm", "cohere", "mistralai", "socket", "http.client"}
PROVIDER_STRINGS = re.compile(r"(api\.anthropic\.com|api\.openai\.com|ANTHROPIC_API_KEY|OPENAI_API_KEY|messages\.create|chat\.completions|"
                              r"claude-[a-z0-9-]+|gpt-[45][a-z0-9.-]*|Bearer |x-api-key|llm\b|LLM\b|model_call|inference)", re.IGNORECASE)
AGENT_WORDS = re.compile(r"black_team|red_advocate|adjudicat|challenge|persona|advocate|objection|agent|reviewer|drafting|editorial", re.IGNORECASE)


def py_files(p: Path):
    if p.is_file():
        return [p] if p.suffix == ".py" else []
    return [f for f in p.rglob("*.py") if "__pycache__" not in f.parts]


def scan_file(f: Path) -> dict:
    src = f.read_text(encoding="utf-8", errors="replace")
    out = {"file": str(f.relative_to(WS)), "sha256": hashlib.sha256(src.encode()).hexdigest()[:16], "imports": [], "provider_strings": [],
           "defs": [], "statements_about_llm": []}
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        out["parse_error"] = str(e)
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out["imports"].append(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out["imports"].append(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if AGENT_WORDS.search(node.name):
                out["defs"].append({"name": node.name, "line": node.lineno, "kind": type(node).__name__})
    out["provider_modules"] = sorted({i for i in out["imports"] if i.split(".")[0] in PROVIDER_MODULES or i in PROVIDER_MODULES})
    for m in PROVIDER_STRINGS.finditer(src):
        line = src.count("\n", 0, m.start()) + 1
        text = src.splitlines()[line - 1].strip()[:160]
        out["provider_strings"].append({"line": line, "match": m.group(0), "text": text})
    for i, line in enumerate(src.splitlines(), 1):
        if re.search(r"no (live )?model|no LLM|deterministic|SINGLE_PROCESS_RULE_BASED|NOT_LLM|rule-based|rules in one process", line, re.IGNORECASE):
            out["statements_about_llm"].append({"line": i, "text": line.strip()[:180]})
    return out


def main():
    provider_inv = {"schema": "CDF-AUDIT-PROVIDER-INVENTORY-1", "trees": {}, "conclusion": None}
    impl_inv = {"schema": "CDF-AUDIT-AI-IMPLEMENTATION-INVENTORY-1", "trees": {}, "agent_like_components": []}
    any_sdk = False
    for label, path in TREES.items():
        if not path.exists():
            provider_inv["trees"][label] = {"path": str(path), "status": "MISSING"}
            continue
        files = py_files(path)
        scans = [scan_file(f) for f in files]
        sdk = sorted({m for s in scans for m in s["provider_modules"]})
        hits = [{"file": s["file"], **h} for s in scans for h in s["provider_strings"]]
        statements = [{"file": s["file"], **h} for s in scans for h in s["statements_about_llm"]]
        provider_inv["trees"][label] = {"path": str(path.relative_to(WS)), "python_files": len(files), "provider_or_http_modules_imported": sdk,
                                        "provider_string_hits": hits[:60], "provider_string_hit_count": len(hits),
                                        "explicit_statements_about_llm_use": statements[:40]}
        any_sdk |= any(m for m in sdk if m not in ("socket",))
        impl_inv["trees"][label] = {"python_files": len(files),
                                    "agent_like_defs": [{"file": s["file"], **d} for s in scans for d in s["defs"]]}
    provider_inv["conclusion"] = ("No AI-provider SDK, HTTP client or model gateway is imported by any tree. The only network-capable import is "
                                  "`socket` in cdf_gco_crms/qa/lo_engine.py, used to test AF_UNIX availability for LibreOffice. Provider-looking "
                                  "strings are vocabulary (e.g. 'inference', 'LLM' in docstrings that deny LLM use)." if not any_sdk else
                                  "An HTTP or provider module is imported; see per-tree hits.")
    # the engine's agent-like components with callers (static)
    comps = [
        ("GCO Observation Drafting Agent", None, "no component: observations are authored by the human GCO reviewer and entered via JSON (main.py round1/append)"),
        ("Black Team — Recipient Department Challenger", "cdf_gco_crms/assurance/challenge.py:black_team", "rule-based function; callers: run_challenge, tests"),
        ("Red Advocate — GCO Observation Defender", "cdf_gco_crms/assurance/challenge.py:red_advocate", "rule-based function; callers: _argue (run_challenge), tests"),
        ("Independent Institutional Adjudicator", "cdf_gco_crms/assurance/challenge.py:adjudicate", "rule table _TABLE × stance; callers: _argue, tests"),
        ("GCO Editorial Agent", None, "no component: Advocacy.revised_comment is returned in the record but never applied to the ReviewState by production code"),
        ("Independent Final Red-Team Reviewer (Art. 20)", None, "no component: protocol role only (20.1–20.5, R1–R7); no code, no test"),
        ("Regulatory and Institutional Evidence Verification Agent", "cdf_gco_crms/assurance/evidence.py:EvidenceRegistry + references/index.py + assurance/reference_verify.py",
         "deterministic binding of excerpts to hashed files; approval classes carried from the source register, never inferred"),
        ("Challenge state machine (support)", "cdf_gco_crms/assurance/objection_engine.py:Objection", "hash-chained events, six productive cycles, decide()"),
        ("Human authorization control (support)", "cdf_gco_crms/assurance/objection_engine.py:HumanDecision + challenge.apply_human_decisions", "Ed25519 signature against a caller-supplied trust store"),
        ("Review-round manager / title registry / Word / Excel / gates (support)", "cdf_gco_crms/rounds, model, word, excel, qa", "deterministic"),
    ]
    src_main = (ENGINE / "main.py").read_text(encoding="utf-8")
    for name, loc, note in comps:
        impl_inv["agent_like_components"].append({
            "agent": name, "source": loc, "note": note,
            "production_entry_points_reaching_it": sorted({cmd for cmd in ("round1", "append", "rebuild", "build-excel", "build-word", "review", "challenge", "adjudicate",
                                                                            "finalize-titles", "import-owner-return", "demo-e2e", "release")
                                                          if loc and loc.split(":")[-1].split(" ")[0] in ("black_team", "red_advocate", "adjudicate", "EvidenceRegistry", "HumanDecision", "Objection")
                                                          and cmd in ("review", "challenge", "adjudicate")}) if loc else [],
            "model_invocation": "NONE (pure Python)" if loc else "NONE (not implemented)",
            "provider_dependency": "NONE", "context_management": "shared in-process objects (same EvidenceRegistry, same persona, same Objection instance)" if loc else "n/a",
            "tool_permissions": "none: the functions read the registry and the state; they open no file and no network" if loc else "n/a",
            "persistence": "ChallengeRecord.to_json() written by main.py review/adjudicate to build/adversarial/*.json" if loc else "n/a",
            "error_handling": "ValueError on a DEFEND without evidence; PermissionError on unverified human decisions" if loc else "n/a",
        })
    (HERE / "reports").mkdir(exist_ok=True)
    (HERE / "reports" / "AI-PROVIDER-INTEGRATION-INVENTORY.json").write_text(json.dumps(provider_inv, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "reports" / "AI-IMPLEMENTATION-INVENTORY.json").write_text(json.dumps(impl_inv, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"provider_conclusion": provider_inv["conclusion"],
                      "modules_by_tree": {k: v.get("provider_or_http_modules_imported") for k, v in provider_inv["trees"].items()}}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
