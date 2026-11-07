"""Run smoke, required engine tests (no skips), then the full public-safe suite."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.libreoffice_smoke import run_bounded

REQUIRED = [
    'tests/test_e2e.py::test_e2e_round5_word_renders_and_workbook_recalculates',
    'tests/test_regression.py::test_10_formula_reconciliation',
    'tests/test_regression.py::test_11_navigation_after_owner_sort',
    'tests/test_regression.py::test_16_visual_render_and_layout',
    'tests/test_regression.py::test_19b_historical_selection_in_spreadsheet',
    'tests/test_word_lifecycle.py::test_lifecycle_libreoffice_renders_final_docx',
]


def require_engine_results(path: Path) -> None:
    cases = list(ET.parse(path).iter('testcase'))
    for node in REQUIRED:
        filename, name = node.split('::')
        classname = filename.removesuffix('.py').replace('/', '.')
        matches = [case for case in cases if case.get('name') == name and case.get('classname') == classname]
        if len(matches) != 1:
            raise AssertionError(f'Required LibreOffice test missing or duplicated: {node}')
        if any(matches[0].find(tag) is not None for tag in ('skipped', 'failure', 'error')):
            raise AssertionError(f'Required LibreOffice test did not pass: {node}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, default=Path('build/libreoffice'))
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    tasks = [
        ('smoke', [sys.executable, 'tools/libreoffice_smoke.py', '--report', str(args.evidence / 'smoke.json')], 180),
        # The existing e2e module builds its round artifacts in preceding tests.
        ('engine', [sys.executable, '-m', 'pytest', 'tests/test_e2e.py', *REQUIRED[1:], '-q', '-rs', '-p', 'no:cacheprovider',
                    '--junitxml=' + str(args.evidence / 'engine.xml')], 900),
        ('public', [sys.executable, '-m', 'pytest', 'tests', 'qa_public', '-q', '-rs', '-p', 'no:cacheprovider',
                    '--junitxml=' + str(args.evidence / 'public.xml')], 1200),
    ]
    for name, command, timeout in tasks:
        try:
            result = run_bounded(command, timeout)
            (args.evidence / (name + '.log')).write_text(result.stdout + result.stderr)
            print(result.stdout, flush=True)
            if name != 'smoke':
                require_engine_results(args.evidence / (name + '.xml'))
        except Exception as exc:
            (args.evidence / (name + '.log')).write_text((getattr(exc, 'stdout', '') or '') + (getattr(exc, 'stderr', '') or ''))
            (args.evidence / (name + '-failure.log')).write_text(f'{type(exc).__name__}: {exc}\n')
            print(f'{name}: FAILED: {type(exc).__name__}: {exc}', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
