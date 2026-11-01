"""Issue #49 Slice 113: installer claims use wheel distribution, not repo aliases."""

from __future__ import annotations

import json

import pytest

from paper_data_suite import evergreen_windows_installer_intent as intent
from paper_data_suite.evergreen_installed_wheel_audit import APPROVED_DISTRIBUTIONS


def _raw(names: tuple[str, ...]) -> bytes:
    payload = {
        "schema": 1,
        "operation": "NEW_PROTECTED_WINDOWS_INSTALLATION",
        "service_name": "PaperDataSuiteService",
        "transaction_id": "a" * 32,
        "catalog_sha256": "b" * 64,
        "recovery_basis_sha256": "c" * 64,
        "artifacts": [
            {"distribution": name, "version": "0.6.6", "sha256": "d" * 64}
            for name in names
        ],
        "requested_phases": list(intent._PHASES),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def test_allowlist_exactly_matches_installed_wheel_inventory() -> None:
    """Identity drift across two existing Suite paths must fail qualification."""
    assert intent._DIST == tuple(sorted(APPROVED_DISTRIBUTIONS))
    assert intent._DIST == (
        "paper-data-suite",
        "pds-concord",
        "pds-core",
        "pds-meridian",
        "pds-portia",
        "pds-vitrine",
        "quillan",
        "scoreform",
    )


def test_all_real_wheel_distributions_are_accepted_as_untrusted_claims() -> None:
    parsed = intent.parse_untrusted_installer_intent(_raw(intent._DIST))
    assert tuple(entry.distribution for entry in parsed.artifacts) == intent._DIST
    assert parsed.service_name == "PaperDataSuiteService"


@pytest.mark.parametrize("name", ["pds-quillan", "pds-scoreform"])
def test_github_repository_alias_is_not_a_wheel_distribution(name: str) -> None:
    with pytest.raises(intent.InstallerIntentError, match="unapproved distribution"):
        intent.parse_untrusted_installer_intent(
            _raw(tuple(sorted(("paper-data-suite", "pds-core", name))))
        )


@pytest.mark.parametrize("name", ["quillan", "scoreform"])
def test_real_wheel_distribution_is_a_valid_optional_component(name: str) -> None:
    result = intent.parse_untrusted_installer_intent(
        _raw(tuple(sorted(("paper-data-suite", "pds-core", name))))
    )
    assert name in tuple(item.distribution for item in result.artifacts)


def test_intent_cli_remains_non_authorizing(capsys: pytest.CaptureFixture[str]) -> None:
    assert intent.main([]) == 2
    captured = capsys.readouterr().out
    assert '"privileged_installer_implemented": false' in captured
    assert '"production_authority": false' in captured
    assert '"active_receipt_authority": false' in captured
