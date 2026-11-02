"""Issue #49 Slice 122 CI exit status regression, not native runtime proof."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
NATIVE_SOURCE = ROOT / "native/windows/bootstrap/bootstrap_probe.cpp"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_script_explicitly_exits_success_after_complete_runtime_acceptance() -> None:
    source = _script()
    assert source.endswith(
        'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\nexit 0\n'
    )
    assert source.count("\nexit 0\n") == 1


def test_expected_refusal_codes_are_still_checked_before_success() -> None:
    source = _script()
    assert "$badCode -ne 2" in source
    assert "Assert-NoAuthorityOutput -Lines $bad" in source
    assert "$code -ne 1" in source
    assert "$code -ne 2" in source
    assert source.index("$badCode -ne 2") < source.index("exit 0")


def test_no_privilege_or_mutation_flag_is_weakened() -> None:
    source = _script()
    for item in (
        "$data.protected_write_performed -cne $false",
        "$data.administrator_authenticated -cne $false",
        "$data.service_identity_verified -cne $false",
        "$data.production_authority -cne $false",
        "$data.active_receipt_authority -cne $false",
        "$Lines[1] -ne $noAuthority",
        "'REFUSED_UNSUPPORTED_NATIVE_BOOTSTRAP_ARGUMENT'",
    ):
        assert item in source


@pytest.mark.parametrize(
    "forbidden",
    ("Start-Service", "New-Service", "Set-Acl", "WriteAllBytes", "--approve"),
    ids=("start", "register", "acl", "binary-write", "approval"),
)
def test_qualification_script_never_adds_privileged_actions(forbidden: str) -> None:
    assert forbidden not in _script()


def test_native_bootstrap_source_remains_read_only() -> None:
    source = NATIVE_SOURCE.read_text(encoding="utf-8")
    assert (
        "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
        in source
    )
    assert "return observed ? 2 : 1;" in source
    assert "WriteFile(" not in source
    assert "CreateServiceW(" not in source
