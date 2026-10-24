"""Failure-path regressions for the bounded stable-runtime diagnostic."""
import os
from pathlib import Path
import sys
import time

import pytest

from tools.libreoffice_smoke import run_bounded, stable_version


@pytest.mark.parametrize('version', ['LibreOfficeDev 26.8.0.0.alpha0', 'LibreOffice 25.2.0.0.beta1',
                                      'LibreOffice 25.2.0.0rc1', 'LibreOffice nightly', ''])
def test_rejects_prerelease(version):
    assert not stable_version(version)


def test_accepts_stable_distribution_version():
    assert stable_version('LibreOffice 25.2.3.2 520(Build:2)')


def test_timeout_reaps_spawned_child(tmp_path):
    import subprocess
    marker = tmp_path / 'child.pid'
    script = ("import subprocess,sys,time; "
              "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
              "open(sys.argv[1],'w').write(str(p.pid)); time.sleep(60)")
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable, '-c', script, str(marker)], 2)
    child_pid = int(marker.read_text())
    for _ in range(20):
        status = Path(f'/proc/{child_pid}/status')
        if not status.exists() or '\nState:\tZ' in status.read_text():
            break
        time.sleep(.05)
    else:
        pytest.fail('Timed-out invocation left a live child behind')
    # The test runner is outside the invocation's isolated group and remains alive.
    assert os.getpid() != child_pid


@pytest.mark.parametrize('problem', ['skip', 'missing'])
def test_required_engine_tests_cannot_silently_skip(tmp_path, problem):
    from tools.libreoffice_validate import REQUIRED, require_engine_results
    import xml.etree.ElementTree as ET
    suite = ET.Element('testsuite')
    for node in REQUIRED:
        filename, name = node.split('::')
        case = ET.SubElement(suite, 'testcase', name=name,
                             classname=filename.removesuffix('.py').replace('/', '.'))
    if problem == 'skip':
        ET.SubElement(case, 'skipped', message='LibreOffice not available')
    else:
        suite.remove(case)
    report = tmp_path / 'engine.xml'
    ET.ElementTree(suite).write(report)
    with pytest.raises(AssertionError):
        require_engine_results(report)
