"""Issue #49 Slice 116: bind candidate installer wheels to pinned trust evidence.

The trust digest and checkpoint inputs are locally forgeable here. Reverify
root-signed metadata under the supplied pin and previous revision checkpoints,
then correlate with the existing closed-wheelhouse review. This is a READ-ONLY
consistency gate, NOT independently provisioned trust, durable rollback custody,
an administrator approval or a protected-install capability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    RevisionCheckpoint,
    verify_registry_document,
)
from paper_data_suite.evergreen_dependency_lock import (
    DependencyLockError,
    verify_signed_dependency_lock,
)
from paper_data_suite.evergreen_trust_provisioning import (
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)
from paper_data_suite.evergreen_windows_installer_intent import (
    InstallerIntentError,
    parse_untrusted_installer_intent,
)
from paper_data_suite.evergreen_windows_installer_locked_wheelhouse import (
    InstallerLockedWheelhouseError,
    review_installer_locked_wheelhouse,
)
from paper_data_suite.evergreen_windows_installer_signed_wheel_bridge import (
    SignedWheelCandidate,
)

_MAX_POLICY: Final = 24 * 1024
_MAX_REGISTRY: Final = 256 * 1024
_MAX_LOCK: Final = 48 * 1024
_NO_AUTHORITY: Final = (
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
)
_CLOSED_STATUS: Final = (
    "SIGNED_CLOSED_WHEELHOUSE_MATCHES_UNTRUSTED_INSTALLER_INTENT_ONLY"
)


class InstallerTrustCheckpointError(ValueError):
    """Caller-provided trust/checkpoints do not agree with signed evidence."""


@dataclass(frozen=True, slots=True)
class InstallerTrustCheckpointReview:
    """Transitive signed evidence coherence, never a privilege credential."""

    status: str
    request_sha256: str
    trust_policy_sha256: str
    trust_policy_revision: int
    registry_payload_sha256: str
    registry_revision: int
    signed_lock_payload_sha256: str
    signed_lock_revision: int
    artifact_distributions: tuple[str, ...]
    dependency_edge_count: int
    pin_independently_provisioned: bool = False
    checkpoint_custody_independently_established: bool = False
    administrator_authenticated: bool = False
    authorized_to_provision: bool = False
    authorized_to_register_service: bool = False
    authorized_to_publish_receipt: bool = False
    authorized_to_activate_or_launch: bool = False
    authority: str = _NO_AUTHORITY


def review_installer_trust_and_checkpoints(
    raw_intent: bytes,
    *,
    candidates: tuple[SignedWheelCandidate, ...],
    wheelhouse: Path,
    registry_envelope: bytes,
    lock_envelope: bytes,
    trust_policy_bytes: bytes,
    expected_policy_sha256: str,
    previous_registry: RevisionCheckpoint,
    previous_lock: RevisionCheckpoint,
    now: datetime,
) -> InstallerTrustCheckpointReview:
    """Reverify a digest-pinned keyring, revisions, and exact locked wheels.

    The `expected_policy_sha256` and previous checkpoints are NOT independently
    authenticated merely by being passed to this Python function. An eventual
    protected service must obtain them from independently controlled custody,
    persist monotonic state and recheck all evidence in a single transaction.
    """
    if (
        type(raw_intent) is not bytes
        or type(candidates) is not tuple
        or not isinstance(wheelhouse, Path)
        or type(registry_envelope) is not bytes
        or not 1 <= len(registry_envelope) <= _MAX_REGISTRY
        or type(lock_envelope) is not bytes
        or not 1 <= len(lock_envelope) <= _MAX_LOCK
        or type(trust_policy_bytes) is not bytes
        or not 1 <= len(trust_policy_bytes) <= _MAX_POLICY
        or type(expected_policy_sha256) is not str
        or type(previous_registry) is not RevisionCheckpoint
        or type(previous_lock) is not RevisionCheckpoint
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise InstallerTrustCheckpointError("invalid pinned trust review inputs")
    try:
        intent = parse_untrusted_installer_intent(raw_intent)
        pinned = load_digest_pinned_trust_policy(
            trust_policy_bytes, pinned_sha256=expected_policy_sha256
        )
        registry = verify_registry_document(
            registry_envelope,
            trust=pinned.keyring,
            now=now,
            checkpoint=previous_registry,
        )
        lock = verify_signed_dependency_lock(
            lock_envelope,
            registry_envelope=registry_envelope,
            trust=pinned.keyring,
            now=now,
            checkpoint=previous_lock,
            registry_checkpoint=previous_registry,
        )
    except (
        InstallerIntentError,
        TrustProvisioningError,
        CatalogVerificationError,
        DependencyLockError,
        ValueError,
    ) as exc:
        raise InstallerTrustCheckpointError(
            "trust pin, previous revision, or signed metadata refused"
        ) from exc
    if (
        pinned.sha256 != expected_policy_sha256
        or registry.payload_sha256 != intent.catalog_sha256
        or lock.registry_payload_sha256 != registry.payload_sha256
        or lock.trust_fingerprint != registry.trust_fingerprint
        or set(lock.roots) != {item.distribution for item in intent.artifacts}
        or len(lock.roots) != len(intent.artifacts)
        or registry.checkpoint.revision < previous_registry.revision
        or lock.checkpoint.revision < previous_lock.revision
        or registry.checkpoint.payload_sha256 != registry.payload_sha256
        or lock.checkpoint.payload_sha256 != lock.payload_sha256
    ):
        raise InstallerTrustCheckpointError(
            "signed registry, lock, or revision checkpoint is inconsistent"
        )
    try:
        closed = review_installer_locked_wheelhouse(
            raw_intent,
            candidates=candidates,
            wheelhouse=wheelhouse,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            trust=pinned.keyring,
            now=now,
        )
    except (InstallerLockedWheelhouseError, OSError, ValueError) as exc:
        raise InstallerTrustCheckpointError(
            "signed closed-wheelhouse evidence refused"
        ) from exc
    expected_names = tuple(item.distribution for item in intent.artifacts)
    if (
        closed.status != _CLOSED_STATUS
        or closed.request_sha256 != hashlib.sha256(raw_intent).hexdigest()
        or closed.registry_payload_sha256 != registry.payload_sha256
        or closed.signed_lock_payload_sha256 != lock.payload_sha256
        or closed.signed_lock_revision != lock.revision
        or closed.pds_distributions != expected_names
        or closed.authority != _NO_AUTHORITY
        or any(
            getattr(closed, field) is not False
            for field in (
                "independently_pinned_root",
                "independently_continuous_checkpoints",
                "authenticated_administrator",
                "authorized_to_provision",
                "authorized_to_register_service",
                "authorized_to_publish_receipt",
                "authorized_to_activate_or_launch",
            )
        )
    ):
        raise InstallerTrustCheckpointError(
            "signed closed-wheelhouse review is inconsistent or claims authority"
        )
    return InstallerTrustCheckpointReview(
        status="PINNED_TRUST_AND_REVISION_EVIDENCE_MATCH_SIGNED_WHEELS_ONLY",
        request_sha256=closed.request_sha256,
        trust_policy_sha256=pinned.sha256,
        trust_policy_revision=pinned.policy_revision,
        registry_payload_sha256=registry.payload_sha256,
        registry_revision=registry.checkpoint.revision,
        signed_lock_payload_sha256=lock.payload_sha256,
        signed_lock_revision=lock.revision,
        artifact_distributions=expected_names,
        dependency_edge_count=closed.dependency_edge_count,
    )


def main(argv: list[str] | None = None) -> int:
    """Read-only diagnostic; no user-supplied pin, path, apply or consent flag."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(
        json.dumps(
            {
                "status": "INDEPENDENT_TRUST_AND_CHECKPOINT_EVIDENCE_NOT_SUBMITTED",
                "verification_contract": (
                    "PINNED_TRUST_AND_REVISION_EVIDENCE_MATCH_SIGNED_WHEELS_ONLY"
                ),
                "independent_root_pin_provisioned": False,
                "protected_monotonic_checkpoints_established": False,
                "authenticated_administrator": False,
                "privileged_installer_implemented": False,
                "production_authority": False,
                "active_receipt_authority": False,
                "authority": _NO_AUTHORITY,
            },
            indent=2,
        )
    )
    print(_NO_AUTHORITY)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
