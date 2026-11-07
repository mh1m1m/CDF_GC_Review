"""Render a workbook to PNG pages through LibreOffice (visual inspection, Art. 16 of the dashboard directive)."""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cdf_gco_crms.qa import lo_engine  # noqa: E402


def render(xlsx: str, outdir: str, dpi: int = 80, first: int = 1, last: int = 3, recalc: bool = False) -> list[Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    work = out / (Path(xlsx).stem[:40] + "_render.xlsx")
    shutil.copy(xlsx, work)
    if recalc:
        lo_engine.recalc(work)
    pdf = lo_engine.to_pdf(work, out)
    prefix = out / "page"
    for old in out.glob("page-*.png"):
        old.unlink()
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(first), "-l", str(last), str(pdf), str(prefix)],
                   check=True)
    return sorted(out.glob("page-*.png"))


if __name__ == "__main__":
    print(render(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 80))
