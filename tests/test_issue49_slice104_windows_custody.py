"""Issue #49 Slice 104: fail-closed Windows protected path ACL checks."""

from __future__ import annotations

from pathlib import Path

import pytest

import paper_data_suite.evergreen_windows_custody as custody

SYSTEM = "S-1-5-18"
ADMINS = "S-1-5-32-544"
USERS = "S-1-5-32-545"


def row(
    sid: str,
    rights: int,
    inherited: bool = False,
    kind: str = "Allow",
    inherit_only: bool = False,
) -> dict[str, object]:
    return {
        "sid": sid,
        "type": kind,
        "rights": rights,
        "inherited": inherited,
        "inherit_only": inherit_only,
    }


def doc(*rules: dict[str, object], owner: str = ADMINS) -> dict[str, object]:
    return {"owner": owner, "rules": list(rules)}


def test_accepted_system_admin_write_and_user_read() -> None:
    custody.inspect_acl_document(
        doc(row(SYSTEM, 2032127), row(ADMINS, 2032127), row(USERS, 131241, True))
    )


@pytest.mark.parametrize("rights", [2, 4, 16, 64, 256, 65536, 262144, 524288, 2032127])
def test_user_write_refused_even_when_inherited(rights: int) -> None:
    with pytest.raises(custody.CustodyAuditError, match="write authority"):
        custody.inspect_acl_document(
            doc(row(SYSTEM, 2032127), row(USERS, rights, True))
        )


def test_denial_does_not_cancel_untrusted_allow() -> None:
    with pytest.raises(custody.CustodyAuditError, match="write authority"):
        custody.inspect_acl_document(
            doc(row(USERS, 2032127, kind="Deny"), row(USERS, 2))
        )


def test_inherit_only_placeholder_does_not_grant_write_to_current_directory() -> None:
    custody.inspect_acl_document(
        doc(row(SYSTEM, 2032127), row("S-1-3-0", 2032127, inherit_only=True))
    )


@pytest.mark.parametrize(
    "owner", [USERS, "S-1-5-11", "BUILTIN\\Administrators", "S-1-5-80-12345"]
)
def test_untrusted_owner_refused(owner: str) -> None:
    with pytest.raises(custody.CustodyAuditError, match="owner"):
        custody.inspect_acl_document(doc(row(SYSTEM, 2032127), owner=owner))


def test_trustedinstaller_is_only_trusted_service_owner() -> None:
    custody.inspect_acl_document(
        doc(row(SYSTEM, 2032127), owner=custody._TRUSTED_INSTALLER)
    )
    with pytest.raises(custody.CustodyAuditError):
        custody.inspect_acl_document(doc(row("S-1-5-80-12345", 2)))


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"owner": ADMINS, "rules": []},
        {
            "owner": ADMINS,
            "rules": [
                {
                    "sid": USERS,
                    "type": "Allow",
                    "rights": "2",
                    "inherited": False,
                }
            ],
        },
    ],
)
def test_malformed_access_controls_refused(invalid: object) -> None:
    with pytest.raises(custody.CustodyAuditError):
        custody.inspect_acl_document(invalid)


def test_linux_refuses_without_windows_acl_api() -> None:
    if custody.os.name == "nt":
        pytest.skip("non-Windows refusal only")
    with pytest.raises(custody.CustodyAuditError, match="Windows is required"):
        custody.audit_windows_install_path(Path("/tmp"))


def test_observation_never_authorizes_launch() -> None:
    value = custody.CustodyAuditObservation(("C:\\Program Files",))
    assert not value.production_authority
    assert value.status == "WINDOWS_PROTECTED_PATH_ACL_OBSERVED_ONLY"


def test_cli_fail_closed(capsys: pytest.CaptureFixture[str]) -> None:
    assert custody.main(["--path", "/no/such/path"]) == 1
    assert "NO_PRODUCTION_INSTALL_CUSTODY_ESTABLISHED" in capsys.readouterr().err
