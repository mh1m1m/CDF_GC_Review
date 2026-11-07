"""Public-safe regression tests for the fail-closed CLI issuance policy (synthetic only).

Origin: PR #2 (fix/v712-fail-closed-cli). Kept on the feature branch with the semantics of the central release
gate: an official issue needs a passing Authorization; a flag never authorises; drafts are classified by name.
Run with: python -m unittest discover -s qa_public -p 'test_*.py' -v   (or pytest qa_public)
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
    DRAFT_CLASSIFICATION, DRAFT_PREFIX, IssuanceDenied, authorize_cli_export, draft_path,
)
from cdf_gco_crms.release.authorization_gate import Authorization


class IssuanceGateTests(unittest.TestCase):
    def test_default_is_fail_closed(self):
        with self.assertRaisesRegex(IssuanceDenied, "RELEASE_GATE_REQUIRED"):
            authorize_cli_export("review.xlsx")
        with self.assertRaisesRegex(IssuanceDenied, "RELEASE_GATE_REQUIRED"):
            authorize_cli_export("review.docx", internal_draft=False)

    def test_issue_is_never_approved_by_draft_flag(self):
        for internal_draft in (True, False):
            with self.subTest(internal_draft=internal_draft):
                with self.assertRaisesRegex(IssuanceDenied, "OFFICIAL_ISSUANCE_NOT_AUTHORIZED"):
                    authorize_cli_export("review.xlsx", internal_draft=internal_draft, issuance_requested=True)

    def test_only_a_passing_authorization_permits_an_official_path(self):
        denied = Authorization(False, "f" * 64, ["NO_REVIEW_RECORD_FOR_THIS_CONTENT"])
        with self.assertRaisesRegex(IssuanceDenied, "RELEASE_GATE_REQUIRED"):
            authorize_cli_export("review.xlsx", authorization=denied)
        granted = Authorization(True, "f" * 64, [])
        self.assertEqual(authorize_cli_export("a/review.xlsx", authorization=granted), Path("a/review.xlsx"))
        self.assertEqual(authorize_cli_export("a/review.xlsx", authorization=granted, issuance_requested=True),
                         Path("a/review.xlsx"))

    def test_drafts_have_stable_explicit_names(self):
        p = Path("a/b") / "review.xlsx"
        got = authorize_cli_export(p, internal_draft=True)
        self.assertEqual(got, Path("a/b") / (DRAFT_PREFIX + "review.xlsx"))
        self.assertEqual(draft_path(got), got)
        self.assertEqual(DRAFT_CLASSIFICATION, "INTERNAL_DRAFT_NOT_APPROVED")

    def test_missing_inputs_never_produce_output(self):
        from main import main, RC_INPUT, RC_REFUSED
        cases = [
            ["round1", "DOES_NOT_EXIST.json", "output"],
            ["append", "DOES_NOT_EXIST.xlsx", "DOES_NOT_EXIST.json", "output"],
            ["rebuild", "DOES_NOT_EXIST.xlsx", "output"],
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
                    self.assertIn(result, (RC_INPUT, RC_REFUSED))
                    payload = json.loads(out.getvalue()[out.getvalue().index("{"):])
                    self.assertIn(payload["status"], ("INPUT_ERROR", "REFUSED"))
                    self.assertTrue(payload["no_output_generated"])
                    self.assertFalse((root / "output").exists())

    def test_issue_flag_is_refused_before_any_input_is_read_in_draft_mode(self):
        from main import main, RC_REFUSED
        cases = [
            ["build-excel", "DOES_NOT_EXIST.xlsx", "output", "--issue", "--internal-draft"],
            ["finalize-titles", "DOES_NOT_EXIST.xlsx", "DOES_NOT_EXIST.json", "output", "--issue", "--internal-draft"],
        ]
        for argv in cases:
            with self.subTest(cmd=argv[0]):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    result = main(argv)
                self.assertEqual(result, RC_REFUSED)
                self.assertIn("OFFICIAL_ISSUANCE_NOT_AUTHORIZED", out.getvalue())
                self.assertIn(DRAFT_CLASSIFICATION, out.getvalue())


if __name__ == "__main__":
    unittest.main()
