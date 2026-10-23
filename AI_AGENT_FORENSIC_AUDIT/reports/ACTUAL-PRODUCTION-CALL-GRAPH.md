# ACTUAL PRODUCTION CALL GRAPH — CDF–GCO–CRMS v7.12 (execution evidence, not an import graph)

Traced in-process with `sys.setprofile` on the engine package while running `main.py` commands on the synthetic case DA-01; a socket guard refused and recorded any outbound connection. Raw edge lists: `evidence/runtime_callgraphs/*.json`.

| Command | rc | Calls into assurance.challenge | Excel builder | Word builder | Socket attempts | First key calls (order) |
|---|---|---|---|---|---|---|
| 01_round1 | BuildResult | no | YES | no | 0 | build_round1 → build_workbook |
| 02_build-excel | 0 | no | YES | no | 0 | parse_workbook → require_safe → build_workbook |
| 03_build-word | 0 | no | no | YES | 0 | parse_workbook → require_safe → comment_document |
| 04_review | 0 | YES | no | no | 0 | parse_workbook → require_safe → from_index → run_challenge → black_team → bind_clause → _argue → red_advocate → adjudicate |
| 05_challenge | 0 | YES | no | no | 0 | parse_workbook → require_safe → from_index → run_challenge → black_team → bind_clause → _argue → red_advocate → adjudicate |
| 06_adjudicate | 0 | YES | no | no | 0 | parse_workbook → require_safe → from_index → run_challenge → black_team → bind_clause → _argue → red_advocate → adjudicate |
| 07_finalize-titles | 3 | no | no | no | 0 | parse_workbook → require_safe → finalize_titles |
| 08_finalize-titles-with-wording | 0 | no | YES | no | 0 | parse_workbook → require_safe → finalize_titles → mark_titles_issued → build_workbook |

## Observations

- round1 does not carry the 'title' field of its JSON into NewObservation (07_finalize-titles refused: 'nothing to approve'); the proposal must be supplied again in the decision file (08).
- Every production build command (round1, build-excel, build-word, finalize-titles) completes WITHOUT any call into assurance.challenge: the challenge is not on the issuance path; it runs only when the operator invokes review/challenge/adjudicate separately.
- No command attempted an outbound socket connection: there is no provider call anywhere in the traced runtime.
- review/challenge/adjudicate call black_team → red_advocate → adjudicate inside one process on shared objects (no separate execution identity).

## Caller → callee edges of the review command (top 40 by frequency)

