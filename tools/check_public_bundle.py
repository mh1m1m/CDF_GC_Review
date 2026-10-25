"""Fail-closed validation of fictional configuration-leakage acceptance probes."""
from pathlib import Path
import argparse

SENTINEL=b'SYNTHETIC_BUILD_ISOLATION_SENTINEL'


def check(dist:Path,rejection_log:Path):
    if not (dist/'index.html').is_file():raise AssertionError('PUBLIC_BUNDLE_MISSING')
    files=[p for p in dist.rglob('*') if p.is_file()]
    if any(SENTINEL in p.read_bytes() for p in files):
        raise AssertionError('BACKEND_CONFIGURATION_IN_PUBLIC_BUNDLE')
    log=rejection_log.read_text()
    if 'PRIVATE_CONFIGURATION_CANNOT_ENTER_CLIENT_BUILD' not in log:
        raise AssertionError('PRIVATE_CLIENT_CONFIGURATION_REJECTION_NOT_VERIFIED')
    if 'SYNTHETIC_REJECTION_SENTINEL' in log:
        raise AssertionError('PRIVATE_CONFIGURATION_VALUE_LOGGED')
    print('PUBLIC_BUNDLE_CONFIGURATION_BOUNDARY: PASSED')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dist',type=Path,required=True);parser.add_argument('--rejection-log',type=Path,required=True);args=parser.parse_args();check(args.dist,args.rejection_log)
