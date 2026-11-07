from pathlib import Path
import pytest
from tools.check_public_bundle import check,SENTINEL


def test_configuration_probe_accepts_only_a_built_clean_client_and_explicit_rejection(tmp_path):
    dist=tmp_path/'dist';dist.mkdir();(dist/'index.html').write_text('Synthetic public application')
    log=tmp_path/'rejected.log';log.write_text('PRIVATE_CONFIGURATION_CANNOT_ENTER_CLIENT_BUILD: VITE_INSTITUTIONAL_SECRET')
    check(dist,log)


@pytest.mark.parametrize('fault',['missing_bundle','backend_secret','missing_rejection'])
def test_configuration_probe_never_passes_an_unexecuted_or_leaking_check(tmp_path,fault):
    dist=tmp_path/'dist';dist.mkdir();log=tmp_path/'rejected.log';log.write_text('PRIVATE_CONFIGURATION_CANNOT_ENTER_CLIENT_BUILD')
    if fault!='missing_bundle':(dist/'index.html').write_text('Synthetic public application')
    if fault=='backend_secret':(dist/'app.js').write_bytes(SENTINEL)
    if fault=='missing_rejection':log.write_text('Tool was not found')
    with pytest.raises(AssertionError):check(dist,log)