- `cdf_gco_crms.references.textnorm:repair_ligatures` → `cdf_gco_crms.references.textnorm:<genexpr>` ×533711
- `cdf_gco_crms.references.textnorm:nfc` → `cdf_gco_crms.references.textnorm:strip_marks` ×30058
- `cdf_gco_crms.references.textnorm:nfc` → `cdf_gco_crms.references.textnorm:repair_ligatures` ×30058
- `cdf_gco_crms.references.textnorm:match_key` → `cdf_gco_crms.references.textnorm:nfc` ×24372
- `cdf_gco_crms.assurance.evidence:stem` → `cdf_gco_crms.references.textnorm:match_key` ×17679
- `cdf_gco_crms.assurance.evidence:content_words` → `cdf_gco_crms.assurance.evidence:stem` ×17622
- `cdf_gco_crms.references.authority_matrix:_cell_text` → `cdf_gco_crms.references.authority_matrix:<lambda>` ×7380
- `cdf_gco_crms.references.authority_matrix:_cell_text` → `cdf_gco_crms.references.authority_matrix:<genexpr>` ×4767
- `cdf_gco_crms.references.authority_matrix:<genexpr>` → `cdf_gco_crms.references.authority_matrix:logical_order` ×3690
- `cdf_gco_crms.references.org_structure:_segments` → `cdf_gco_crms.references.textnorm:nfc` ×3414
- `cdf_gco_crms.references.org_structure:unit` → `cdf_gco_crms.references.textnorm:match_key` ×3258
- `cdf_gco_crms.references.authority_matrix:_parse_page` → `cdf_gco_crms.references.authority_matrix:col_of` ×2801
- `cdf_gco_crms.references.authority_matrix:_parse_page` → `cdf_gco_crms.references.authority_matrix:band_of` ×2801
- `cdf_gco_crms.references.org_structure:_page_lines` → `cdf_gco_crms.references.org_structure:_segments` ×2167
- `cdf_gco_crms.references.authority_matrix:_parse_page` → `cdf_gco_crms.references.authority_matrix:_cell_text` ×1444
- `cdf_gco_crms.references.authority_matrix:_parse_page` → `cdf_gco_crms.references.authority_matrix:<genexpr>` ×1290
- `cdf_gco_crms.references.authority_matrix:canonical_body` → `cdf_gco_crms.references.textnorm:match_key` ×1210
- `cdf_gco_crms.assurance.evidence:content_words` → `cdf_gco_crms.references.textnorm:nfc` ×1146
- `cdf_gco_crms.references.org_structure:_page_lines` → `cdf_gco_crms.references.textnorm:strip_marks` ×1145
- `cdf_gco_crms.assurance.evidence:task_stems` → `cdf_gco_crms.assurance.evidence:<genexpr>` ×1003
- `cdf_gco_crms.assurance.evidence:best_task_overlap` → `cdf_gco_crms.assurance.evidence:<genexpr>` ×954
- `cdf_gco_crms.assurance.evidence:<genexpr>` → `cdf_gco_crms.assurance.evidence:content_words` ×925
- `cdf_gco_crms.references.authority_matrix:<genexpr>` → `cdf_gco_crms.references.textnorm:match_key` ×916
- `cdf_gco_crms.references.authority_matrix:classify_role` → `cdf_gco_crms.references.textnorm:match_key` ×894
- `cdf_gco_crms.references.authority_matrix:_cell_text` → `cdf_gco_crms.references.textnorm:nfc` ×813
- `cdf_gco_crms.references.authority_matrix:sort_key` → `cdf_gco_crms.references.authority_matrix:<genexpr>` ×435
- `cdf_gco_crms.references.authority_matrix:_parse_page` → `cdf_gco_crms.references.authority_matrix:classify_role` ×287
- `cdf_gco_crms.references.authority_matrix:classify_role` → `cdf_gco_crms.references.textnorm:nfc` ×286
- `cdf_gco_crms.ingestion.safe_open:inspect_package` → `cdf_gco_crms.ingestion.safe_open:<genexpr>` ×264
- `cdf_gco_crms.references.org_structure:_parse_division` → `cdf_gco_crms.references.textnorm:match_key` ×218
- `cdf_gco_crms.assurance.evidence:find_matter` → `cdf_gco_crms.assurance.evidence:<genexpr>` ×191
- `cdf_gco_crms.references.authority_matrix:_parse_page` → `cdf_gco_crms.references.authority_matrix:<lambda>` ×163
- `cdf_gco_crms.references.org_structure:parse_org_text` → `cdf_gco_crms.references.textnorm:match_key` ×160
- `cdf_gco_crms.references.org_structure:_parse_tasks` → `cdf_gco_crms.references.org_structure:_header_kind` ×150
- `cdf_gco_crms.assurance.evidence:find_matter` → `cdf_gco_crms.assurance.evidence:content_words` ×142
- `cdf_gco_crms.references.authority_matrix:parse_matrix` → `cdf_gco_crms.references.authority_matrix:sort_key` ×141
- `cdf_gco_crms.references.org_structure:_parse_division` → `cdf_gco_crms.references.org_structure:_header_kind` ×128
- `cdf_gco_crms.references.authority_matrix:_parse_page` → `cdf_gco_crms.references.authority_matrix:canonical_body` ×121
- `cdf_gco_crms.references.org_structure:parse_org_text` → `cdf_gco_crms.references.org_structure:_header_kind` ×95
- `cdf_gco_crms.references.org_structure:parse_org_text` → `cdf_gco_crms.references.org_structure:_page_lines` ×92
