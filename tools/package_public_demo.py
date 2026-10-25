"""Build an explicit public-only Docker context from tracked source and built UI.

No private mounts, dotenv/configuration files, institutional datasets or databases
are copied. Build the pinned stable runtime as cdf-lo-stable before this image.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SHARED={'shared/demo-reference-fixtures.json','shared/logo-registry.json','shared/visual-tokens.json','shared/rendering-specification.json'}
PUBLIC_ASSETS={'apps/web/public/demo-mark-on-dark.svg'}   # the public demo never ships an institution's wordmark (audit C5)
TOOLS={'tools/public_demo_entrypoint.py','tools/seed_visual_demo.py','tools/mat_dna/seed_calibration_demo.py'}


def package(output:Path):
    output=output.resolve()
    if output==ROOT or output in ROOT.parents:raise ValueError('UNSAFE_PACKAGE_DESTINATION')
    if output.exists():raise FileExistsError('Use a new empty package destination')
    files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    selected=[p for p in files if p and ((p.startswith('cdf_gco_crms/') and p.endswith('.py'))
        or (p.startswith('apps/api/') and p.endswith('.py')) or p in SHARED or p in TOOLS or p in PUBLIC_ASSETS
        or p=='tests/fixtures/mat/synthetic_mat_profile.json')]
    output.mkdir(parents=True)
    manifest=[]
    for relative in selected:
        source=ROOT/relative
        if not source.is_file():continue
        destination=output/'repo'/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
        manifest.append({'path':relative,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
    ui=ROOT/'apps/web/dist'
    if not (ui/'index.html').is_file():raise FileNotFoundError('Build apps/web before packaging')
    shutil.copytree(ui,output/'ui')
    for path in (output/'ui').rglob('*'):
        if path.is_file():manifest.append({'path':'ui/'+str(path.relative_to(output/'ui')),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (output/'public-package-manifest.json').write_text(json.dumps(manifest,indent=2))
    (output/'Dockerfile').write_text('''ARG RUNTIME_IMAGE=cdf-lo-stable
FROM ${RUNTIME_IMAGE}
COPY --chown=10001:10001 repo /repo
COPY --chown=10001:10001 ui /ui
ENV CDF_OPERATION_MODE=PUBLIC_SYNTHETIC_DEMO CDF_CALIBRATION_MODE=SYNTHETIC_LOCAL_DEV CDF_CALIBRATION_DB=/tmp/public-demo.sqlite CDF_PUBLIC_UI_DIRECTORY=/ui
USER 10001:10001
WORKDIR /repo
CMD ["python","tools/public_demo_entrypoint.py"]
''')
    return len(manifest)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    print('Public package files:',package(parser.parse_args().output))
