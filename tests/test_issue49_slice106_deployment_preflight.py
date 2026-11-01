"""Slice 106: protected deployment preflight remains read-only and fail-closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_data_suite import evergreen_windows_deployment_preflight as target

_SYSTEM = "S-1-5-18"
_ADMINS = "S-1-5-32-544"
_USERS = "S-1-5-32-545"


def ace(sid: str, rights: int, *, inherit_only: bool = False) -> dict[str, object]:
    return {
        "sid": sid,
        "type": "Allow",
        "rights": rights,
        "inherited": True,
        "inherit_only": inherit_only,
    }


def acl(*rows: dict[str, object], owner: str = _ADMINS) -> dict[str, object]:
    return {"owner": owner, "rules": list(rows)}


STRICT = acl(ace(_SYSTEM, 2032127), ace(_ADMINS, 2032127), ace(_USERS, 131241))
# Standard ProgramData-style ability to create unrelated child directories
# must not imply the ability to replace an already protected PDS state child.
PARENT = acl(ace(_SYSTEM, 2032127), ace(_ADMINS, 2032127), ace(_USERS, 4))


def layout(tmp_path: Path) -> tuple[Path, Path]:
    app = tmp_path / "Program Files"
    data = tmp_path / "ProgramData"
    app.mkdir()
    data.mkdir()
    return app, data


def loader(path: Path) -> dict[str, object]:
    return PARENT if path.name == "ProgramData" else STRICT


def test_existing_base_not_a_completed_deployment(tmp_path: Path) -> None:
    app, data = layout(tmp_path)
    value = target.inspect_proposed_deployment(app, data, read_acl=loader)
    assert value.status == "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED"
    assert value.checked_paths == (str(app), str(data))
    assert value.missing_paths == (
        str(app / "Paper Data Suite"),
        str(data / "Paper Data Suite"),
        str(data / "Paper Data Suite" / "active-receipts"),
        str(data / "Paper Data Suite" / "service-state"),
    )
    assert not value.production_authority
    assert not value.active_receipt_authority
    assert list(app.iterdir()) == []
    assert list(data.iterdir()) == []


def test_provisioned_directories_still_non_authorizing(tmp_path: Path) -> None:
    app, data = layout(tmp_path)
    (app / "Paper Data Suite").mkdir()
    (data / "Paper Data Suite").mkdir()
    (data / "Paper Data Suite" / "active-receipts").mkdir()
    (data / "Paper Data Suite" / "service-state").mkdir()
    value = target.inspect_proposed_deployment(app, data, read_acl=loader)
    assert value.status == "PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY"
    assert len(value.checked_paths) == 6
    assert value.missing_paths == ()
    assert value.production_authority is False
    assert value.active_receipt_authority is False


def test_missing_os_base_refused_not_treated_as_provisionable(tmp_path: Path) -> None:
    app, data = layout(tmp_path)
    data.rmdir()
    with pytest.raises(target.DeploymentPreflightError, match="base is missing"):
        target.inspect_proposed_deployment(app, data, read_acl=loader)


def test_untrusted_write_to_state_target_refused(tmp_path: Path) -> None:
    app, data = layout(tmp_path)
    (data / "Paper Data Suite").mkdir()

    def state_writable(path: Path) -> dict[str, object]:
        if path == data / "Paper Data Suite":
            return acl(ace(_SYSTEM, 2032127), ace(_USERS, 2))
        return loader(path)

    with pytest.raises(target.DeploymentPreflightError, match="ACL custody refused"):
        target.inspect_proposed_deployment(app, data, read_acl=state_writable)


@pytest.mark.parametrize("rights", [0x40, 0x10000, 0x40000, 0x80000, -1])
def test_state_base_delete_or_acl_mutation_refused(rights: int) -> None:
    with pytest.raises(target.CustodyAuditError, match="write authority"):
        target.inspect_state_parent_acl(acl(ace(_SYSTEM, 2032127), ace(_USERS, rights)))


@pytest.mark.parametrize("rights", [2, 4, 6])
def test_parent_allows_unrelated_creation_but_not_child_mutation(rights: int) -> None:
    target.inspect_state_parent_acl(acl(ace(_SYSTEM, 2032127), ace(_USERS, rights)))


def test_parent_inherit_only_full_access_not_effective_here() -> None:
    target.inspect_state_parent_acl(
        acl(ace(_SYSTEM, 2032127), ace("S-1-3-0", -1, inherit_only=True))
    )


@pytest.mark.parametrize("rights", [True, 2**32, -(2**31) - 1, "4"])
def test_invalid_state_parent_mask_refused(rights: object) -> None:
    document = acl(ace(_SYSTEM, 2032127))
    document["rules"].append(ace(_USERS, rights))  # type: ignore[arg-type]
    with pytest.raises(target.CustodyAuditError, match="rights mask"):
        target.inspect_state_parent_acl(document)


def test_untrusted_state_parent_owner_refused() -> None:
    with pytest.raises(target.CustodyAuditError, match="owner"):
        target.inspect_state_parent_acl(acl(ace(_SYSTEM, 2032127), owner=_USERS))


def test_parent_malformed_unknown_fields_refused() -> None:
    with pytest.raises(target.CustodyAuditError, match="invalid state-parent"):
        target.inspect_state_parent_acl({"owner": _ADMINS, "rules": [], "extra": 3})


def test_symlink_refused_without_following(tmp_path: Path) -> None:
    app, data = layout(tmp_path)
    try:
        (app / "Paper Data Suite").symlink_to(data, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation privilege unavailable")
        raise
    with pytest.raises(target.DeploymentPreflightError, match="unsafe"):
        target.inspect_proposed_deployment(app, data, read_acl=loader)


def test_symlink_metadata_refused_without_symlink_privilege(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, data = layout(tmp_path)
    link = app / "Paper Data Suite"
    original_lstat = Path.lstat

    def fake_lstat(path: Path) -> object:
        if path == link:
            return type("LinkStat", (), {"st_mode": 0o120777})()
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(target.DeploymentPreflightError, match="unsafe"):
        target.inspect_proposed_deployment(app, data, read_acl=loader)


def test_file_instead_of_directory_refused(tmp_path: Path) -> None:
    app, data = layout(tmp_path)
    (app / "Paper Data Suite").write_text("not a directory")
    with pytest.raises(target.DeploymentPreflightError, match="directory"):
        target.inspect_proposed_deployment(app, data, read_acl=loader)


def test_acl_query_failure_refused(tmp_path: Path) -> None:
    app, data = layout(tmp_path)

    def unavailable(path: Path) -> object:
        raise OSError("failed to read ACL")

    with pytest.raises(target.DeploymentPreflightError, match="ACL custody refused"):
        target.inspect_proposed_deployment(app, data, read_acl=unavailable)


def test_root_overlap_refused(tmp_path: Path) -> None:
    app, _data = layout(tmp_path)
    with pytest.raises(target.DeploymentPreflightError, match="overlap"):
        target.inspect_proposed_deployment(app, app, read_acl=loader)


def test_non_windows_public_entry_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target.os, "name", "posix")
    with pytest.raises(target.DeploymentPreflightError, match="Windows is required"):
        target.audit_windows_deployment_preflight()


def test_cli_refusal_when_acl_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unavailable() -> target.DeploymentPreflight:
        raise target.DeploymentPreflightError("fake ACL failure")

    monkeypatch.setattr(target, "audit_windows_deployment_preflight", unavailable)
    assert target.main([]) == 1
    assert "NO_PRODUCTION_INSTALL_OR_RECEIPT_AUTHORITY" in capsys.readouterr().err


def test_cli_provisioning_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        target,
        "audit_windows_deployment_preflight",
        lambda: target.DeploymentPreflight("PROVISIONING", (), ("not-created",)),
    )
    assert target.main([]) == 2
    assert "PROVISIONING_REQUIRED_NO_FILESYSTEM_WRITES" in capsys.readouterr().out
