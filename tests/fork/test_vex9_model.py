# SPDX-License-Identifier: AGPL-3.0-only
"""VEX-9 offline authoring checks. Live voice quality is separate (tools/check_vex9.py --live)."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('vex9_check', ROOT / 'tools/check_vex9.py')
vex9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vex9)


def test_shipped_modelfiles_follow_parameter_and_identity_conventions():
    checks = vex9.offline_checks(include_authoring=False)
    assert all(checks.values()), {k: v for k, v in checks.items() if not v}


def test_authoring_drafts_follow_standard_template():
    present = [path.is_file() for path in vex9.AUTHORING_FILES]
    if not any(present):
        pytest.skip('authoring drafts are not part of the public export')
    assert all(present), 'authoring drafts must be all present or all absent'
    checks = vex9.offline_checks(include_authoring=True)
    assert all(checks.values()), {k: v for k, v in checks.items() if not v}
