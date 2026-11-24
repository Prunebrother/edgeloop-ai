# SPDX-License-Identifier: AGPL-3.0-only
import subprocess
import sys
from tools.campaign_live_check import ROOT, resolve_models


def test_real_manifest_models_and_override():
    models=resolve_models()
    assert models['vex9']=='vex9-narrative-f29-v016:latest'
    assert models['mira']=='mira-narrative-f29-v017:latest'
    assert resolve_models(overrides=['mira=custom:latest'])['mira']=='custom:latest'


def test_unknown_campaign_and_mission_are_skipped(tmp_path):
    for args in [['--campaign','missing'],['missing_mission']]:
        result=subprocess.run([sys.executable,str(ROOT/'tools/campaign_live_check.py'),
                               '--out',str(tmp_path),*args],capture_output=True,text=True)
        assert result.returncode==0, result.stderr
        assert 'SKIP' in result.stdout
