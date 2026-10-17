"""Issue #49 Slice 1: non-wired evergreen eligibility policy invariants."""

from __future__ import annotations

from dataclasses import replace

import pytest

from paper_data_suite.evergreen_policy import (
    IntegrationEvidence,
    IntegrationStatus,
    LaunchPreflight,
    LaunchReason,
    LaunchStatus,
    ReleaseTrust,
    assess_integration,
    assess_launch,
)


def _ready() -> LaunchPreflight:
    return LaunchPreflight(
        installed=True,
        release_trust=ReleaseTrust.TRUSTED,
        artifact_matches_receipt=True,
        update_transaction_healthy=True,
        python_compatible=True,
        dependencies_compatible=True,
        entry_point_owned=True,
        launcher_confined=True,
    )


def test_verified_future_release_is_launchable_without_suite_version_input() -> None:
    decision = assess_launch(_ready())
    assert decision.status is LaunchStatus.AVAILABLE
    assert decision.reason is LaunchReason.ELIGIBLE
    assert decision.can_launch
    assert not hasattr(_ready(), "historical_suite_version")
    assert not hasattr(_ready(), "installed_module_version")


def test_absent_module_is_not_installed_without_pretending_failure() -> None:
    decision = assess_launch(replace(_ready(), installed=False))
    assert decision.status is LaunchStatus.NOT_INSTALLED
    assert decision.reason is LaunchReason.NOT_INSTALLED
    assert not decision.can_launch


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"release_trust": ReleaseTrust.UNKNOWN}, LaunchReason.RELEASE_UNKNOWN),
        ({"release_trust": ReleaseTrust.REVOKED}, LaunchReason.RELEASE_REVOKED),
        ({"artifact_matches_receipt": False}, LaunchReason.ARTIFACT_MISMATCH),
        ({"update_transaction_healthy": False}, LaunchReason.UPDATE_INCOMPLETE),
        ({"python_compatible": False}, LaunchReason.PYTHON_INCOMPATIBLE),
        ({"dependencies_compatible": False}, LaunchReason.DEPENDENCIES_INCOMPATIBLE),
        ({"entry_point_owned": False}, LaunchReason.ENTRY_POINT_INVALID),
        ({"launcher_confined": False}, LaunchReason.LAUNCHER_UNSAFE),
    ],
)
def test_untrusted_or_unsafe_release_fails_closed(
    changes: dict[str, object], expected: LaunchReason
) -> None:
    decision = assess_launch(replace(_ready(), **changes))
    assert decision.status is LaunchStatus.BLOCKED
    assert decision.reason is expected
    assert not decision.can_launch


def test_missing_integrations_cannot_block_independent_launch() -> None:
    launch = assess_launch(_ready())
    integration = assess_integration(
        launch, IntegrationEvidence.UNQUALIFIED, requires_exact_attestation=True
    )
    assert launch.can_launch
    assert integration.status is IntegrationStatus.UNQUALIFIED
    assert not integration.permitted


@pytest.mark.parametrize(
    ("evidence", "requires_exact", "expected"),
    [
        (IntegrationEvidence.EXACT_ATTESTED, True, IntegrationStatus.AVAILABLE_EXACT),
        (IntegrationEvidence.EXACT_ATTESTED, False, IntegrationStatus.AVAILABLE_EXACT),
        (
            IntegrationEvidence.CONTRACT_SUPPORTED,
            False,
            IntegrationStatus.AVAILABLE_CONTRACT,
        ),
        (IntegrationEvidence.CONTRACT_SUPPORTED, True, IntegrationStatus.UNQUALIFIED),
        (IntegrationEvidence.UNQUALIFIED, False, IntegrationStatus.UNQUALIFIED),
        (IntegrationEvidence.UNQUALIFIED, True, IntegrationStatus.UNQUALIFIED),
        (IntegrationEvidence.UNAVAILABLE, False, IntegrationStatus.UNAVAILABLE),
        (IntegrationEvidence.UNAVAILABLE, True, IntegrationStatus.UNAVAILABLE),
    ],
)
def test_capability_evidence_is_feature_scoped(
    evidence: IntegrationEvidence,
    requires_exact: bool,
    expected: IntegrationStatus,
) -> None:
    decision = assess_integration(
        assess_launch(_ready()),
        evidence,
        requires_exact_attestation=requires_exact,
    )
    assert decision.status is expected
    assert decision.permitted == (
        expected
        in (
            IntegrationStatus.AVAILABLE_EXACT,
            IntegrationStatus.AVAILABLE_CONTRACT,
        )
    )


def test_blocked_application_cannot_claim_integration_available() -> None:
    launch = assess_launch(replace(_ready(), release_trust=ReleaseTrust.UNKNOWN))
    decision = assess_integration(
        launch,
        IntegrationEvidence.EXACT_ATTESTED,
        requires_exact_attestation=False,
    )
    assert decision.status is IntegrationStatus.UNAVAILABLE
    assert not decision.permitted


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("installed", 1),
        ("release_trust", "trusted"),
        ("launcher_confined", "yes"),
        ("dependencies_compatible", None),
    ],
)
def test_untyped_probe_values_cannot_be_implicitly_truthy(
    field: str, value: object
) -> None:
    with pytest.raises(TypeError):
        replace(_ready(), **{field: value})


def test_integration_inputs_fail_closed_on_unexpected_types() -> None:
    with pytest.raises(TypeError):
        assess_integration(
            assess_launch(_ready()),
            "exact_attested",  # type: ignore[arg-type]
            requires_exact_attestation=False,
        )
    with pytest.raises(TypeError):
        assess_integration(
            assess_launch(_ready()),
            IntegrationEvidence.CONTRACT_SUPPORTED,
            requires_exact_attestation=1,  # type: ignore[arg-type]
        )
