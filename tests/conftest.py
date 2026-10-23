import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cdf_gco_crms.config import round_schema as S  # noqa: E402
from cdf_gco_crms.model.entities import GText, Segment  # noqa: E402
from cdf_gco_crms.references.synthetic_index import load_reference_index, real_sources_available  # noqa: E402
from cdf_gco_crms.regression import synthetic as SY  # noqa: E402
from cdf_gco_crms.rounds.round_expansion import NewObservation  # noqa: E402

C, CC, RE, O = S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN


def base_obs(n):
    return [SY.topic_obs(i) for i in range(n)]


def new_obs(i, reason="أُضيف البند في النسخة المحدثة."):
    return NewObservation(f"ص.{20 + i}، المادة (20) – البند (20-{i})", f"نص مضاف {i} …",
                          GText([Segment("نوصي بربط البند بموافقة صاحب الصلاحية.", False)]), reason=reason)


def history(traj, new=None, *, rounds, outdir=None, code="TST", build_rounds=None, seed=11, silence=0.0):
    doc = SY.fixture_document(code)
    return SY.run_history(doc, base_obs(len(traj)), [list(t) for t in traj], new or {}, rounds=rounds,
                          outdir=outdir, build_rounds=build_rounds, seed=seed, silence=silence,
                          dates={r: f"2026-{(r % 12) + 1:02d}-15" for r in range(1, rounds + 1)},
                          versions={r: f"الإصدار 0.{r}" for r in range(1, rounds + 1)})


@pytest.fixture(scope="session")
def five_round(tmp_path_factory):
    """TEST 04 history: closure, reopening, reclosure, conditional, stalled, new observations."""
    traj = [
        [O, C, C, C, C],        # 01 closed r2
        [O, C, C, RE, C],       # 02 closed, reopened r4, reclosed r5
        [O, C, C, RE, RE],      # 03 closed r2, reopened r4 (TEST E)
        [O, CC, CC, C, C],      # 04 conditional then closed
        [O, RE, RE, RE, RE],    # 05 stalled
        [O, O, O, O, O],        # 06 stalled open
        [O, RE, C, C, C],       # 07
        [O, CC, RE, CC, C],     # 08
        [O, O, RE, C, C],       # 09
        [O, RE, CC, CC, CC],    # 10 condition unmet
    ]
    new = {3: [(new_obs(1), [O, RE, C])], 4: [(new_obs(2), [O, O])]}
    out = tmp_path_factory.mktemp("five")
    h = history(traj, new, rounds=5, outdir=out, code="FIV")
    return h, traj, out


@pytest.fixture(scope="session")
def reference_index():
    """The authority reference index for tests: the institutional sources when they are on disk, else the public
    SYNTHETIC fixture (``cdf_gco_crms.references.synthetic_index``). ``CDF_TEST_SYNTHETIC_REFERENCE=1`` forces the
    fixture so that the public-clone path can be exercised on a machine that holds the sources."""
    if os.environ.get("CDF_TEST_SYNTHETIC_REFERENCE") == "1":
        return load_reference_index(synthetic="always")
    return load_reference_index(synthetic="if-missing")


@pytest.fixture(scope="session")
def institutional_sources_present() -> bool:
    return real_sources_available() and os.environ.get("CDF_TEST_SYNTHETIC_REFERENCE") != "1"
