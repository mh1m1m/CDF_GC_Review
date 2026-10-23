"""Public-safe regression tests for v7.12 fail-closed CLI issuance (synthetic only).

Run with: python -m unittest discover -s qa_public -p 'test_*.py' -v
No institutional source documents or provider credentials are required.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cdf_gco_crms.assurance.issuance_gate import (
    DRAFT_CLASSIFICATION, DRAFT_PREFIX, IssuanceDenied,
    authorize_cli_export, draft_path,
)


class IssuanceGateTests(unittest.TestCase):
    def test_default_is_fail_closed(self):
        with self.assertRaisesRegex(IssuanceDenied, "RELEASE_GATE_REQUIRED"):
            authorize_cli_export("review.xlsx")
        with self.assertRaisesRegex(IssuanceDenied, "RELEASE_GATE_REQUIRED"):
            authorize_cli_export("review.docx", internal_draft=False)

    def test_issue_is_never_approved_by_draft_flag(self):
        for internal_draft in (True, False):
            with self.subTest(internal_draft=internal_draft):
                with self.assertRaisesRegex(IssuanceDenied, "OFFICIAL_ISSUANCE_DISABLED"):
                    authorize_cli_export("review.xlsx", internal_draft=internal_draft,
                                         issuance_requested=True)

    def test_drafts_have_stable_explicit_names(self):
        p = Path("a/b") / "review.xlsx"
        got = authorize_cli_export(p, internal_draft=True)
        self.assertEqual(got, Path("a/b") / (DRAFT_PREFIX + "review.xlsx"))
        self.assertEqual(draft_path(got), got)
        self.assertEqual(DRAFT_CLASSIFICATION, "INTERNAL_DRAFT_NOT_APPROVED")

    def test_preflight_refuses_before_any_input_is_read(self):
        from main import main, RC_REFUSED
        cases = [
            ["round1", "DOES_NOT_EXIST.json", "output"],
            ["append", "DOES_NOT_EXIST.xlsx", "DOES_NOT_EXIST.json", "output"],
            ["rebuild", "DOES_NOT_EXIST.xlsx", "output"],
            ["migrate", "DOES_NOT_EXIST.xlsx", "output"],
            ["finalize-titles", "DOES_NOT_EXIST.xlsx", "DOES_NOT_EXIST.json", "output"],
            ["build-excel", "DOES_NOT_EXIST.xlsx", "output"],
            ["build-word", "DOES_NOT_EXIST.xlsx", "output.docx"],
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for argv in cases:
                with self.subTest(cmd=argv[0]):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        result = main(argv)
                    self.assertEqual(result, RC_REFUSED)
                    payload = json.loads(out.getvalue())
                    self.assertEqual(payload["status"], "REFUSED")
                    self.assertTrue(payload["no_output_generated"])
                    self.assertFalse((root / "output").exists())

    def test_issue_flag_is_refused_even_in_draft_mode(self):
        from main import main, RC_REFUSED
        cases = [
            ["build-excel", "DOES_NOT_EXIST.xlsx", "output", "--issue", "--internal-draft"],
            ["finalize-titles", "DOES_NOT_EXIST.xlsx", "DOES_NOT_EXIST.json",
             "output", "--issue", "--internal-draft"],
        ]
        for argv in cases:
            with self.subTest(cmd=argv[0]):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    result = main(argv)
                self.assertEqual(result, RC_REFUSED)
                self.assertIn("OFFICIAL_ISSUANCE_DISABLED", out.getvalue())


if __name__ == "__main__":
    unittest.main()
