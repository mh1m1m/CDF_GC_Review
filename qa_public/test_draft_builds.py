"""Integration smoke: synthetic CLI exports without a release authorisation are explicitly internal drafts.

Origin: PR #2 (fix/v712-fail-closed-cli); kept with the central-gate semantics. No confidential reference files.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from main import main, RC_OK, RC_REFUSED
from cdf_gco_crms.assurance.issuance_gate import DRAFT_PREFIX
from cdf_gco_crms.release.authorization_gate import docx_is_working_copy, xlsx_is_working_copy


class PublicSyntheticDraftBuilds(unittest.TestCase):
    def test_round1_excel_rebuild_and_word_all_draft_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec = {
                "document": {
                    "name": "Synthetic Protocol Example", "code": "TS",
                    "cover_version": "0.1", "owning_department": "Synthetic Testing",
                    "is_demo": True,
                },
                "date": "2026-10-23",
                "observations": [{
                    "location": "Article 1",
                    "quote": "This synthetic passage is not an institutional document.",
                    "comment": "Governance observation: the proposed rule needs a documented approval step.",
                }],
            }
            inp = root / "case.json"
            inp.write_text(json.dumps(spec), encoding="utf-8")
            r1 = root / "r1"
            with contextlib.redirect_stdout(io.StringIO()):
                main(["round1", str(inp), str(r1)])                        # a round-1 draft is always a draft
            xlsx = next(r1.glob("*.xlsx"))
            self.assertTrue(xlsx.name.startswith(DRAFT_PREFIX) and xlsx_is_working_copy(xlsx))

            out = root / "rebuild"
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["build-excel", str(xlsx), str(out)])            # no review record: refused, nothing written
            self.assertEqual(rc, RC_REFUSED)
            self.assertFalse(out.exists() and any(out.iterdir()))
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["build-excel", str(xlsx), str(out), "--internal-draft"])
            self.assertEqual(rc, RC_OK)
            self.assertTrue((out / xlsx.name).is_file() and xlsx_is_working_copy(out / xlsx.name))

            docx_out = root / "review.docx"
            with contextlib.redirect_stdout(io.StringIO()):
                rc_word = main(["build-word", str(xlsx), str(docx_out), "--internal-draft"])
            self.assertEqual(rc_word, RC_OK)
            draft_docx = root / (DRAFT_PREFIX + docx_out.name)
            self.assertTrue(draft_docx.is_file() and docx_is_working_copy(draft_docx))
            self.assertFalse(docx_out.exists())


if __name__ == "__main__":
    unittest.main()
