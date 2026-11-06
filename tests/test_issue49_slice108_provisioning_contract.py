"""Slice 108: provisioning is only a read-only administrator handoff."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_data_suite import evergreen_windows_provisioning_contract as target
from paper_data_suite.evergreen_windows_deployment_preflight import (
    DeploymentPreflightError,
)

_SYSTEM = "S-1-5-18"
_ADMINS = "S-1-5-32-544"
_USERS = "S-1-5-32-545"


def _ace(sid: str, rights: int) -> dict[str, object]:
    return {
        "sid": sid,
        "type": "Allow",
        "rights": rights,
        "inherited": False,
        "inherit_only": False,
    }


def _strict() -> dict[str, object]:
    return {
        "owner": _ADMINS,
        "rules": [_ace(_SYSTEM, 2032127), _ace(_ADMINS, 2032127), _ace(_USERS, 131241)],
    }


def _parent() -> dict[str, object]:
    return {
        "owner": _ADMINS,
        "rules": [_ace(_SYSTEM, 2032127), _ace(_ADMINS, 2032127), _ace(_USERS, 0x116)],
    }


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    app = tmp_path / "Program Files"
    data = tmp_path / "ProgramData"
    app.mkdir()
    data.mkdir()
    return app, data


def _reader(path: Path) -> object:
    return _parent() if path.name == "ProgramData" else _strict()


def test_missing_four_paths_only_produces_non_authorizing_handoff(
    tmp_path: Path,
) -> None:
    app, data = _layout(tmp_path)
    review = target.review_windows_provisioning(app, data, read_acl=_reader)
    assert review.status == "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED"
    assert review.checked_paths == (str(app), str(data))
    assert review.missing_paths == tuple(
        requirement.directory for requirement in review.required_directories
    )
    assert tuple(
        requirement.purpose for requirement in review.required_directories
    ) == (
        "APPLICATION_BINARIES",
        "PROTECTED_STATE_ROOT",
        "ACTIVE_RECEIPTS",
        "SERVICE_TRANSACTION_STATE",
    )
    assert all(
        not requirement.ordinary_user_write_allowed
        for requirement in review.required_directories
    )
    assert all(
        not requirement.authorized_for_creation
        for requirement in review.required_directories
    )
    assert not review.production_authority
    assert not review.active_receipt_authority
    assert review.service_identity == "INDEPENDENT_SERVICE_IDENTITY_NOT_ESTABLISHED"
    assert review.executable_integrity == "NOT_VERIFIED"
    assert review.protected_receipt_head == "NOT_VERIFIED"
    assert list(app.iterdir()) == []
    assert list(data.iterdir()) == []


def test_existing_acl_observation_is_still_non_authorizing(tmp_path: Path) -> None:
    app, data = _layout(tmp_path)
    (app / "Paper Data Suite").mkdir()
    (data / "Paper Data Suite").mkdir()
    for child in ("active-receipts", "service-state"):
        (data / "Paper Data Suite" / child).mkdir()
    result = target.review_windows_provisioning(app, data, read_acl=_reader)
    assert result.status == "PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY"
    assert result.missing_paths == ()
    assert not result.production_authority
    assert not result.active_receipt_authority
    assert result.authority == target._NO_AUTHORITY


def test_untrusted_state_write_refuses(tmp_path: Path) -> None:
    app, data = _layout(tmp_path)
    state = data / "Paper Data Suite"
    state.mkdir()

    def unsafe(path: Path) -> object:
        if path == state:
            return {
                "owner": _ADMINS,
                "rules": [_ace(_SYSTEM, 2032127), _ace(_USERS, 0x2)],
            }
        return _reader(path)

    with pytest.raises(DeploymentPreflightError, match="ACL custody"):
        target.review_windows_provisioning(app, data, read_acl=unsafe)


def test_parent_acl_compatibility_is_not_applied_to_child(tmp_path: Path) -> None:
    app, data = _layout(tmp_path)
    (data / "Paper Data Suite").mkdir()

    def unsafe(path: Path) -> object:
        if path == data / "Paper Data Suite":
            return _parent()
        return _reader(path)

    with pytest.raises(DeploymentPreflightError, match="ACL custody"):
        target.review_windows_provisioning(app, data, read_acl=unsafe)


@pytest.mark.parametrize("bad", [None, 5, "not a callable"])
def test_bad_acl_reader_refused(tmp_path: Path, bad: object) -> None:
    app, data = _layout(tmp_path)
    with pytest.raises(DeploymentPreflightError, match="reader unavailable"):
        target.review_windows_provisioning(app, data, read_acl=bad)


def test_missing_base_refuses_not_provisioning(tmp_path: Path) -> None:
    app, data = _layout(tmp_path)
    data.rmdir()
    with pytest.raises(DeploymentPreflightError, match="base is missing"):
        target.review_windows_provisioning(app, data, read_acl=_reader)


def test_cli_missing_returns_two_without_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    app, data = _layout(tmp_path)
    expected = target.review_windows_provisioning(app, data, read_acl=_reader)
    monkeypatch.setattr(target, "inspect_windows_provisioning", lambda: expected)
    assert target.main([]) == 2
    output = capsys.readouterr().out
    decoded = json.loads(output.split("\nNO_INSTALL_SERVICE_RECEIPT_")[0])
    assert decoded["production_authority"] is False
    assert decoded["active_receipt_authority"] is False
    assert len(decoded["required_directories"]) == 4
    assert target._NO_AUTHORITY in output


def test_cli_observed_returns_zero_not_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    app, data = _layout(tmp_path)
    (app / "Paper Data Suite").mkdir()
    state = data / "Paper Data Suite"
    state.mkdir()
    (state / "active-receipts").mkdir()
    (state / "service-state").mkdir()
    expected = target.review_windows_provisioning(app, data, read_acl=_reader)
    monkeypatch.setattr(target, "inspect_windows_provisioning", lambda: expected)
    assert target.main([]) == 0
    assert target._NO_AUTHORITY in capsys.readouterr().out


def test_cli_refusal_returns_one_without_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def denied() -> target.ProvisioningReview:
        raise DeploymentPreflightError("unsafe ACL")

    monkeypatch.setattr(target, "inspect_windows_provisioning", denied)
    assert target.main([]) == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert target._NO_AUTHORITY in result.err


def test_non_windows_public_review_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    # Target the module-local OS gate only; avoid patching global os.name.
    class NotWindows:
        name = "posix"

    monkeypatch.setattr(target, "os", NotWindows())
    with pytest.raises(DeploymentPreflightError, match="Windows is required"):
        target.inspect_windows_provisioning()
