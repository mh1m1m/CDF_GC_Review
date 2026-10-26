"""Vercel Python function: the calibration and intelligence API in HOSTED_SYNTHETIC_DEMO mode.

Every /api/* request is rewritten here (vercel.json). Configuration comes from the project's environment
variables (see docs/deploy/HOSTED_DEMO.md); nothing secret is committed. The hosted mode refuses to start
without CDF_DATABASE_URL and CDF_SUPABASE_URL, accepts only SYN- cases and never issues documents.
"""
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
os.environ.setdefault("CDF_CALIBRATION_DB", str(Path(tempfile.gettempdir()) / "cdf-hosted" / "placeholder.sqlite"))  # path only names the schema

from apps.api.main import app  # noqa: E402,F401  (ASGI entry point)
