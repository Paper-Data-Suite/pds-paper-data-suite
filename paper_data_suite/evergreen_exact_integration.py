"""Issue #49: signed, exact-scope feature evidence for an audited candidate.

A valid integration signature does not establish actual provider readiness,
software activation, installed-state continuity, or permission to execute.
The candidate is fully reverified from raw input rather than trusting a
caller-created observation or a user-editable journal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Final

from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    RevisionCheckpoint,
    TrustedKeyring,
    verify_integration_document,
    verify_registry_document,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    parse_unverified_prepared_record,
)
from paper_data_suite.evergreen_journal_pip_preflight import (
    JournalPipPreflightError,
    inspect_journal_bound_publisher_pip_candidate,
)

_FEATURE: Final = re.compile(r"[a-z][a-z0-9_.-]{2,95}\Z")
_COMPONENT: Final = re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
_MAX_ATTESTATION: Final = 128 * 1024


class ExactIntegrationError(ValueError):
    """Untrustworthy candidate evidence or unsupported attestation authority."""


class ExactEvidenceStatus(str, Enum):
    """Per-feature evidence; NOT a software launch or integration authorization."""

    EXACT_ATTESTED = "exact_attested"
    UNQUALIFIED = "unqualified"
    ATTESTED_FAILURE = "attested_failure"


@dataclass(frozen=True, slots=True)
class ObservedExactIntegration:
    """Verified exact feature scope for one currently audited staged candidate."""

    transaction_id: str
    feature_id: str
    status: ExactEvidenceStatus
    participants: tuple[str, ...]
    pip_inventory_sha256: str
    attestation_sha256: str | None
    evidence_sha256: str | None
    signed_revision: int | None
    signed_result: str | None


def _scope(feature_id: str, participants: tuple[str, ...]) -> None:
    if (
        type(feature_id) is not str
        or not _FEATURE.fullmatch(feature_id)
        or type(participants) is not tuple
        or not 1 <= len(participants) <= 32
        or any(
            type(part) is not str or not _COMPONENT.fullmatch(part)
            for part in participants
        )
        or len(set(participants)) != len(participants)
    ):
        raise ExactIntegrationError("invalid named capability or participant scope")


def inspect_journal_exact_integration(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    expected_revision: int,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    module_envelopes: dict[str, bytes],
    integration_envelope: bytes | None,
    feature_id: str,
    required_component_ids: tuple[str, ...],
    trust: TrustedKeyring,
    now: datetime,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    native_checkpoint: RevisionCheckpoint | None = None,
    integration_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> ObservedExactIntegration:
    """Compare a signed named feature with exact publisher-approved wheel bytes.

    Missing evidence and a different signed scope are unqualified, not a
    global module failure. Invalid signatures or untrusted candidate software
    fail closed. Signed `failed` is a negative finding for *this feature only*.
    The required participants come from the trusted calling feature contract;
    caller-provided scopes do not grant authority absent a signed exact match.
    """
    _scope(feature_id, required_component_ids)
    if integration_envelope is not None and (
        type(integration_envelope) is not bytes
        or not 1 <= len(integration_envelope) <= _MAX_ATTESTATION
    ):
        raise ExactIntegrationError("invalid integration attestation bytes")
    try:
        registry = verify_registry_document(
            registry_envelope,
            trust=trust,
            now=now,
            checkpoint=registry_checkpoint,
        )
        prepared = parse_unverified_prepared_record(prepared_record)
        integration = (
            verify_integration_document(
                integration_envelope,
                registry=registry,
                trust=trust,
                now=now,
                checkpoint=integration_checkpoint,
            )
            if integration_envelope is not None
            else None
        )
        candidate = inspect_journal_bound_publisher_pip_candidate(
            software_root,
            classroom_workspace=classroom_workspace,
            transaction_id=transaction_id,
            expected_revision=expected_revision,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            evidence_envelope=evidence_envelope,
            module_envelopes=module_envelopes,
            trust=trust,
            now=now,
            registry_checkpoint=registry_checkpoint,
            lock_checkpoint=lock_checkpoint,
            native_checkpoint=native_checkpoint,
            layout=layout,
        )
    except (
        CatalogVerificationError,
        PreparedRecordError,
        JournalPipPreflightError,
        TypeError,
        ValueError,
        OSError,
    ) as error:
        raise ExactIntegrationError(
            "integration signature or journal-bound candidate verification failed"
        ) from error
    if (
        candidate.transaction_id != prepared.transaction_id
        or prepared.registry_payload_sha256 != registry.payload_sha256
    ):
        raise ExactIntegrationError("candidate and registry identity differ")

    attestation_sha = integration.payload_sha256 if integration else None
    evidence_sha = integration.claims.evidence_sha256 if integration else None
    revision = integration.claims.window.revision if integration else None
    signed_result = integration.claims.result if integration else None
    status = ExactEvidenceStatus.UNQUALIFIED
    if integration is not None:
        claims = integration.claims
        registered = {
            canonicalize_name(item.distribution): item.component_id
            for item in registry.claims.modules
        }
        wheel_hashes = {
            registered[canonicalize_name(wheel.distribution)]: wheel.sha256
            for wheel in prepared.wheels
            if canonicalize_name(wheel.distribution) in registered
        }
        signed_publishers = {name for name, _ in candidate.publisher_digests}
        participants = {
            item.component_id: item.wheel_sha256 for item in claims.artifacts
        }
        expected = set(required_component_ids)
        if (
            claims.feature_id == feature_id
            and set(participants) == expected
            and expected <= signed_publishers
            and all(
                wheel_hashes.get(name) == digest
                for name, digest in participants.items()
            )
            and prepared.python_minor in claims.python_minors
            and prepared.platform in claims.platforms
        ):
            status = (
                ExactEvidenceStatus.EXACT_ATTESTED
                if claims.result == "passed"
                else ExactEvidenceStatus.ATTESTED_FAILURE
            )

    return ObservedExactIntegration(
        transaction_id=candidate.transaction_id,
        feature_id=feature_id,
        status=status,
        participants=tuple(sorted(required_component_ids)),
        pip_inventory_sha256=candidate.pip_inventory_sha256,
        attestation_sha256=attestation_sha,
        evidence_sha256=evidence_sha,
        signed_revision=revision,
        signed_result=signed_result,
    )


__all__ = (
    "ExactEvidenceStatus",
    "ExactIntegrationError",
    "ObservedExactIntegration",
    "inspect_journal_exact_integration",
)
