"""Slice 137 repair 1: Windows LocalUser account-name length constraint."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "native/windows/bootstrap/qualify_sandbox_ordinary_user_ci.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-sandbox-ordinary-user-denial.yml"
CHILD = ROOT / "native/windows/bootstrap/sandbox_ordinary_user_probe.ps1"


def test_windows_local_account_name_within_twenty_character_limit() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"\$name = '([a-z_]+)' \+ \[guid\]::NewGuid\(\)"
        r"\.ToString\('N'\)\.Substring\(0, (\d+)\)",
        text,
    )
    assert match is not None
    prefix, suffix = match.group(1), int(match.group(2))
    assert len(prefix) + suffix <= 20
    assert suffix >= 12  # Retain substantial random collision resistance.
    assert prefix == "pdsacl_"
    assert "if ($name.Length -gt 20)" in text
    assert "New-LocalUser -Name $name" in text


def test_remains_hosted_ci_only_and_unprivileged() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "RUNNER_ENVIRONMENT -cne 'github-hosted'" in text
    assert "GITHUB_ACTIONS" in text
    assert "RUNNER_OS" in text
    assert "New-LocalUser -Name $name" in text
    assert "Get-LocalGroupMember -SID" in text
    assert "-Credential $credential" in text
    assert "ordinary-should-never-write.txt" in text
    assert "protected_directory_denials -ne 4" in text
    assert "authorized_to_install -cne $false" in text
    assert "Remove-LocalUser" not in text
    assert WORKFLOW.is_file()
    assert CHILD.is_file()


def test_existing_positive_and_negative_controls_still_required() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "CI_ORDINARY_CONTROL_REACHABLE" in text
    assert "ORDINARY_WRITE_SUCCEEDED" in text
    assert "ordinary-proof.json" in text
    assert "protected_directory_denials -ne 4" in text
    assert (
        "SLICE137_EPHEMERAL_STANDARD_USER_POSITIVE_AND_FOUR_NEGATIVE_ACL_CHECKS_PASSED"
        in text
    )
    assert "NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY" in text
