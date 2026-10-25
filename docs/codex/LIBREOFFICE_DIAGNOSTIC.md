# LibreOffice diagnostic — 2026-10-24

## Observed environment
LibreOffice is installed and executable as `soffice` through the managed runtime wrapper. Version: `LibreOfficeDev 26.8.0.0.alpha0`, build `2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`. The `libreoffice` alias is absent. Reinstalling merely to establish availability is unnecessary.

All probes used tiny fictional files under a temporary directory, fresh isolated profiles, bounded execution, and normal local process/socket access. XLSX conversion outputs were directed to a separate directory. No source documents or private inputs were used.

| Probe | Result |
|---|---|
| `soffice --version` | PASSED |
| Writer plain text → PDF | PASSED; nonempty PDF, 12,145 bytes |
| Three-cell XLSX: A1=2, A2=3, A3=SUM(A1:A2), existing project macro | FAILED: `LOResult(ok=False, message='timeout')`, 10-second recalculation bound |
| Same XLSX → XLSX using explicit Calc filter and separate output/profile | FAILED: 30-second bound, no output workbook; expected cached value 5 could not be checked |
| CSV with one numeric row → ODS | FAILED: exit 124 after 15 seconds, no output |
| XLSX conversion with OpenCL/threaded calculation disabled | FAILED: forced termination (exit 137) after 15-second bound plus kill grace; no output |

The generated macro library was registered: `script.xlc`, `Standard/script.xlb` and `Module1.xba` were present. A system-call-summary probe yielded no usable trace, so no diagnosis is based on it.

## Conclusion and limits
The timeout is reproducible without the CDF workbook and without its macro. Writer conversion works while these Calc import/export probes do not. This narrows the failure to the local Calc execution path or configuration; the precise internal cause is NOT_VERIFIED. It is not evidence that Codex cannot run LibreOffice, and it does not establish a formula defect in the CDF workbook. The development/alpha version is an environment fact, not proof that a particular upstream bug is responsible.

No release gate, formula assertion, or skip condition was changed to conceal the failure. Independent spreadsheet recalculation remains unverified. Before production acceptance, validate a stable LibreOffice build first on this smoke workbook and then on the existing six LibreOffice tests. Test Writer DOCX → PDF separately with a synthetic DOCX if that specific conversion is required; this probe used plain text. Impress was not tested.

## Reproduction
Use a unique temporary directory rather than a shared profile, and use `soffice` on this runtime:

```sh
python - <<'PYTHON'
from pathlib import Path
from tempfile import mkdtemp
from openpyxl import Workbook
root = Path(mkdtemp(prefix='cdf-lo-smoke-'))
book = Workbook()
sheet = book.active
sheet['A1'] = 2
sheet['A2'] = 3
sheet['A3'] = '=SUM(A1:A2)'
book.save(root / 'small.xlsx')
print(root)
PYTHON
# Set probe_root to the path printed above.
mkdir -p "$probe_root/output"
timeout -k 2s 30s soffice \
  "-env:UserInstallation=file://$probe_root/profile" \
  --headless --convert-to 'xlsx:Calc MS Excel 2007 XML' \
  --outdir "$probe_root/output" "$probe_root/small.xlsx"
```

On a working runtime, reopen the **output** workbook with `openpyxl.load_workbook(..., data_only=True)` and assert A3 equals 5. An exit code or file existence alone is not a recalculation result. The source must remain unchanged.

## Independent CI evidence
PR 6 source `f2ff9b6708e6ac438ecfcd71eab737d5e3e07615`: Actions run [40064935332](https://github.com/mh1m1m/CDF_GC_Review/actions/runs/40064935332) completed successfully in all three jobs: Python public-safe tests, TypeScript/Vite build and Chromium browser E2E. This independently verifies that source head's browser tests despite the local Chromium download restriction. The workflow does not install LibreOffice, so its success must not be used to claim Calc reconciliation. A dedicated stable-LibreOffice CI job remains a follow-on improvement.
