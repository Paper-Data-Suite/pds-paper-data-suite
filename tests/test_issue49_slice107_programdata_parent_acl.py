"""Slice 107: normal ProgramData parent ACLs cannot certify PDS child custody."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_data_suite import evergreen_windows_deployment_preflight as deployment
from paper_data_suite.evergreen_windows_custody import CustodyAuditError

_SYSTEM = "S-1-5-18"
_ADMINS = "S-1-5-32-544"
_USERS = "S-1-5-32-545"


def _ace(sid: str, rights: int, *, inherit_only: bool = False) -> dict[str, object]:
    return {
        "sid": sid,
        "type": "Allow",
        "rights": rights,
        "inherited": False,
        "inherit_only": inherit_only,
    }


def _acl(*rows: dict[str, object]) -> dict[str, object]:
    return {
        "owner": _ADMINS,
        "rules": [_ace(_SYSTEM, 2032127), _ace(_ADMINS, 2032127), *rows],
    }


# WD, AD, WEA, WA: create files, create subdirectories, write extended
# attributes, write attributes, as commonly permitted on ProgramData.
_PROGRAMDATA_CREATION_AND_ATTRIBUTES = 0x2 | 0x4 | 0x10 | 0x100


@pytest.mark.parametrize(
    "rights",
    [0x2, 0x4, 0x10, 0x100, 0x116, _PROGRAMDATA_CREATION_AND_ATTRIBUTES],
)
def test_programdata_parent_allows_creation_and_parent_attributes(rights: int) -> None:
    deployment.inspect_state_parent_acl(_acl(_ace(_USERS, rights)))


@pytest.mark.parametrize(
    "rights",
    [0x40, 0x10000, 0x40000, 0x80000, 0x10000000, 0x40000000, -1],
)
def test_parent_still_refuses_delete_and_security_descriptor_rights(
    rights: int,
) -> None:
    with pytest.raises(CustodyAuditError, match="write authority"):
        deployment.inspect_state_parent_acl(_acl(_ace(_USERS, rights)))


@pytest.mark.parametrize("rights", [0x2, 0x4, 0x10, 0x100, 0x116])
def test_protected_child_retains_strict_refusal(rights: int) -> None:
    from paper_data_suite.evergreen_windows_custody import inspect_acl_document

    with pytest.raises(CustodyAuditError, match="write authority"):
        inspect_acl_document(_acl(_ace(_USERS, rights)))


def test_existing_protected_state_must_pass_its_own_acl(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    program_data = tmp_path / "ProgramData"
    program_files.mkdir()
    program_data.mkdir()
    state = program_data / "Paper Data Suite"
    state.mkdir()

    def acl_for(path: Path) -> object:
        if path == program_data:
            return _acl(_ace(_USERS, 0x116))
        if path == state:
            return _acl(_ace(_USERS, 0x100))
        return _acl(_ace(_USERS, 131241))

    with pytest.raises(deployment.DeploymentPreflightError, match="ACL custody"):
        deployment.inspect_proposed_deployment(
            program_files, program_data, read_acl=acl_for
        )


def test_missing_children_provisioning_required_not_trust(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    program_data = tmp_path / "ProgramData"
    program_files.mkdir()
    program_data.mkdir()

    def acl_for(path: Path) -> object:
        if path == program_data:
            return _acl(_ace(_USERS, 0x116))
        return _acl(_ace(_USERS, 131241))

    result = deployment.inspect_proposed_deployment(
        program_files, program_data, read_acl=acl_for
    )
    assert result.status == "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED"
    assert len(result.missing_paths) == 4
    assert not result.production_authority
    assert not result.active_receipt_authority
    assert list(program_files.iterdir()) == []
    assert list(program_data.iterdir()) == []


def test_inherit_only_generic_all_does_not_apply_to_parent() -> None:
    deployment.inspect_state_parent_acl(
        _acl(_ace(_USERS, 0x116), _ace("S-1-3-0", -1, inherit_only=True))
    )
