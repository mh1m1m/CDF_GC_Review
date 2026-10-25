"""D17: the acceptance harnesses refuse to run with assertions disabled, so they can never write PASS unchecked."""
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", ["cdf_gco_crms.acceptance.unified", "cdf_gco_crms.acceptance.phase2"])
def test_harness_refuses_optimized_interpreter(module, tmp_path):
    r = subprocess.run([sys.executable, "-O", "-m", module, "--report-dir", str(tmp_path / "out")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "ACCEPTANCE_REQUIRES_ASSERTIONS" in (r.stderr + r.stdout)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").rglob("*summary*.json"))
