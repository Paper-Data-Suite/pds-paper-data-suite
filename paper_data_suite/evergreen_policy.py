"""Pure issue #49 launch and integration eligibility policy (not yet wired in).

All inputs are *observations* from future authenticated metadata and installed
environment adapters. This module does not authenticate bytes, probe a host,
read a workspace, or grant launch permissions based on its own unchecked input.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReleaseTrust(str, Enum):
    """Locally established, authenticated release-authorization state."""

    TRUSTED = "trusted"
    UNKNOWN = "unknown"
    REVOKED = "revoked"


class LaunchStatus(str, Enum):
    """Independent application launch eligibility, not suite qualification."""

    AVAILABLE = "available"
    NOT_INSTALLED = "not_installed"
    BLOCKED = "blocked"


class LaunchReason(str, Enum):
    """Deterministic launch decision codes; no raw diagnostic payloads."""

    ELIGIBLE = "launch.eligible"
    NOT_INSTALLED = "launch.not_installed"
    RELEASE_UNKNOWN = "launch.release_unknown"
    RELEASE_REVOKED = "launch.release_revoked"
    ARTIFACT_MISMATCH = "launch.artifact_mismatch"
    UPDATE_INCOMPLETE = "launch.update_incomplete"
    PYTHON_INCOMPATIBLE = "launch.python_incompatible"
    DEPENDENCIES_INCOMPATIBLE = "launch.dependencies_incompatible"
    ENTRY_POINT_INVALID = "launch.entry_point_invalid"
    LAUNCHER_UNSAFE = "launch.launcher_unsafe"


@dataclass(frozen=True, slots=True)
class LaunchPreflight:
    """Trusted adapter results, not unverified module self-assertions.

    ``release_trust`` MUST be supplied by an independently authenticated catalog
    and verified installation receipt. The other facts MUST be established by
    corresponding trusted local probes before constructing this object.
    """

    installed: bool
    release_trust: ReleaseTrust
    artifact_matches_receipt: bool
    update_transaction_healthy: bool
    python_compatible: bool
    dependencies_compatible: bool
    entry_point_owned: bool
    launcher_confined: bool

    def __post_init__(self) -> None:
        if not isinstance(self.installed, bool):
            raise TypeError("installed must be bool")
        if not isinstance(self.release_trust, ReleaseTrust):
            raise TypeError("release_trust must be ReleaseTrust")
        for name in (
            "artifact_matches_receipt",
            "update_transaction_healthy",
            "python_compatible",
            "dependencies_compatible",
            "entry_point_owned",
            "launcher_confined",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")


@dataclass(frozen=True, slots=True)
class LaunchDecision:
    """One isolated launcher decision, carrying no integration certification."""

    status: LaunchStatus
    reason: LaunchReason

    @property
    def can_launch(self) -> bool:
        """Only an independently eligible installed module may launch."""
        return self.status is LaunchStatus.AVAILABLE


def assess_launch(preflight: LaunchPreflight) -> LaunchDecision:
    """Decide launchability without historical Suite-version comparisons.

    Input validation/authentication belongs to future adapters. An offline
    freshness warning is intentionally not a launch disqualifier for an already
    authenticated installed release; signed authorization/revocation policy is
    handled before supplying ``release_trust``.
    """
    if not isinstance(preflight, LaunchPreflight):
        raise TypeError("preflight must be LaunchPreflight")
    if not preflight.installed:
        return LaunchDecision(LaunchStatus.NOT_INSTALLED, LaunchReason.NOT_INSTALLED)
    if preflight.release_trust is ReleaseTrust.REVOKED:
        return LaunchDecision(LaunchStatus.BLOCKED, LaunchReason.RELEASE_REVOKED)
    if preflight.release_trust is not ReleaseTrust.TRUSTED:
        return LaunchDecision(LaunchStatus.BLOCKED, LaunchReason.RELEASE_UNKNOWN)
    for condition, reason in (
        (preflight.artifact_matches_receipt, LaunchReason.ARTIFACT_MISMATCH),
        (preflight.update_transaction_healthy, LaunchReason.UPDATE_INCOMPLETE),
        (preflight.python_compatible, LaunchReason.PYTHON_INCOMPATIBLE),
        (preflight.dependencies_compatible, LaunchReason.DEPENDENCIES_INCOMPATIBLE),
        (preflight.entry_point_owned, LaunchReason.ENTRY_POINT_INVALID),
        (preflight.launcher_confined, LaunchReason.LAUNCHER_UNSAFE),
    ):
        if not condition:
            return LaunchDecision(LaunchStatus.BLOCKED, reason)
    return LaunchDecision(LaunchStatus.AVAILABLE, LaunchReason.ELIGIBLE)


class IntegrationEvidence(str, Enum):
    """Exact evidence and public-contract evidence are distinct authorities."""

    EXACT_ATTESTED = "exact_attested"
    CONTRACT_SUPPORTED = "contract_supported"
    UNQUALIFIED = "unqualified"
    UNAVAILABLE = "unavailable"


class IntegrationStatus(str, Enum):
    """Whether one named cross-module capability may be used."""

    AVAILABLE_EXACT = "available_exact"
    AVAILABLE_CONTRACT = "available_contract"
    UNQUALIFIED = "unqualified"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class IntegrationDecision:
    """Per-feature decision, independent of the primary launcher state."""

    status: IntegrationStatus

    @property
    def permitted(self) -> bool:
        return self.status in (
            IntegrationStatus.AVAILABLE_EXACT,
            IntegrationStatus.AVAILABLE_CONTRACT,
        )


def assess_integration(
    launch: LaunchDecision,
    evidence: IntegrationEvidence,
    *,
    requires_exact_attestation: bool,
) -> IntegrationDecision:
    """Restrict one feature without changing application launch eligibility.

    A contract-compatible feature can use supported public contracts when its
    caller has explicitly declared that exact-configuration testing is *not*
    required. Features that require exact attestation must never infer it from
    compatible ranges or nearby package versions.
    """
    if not isinstance(launch, LaunchDecision):
        raise TypeError("launch must be LaunchDecision")
    if not isinstance(evidence, IntegrationEvidence):
        raise TypeError("evidence must be IntegrationEvidence")
    if not isinstance(requires_exact_attestation, bool):
        raise TypeError("requires_exact_attestation must be bool")
    if not launch.can_launch or evidence is IntegrationEvidence.UNAVAILABLE:
        return IntegrationDecision(IntegrationStatus.UNAVAILABLE)
    if evidence is IntegrationEvidence.EXACT_ATTESTED:
        return IntegrationDecision(IntegrationStatus.AVAILABLE_EXACT)
    if evidence is IntegrationEvidence.CONTRACT_SUPPORTED:
        if requires_exact_attestation:
            return IntegrationDecision(IntegrationStatus.UNQUALIFIED)
        return IntegrationDecision(IntegrationStatus.AVAILABLE_CONTRACT)
    return IntegrationDecision(IntegrationStatus.UNQUALIFIED)
