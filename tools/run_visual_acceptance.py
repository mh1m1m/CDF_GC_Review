"""Run local browser acceptance with an ephemeral token and fictional database only."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory(prefix='cdf-browser-') as temp:
        db=Path(temp)/'synthetic.sqlite'
        from tools.seed_visual_demo import seed
        seed(db)
        subprocess.run([sys.executable,'tools/mat_dna/seed_calibration_demo.py','--db',str(db)],cwd=ROOT,check=True)
        env=os.environ.copy();env.update(CDF_CALIBRATION_MODE='SYNTHETIC_LOCAL_DEV',CDF_CALIBRATION_DB=str(db),
            CDF_CALIBRATION_DEV_TOKEN=secrets.token_urlsafe(36),CDF_AI_PROVIDER='')
        if shutil.which('chromium'): env['CDF_CHROMIUM_EXECUTABLE']=shutil.which('chromium')
        log=(ROOT/'build/browser-api.log');log.parent.mkdir(exist_ok=True)
        with log.open('w') as stream:
            api=subprocess.Popen([sys.executable,'-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port','8765'],cwd=ROOT,env=env,stdout=stream,stderr=stream)
            try:
                for _ in range(60):
                    if api.poll() is not None:raise RuntimeError('API exited; inspect build/browser-api.log')
                    try:
                        with urlopen('http://127.0.0.1:8765/api/health',timeout=1) as response:
                            if response.status==200:break
                    except OSError:pass
                    time.sleep(.25)
                else:raise RuntimeError('API startup timeout')
                args=['npm','run','test:e2e','--',*sys.argv[1:]]
                return subprocess.run(args,cwd=ROOT/'apps/web',env=env,timeout=600).returncode
            finally:
                api.terminate()
                try:api.wait(timeout=5)
                except subprocess.TimeoutExpired:api.kill();api.wait()

if __name__=='__main__':
    sys.path.insert(0,str(ROOT))
    raise SystemExit(main())
