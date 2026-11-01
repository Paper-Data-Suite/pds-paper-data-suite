"""Issue #49 Slice 114: correlate installer intent with freshly signed wheels.

The caller supplies bytes, wheel paths and a keyring; the independent root of
trust, durable monotonic checkpoints, administrative actor and consent are NOT
established here. No install, service, receipt, launch or network operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_release_artifacts import (
    ReleaseArtifactError,
    VerifiedReleaseWheel,
    verify_signed_release_wheel,
)
from paper_data_suite.evergreen_windows_installer_intent import (
    InstallerIntentError,
    parse_untrusted_installer_intent,
)

_MAX_ENVELOPE: Final = 256 * 1024
_NO_AUTHORITY: Final = (
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
)


class InstallerSignedWheelBridgeError(ValueError):
    """The untrusted request cannot be reconciled to signed wheel bytes."""


@dataclass(frozen=True, slots=True)
class SignedWheelCandidate:
    """Caller-selected wheel source; neither a trusted path nor install input."""

    distribution: str
    wheel_path: Path
    module_envelope: bytes


@dataclass(frozen=True, slots=True)
class SignedWheelBridgeReview:
    """Exact signed-byte consistency only; cannot authorize any side effect."""

    status: str
    request_sha256: str
    registry_payload_sha256: str
    matched_distributions: tuple[str, ...]
    matched_wheel_sha256: tuple[str, ...]
    signer_context: str = "CALLER_KEYRING_NOT_INDEPENDENTLY_PINNED"
    monotonic_checkpoints: str = "NOT_INDEPENDENTLY_VERIFIED"
    administrator_identity: str = "NOT_AUTHENTICATED"
    recovery_basis: str = "UNVERIFIED_REQUEST_CLAIM"
    authorized_to_provision: bool = False
    authorized_to_register_service: bool = False
    authorized_to_publish_receipt: bool = False
    authorized_to_activate_or_launch: bool = False
    authority: str = _NO_AUTHORITY


def review_installer_signed_wheels(
    raw_intent: bytes,
    *,
    candidates: tuple[SignedWheelCandidate, ...],
    registry_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
) -> SignedWheelBridgeReview:
    """Reverify all signed metadata/wheel bytes against *untrusted* intent.

    Do not supply keyrings, timestamps, or files from an untrusted request as
    installer authority. The eventual independently administered service must
    verify pinned roots, monotonic state, identity, consent and recovery itself.
    Even this successful review is never an authorization token.
    """
    try:
        intent = parse_untrusted_installer_intent(raw_intent)
    except InstallerIntentError as exc:
        raise InstallerSignedWheelBridgeError("invalid installer intent") from exc
    if (
        type(candidates) is not tuple
        or len(candidates) != len(intent.artifacts)
        or type(registry_envelope) is not bytes
        or not 1 <= len(registry_envelope) <= _MAX_ENVELOPE
        or type(trust) is not TrustedKeyring
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise InstallerSignedWheelBridgeError("invalid signed wheel review inputs")

    reviewed: list[VerifiedReleaseWheel] = []
    paths: set[Path] = set()
    for expected, candidate in zip(intent.artifacts, candidates, strict=True):
        if (
            type(candidate) is not SignedWheelCandidate
            or type(candidate.distribution) is not str
            or candidate.distribution != expected.distribution
            or not isinstance(candidate.wheel_path, Path)
            or type(candidate.module_envelope) is not bytes
            or not 1 <= len(candidate.module_envelope) <= _MAX_ENVELOPE
            or candidate.wheel_path in paths
        ):
            raise InstallerSignedWheelBridgeError("wheel candidate scope mismatch")
        paths.add(candidate.wheel_path)
        try:
            evidence = verify_signed_release_wheel(
                candidate.wheel_path,
                registry_envelope=registry_envelope,
                module_envelope=candidate.module_envelope,
                trust=trust,
                now=now,
                version=expected.version,
            )
        except (ReleaseArtifactError, OSError) as exc:
            raise InstallerSignedWheelBridgeError(
                "signed release or wheel verification failed"
            ) from exc
        if (
            type(evidence) is not VerifiedReleaseWheel
            or evidence.distribution != expected.distribution
            or evidence.version != expected.version
            or evidence.sha256 != expected.sha256
            or evidence.registry_payload_sha256 != intent.catalog_sha256
        ):
            raise InstallerSignedWheelBridgeError(
                "signed wheel identity or catalog differs from intent"
            )
        reviewed.append(evidence)
    components = tuple(wheel.component_id for wheel in reviewed)
    if len(set(components)) != len(components):
        raise InstallerSignedWheelBridgeError("duplicate signed module identity")

    return SignedWheelBridgeReview(
        status="SIGNED_WHEEL_BYTES_MATCH_UNTRUSTED_INTENT_ONLY",
        request_sha256=hashlib.sha256(raw_intent).hexdigest(),
        registry_payload_sha256=intent.catalog_sha256,
        matched_distributions=tuple(wheel.distribution for wheel in reviewed),
        matched_wheel_sha256=tuple(wheel.sha256 for wheel in reviewed),
    )


def main(argv: list[str] | None = None) -> int:
    """Read-only informational CLI; no paths, approvals or apply mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(
        json.dumps(
            {
                "status": "INDEPENDENT_SIGNED_WHEEL_EVIDENCE_NOT_SUBMITTED",
                "verification_contract": (
                    "SIGNED_WHEEL_BYTES_MATCH_UNTRUSTED_INTENT_ONLY"
                ),
                "privileged_installer_implemented": False,
                "independent_trust_root_established": False,
                "monotonic_checkpoints_established": False,
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
    sys.exit(main())
