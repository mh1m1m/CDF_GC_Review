"""Vercel Python function: hosted MCP endpoint (/mcp) for the synthetic demo (cdf_gco_crms.interfaces.hosted_mcp)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CDF_CALIBRATION_MODE", "HOSTED_SYNTHETIC_DEMO")
os.environ.setdefault("CDF_OPERATION_MODE", "PUBLIC_SYNTHETIC_DEMO")
os.environ.setdefault("CDF_JOB_RUNNER", "inline")
os.environ.setdefault("CDF_DATABASE_SCHEMA", "cdf")
os.environ.setdefault("CDF_CALIBRATION_DB", str(Path(tempfile.gettempdir()) / "cdf-hosted" / "placeholder.sqlite"))

from apps.api import main as api  # noqa: E402  (same configuration, store and verifier as the API)
from cdf_gco_crms.interfaces.hosted_mcp import hosted_mcp  # noqa: E402

app = hosted_mcp(api.application, api.VERIFIER, api._DB_LOCK)
