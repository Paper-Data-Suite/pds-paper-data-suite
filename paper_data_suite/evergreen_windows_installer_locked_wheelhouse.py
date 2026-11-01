"""Issue #49 Slice 115: bind signed installer wheels to closed dependency lock.

Only a read-only consistency proof: caller keyring/checkpoints are not
independently provisioned. No install, service, approval, receipt, or launch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_dependency_lock import (
    DependencyLockError,
    verify_signed_locked_wheelhouse,
)
from paper_data_suite.evergreen_windows_installer_intent import (
    _DIST,
    InstallerIntentError,
    parse_untrusted_installer_intent,
)
from paper_data_suite.evergreen_windows_installer_signed_wheel_bridge import (
    InstallerSignedWheelBridgeError,
    SignedWheelCandidate,
    review_installer_signed_wheels,
)

_MAX_LOCK: Final = 48 * 1024
_MAX_REGISTRY: Final = 256 * 1024
_NO_AUTHORITY: Final = (
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
)


class InstallerLockedWheelhouseError(ValueError):
    """Requested wheels and a freshly signed closed wheelhouse disagree."""


@dataclass(frozen=True, slots=True)
class LockedInstallerWheelhouseReview:
    """Read-only wheel consistency; never an authorization credential."""

    status: str
    request_sha256: str
    registry_payload_sha256: str
    signed_lock_payload_sha256: str
    signed_lock_revision: int
    python_minor: str
    platform_tag: str
    pds_distributions: tuple[str, ...]
    external_dependency_distributions: tuple[str, ...]
    dependency_edge_count: int
    independently_pinned_root: bool = False
    independently_continuous_checkpoints: bool = False
    authenticated_administrator: bool = False
    authorized_to_provision: bool = False
    authorized_to_register_service: bool = False
    authorized_to_publish_receipt: bool = False
    authorized_to_activate_or_launch: bool = False
    authority: str = _NO_AUTHORITY


def review_installer_locked_wheelhouse(
    raw_intent: bytes,
    *,
    candidates: tuple[SignedWheelCandidate, ...],
    wheelhouse: Path,
    registry_envelope: bytes,
    lock_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
) -> LockedInstallerWheelhouseReview:
    """Reverify the lock and individual signed wheels against untrusted intent.

    This does not prove independent key custody or persistent anti-rollback.
    Even matching caller-supplied signed evidence cannot authorize an install.
    """
    try:
        intent = parse_untrusted_installer_intent(raw_intent)
    except InstallerIntentError as exc:
        raise InstallerLockedWheelhouseError("invalid installer intent") from exc
    if (
        type(candidates) is not tuple
        or len(candidates) != len(intent.artifacts)
        or not isinstance(wheelhouse, Path)
        or type(registry_envelope) is not bytes
        or not 1 <= len(registry_envelope) <= _MAX_REGISTRY
        or type(lock_envelope) is not bytes
        or not 1 <= len(lock_envelope) <= _MAX_LOCK
        or type(trust) is not TrustedKeyring
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise InstallerLockedWheelhouseError("invalid wheelhouse verification inputs")

    try:
        closed = verify_signed_locked_wheelhouse(
            wheelhouse,
            lock_envelope=lock_envelope,
            registry_envelope=registry_envelope,
            trust=trust,
            now=now,
        )
    except (DependencyLockError, OSError, ValueError) as exc:
        raise InstallerLockedWheelhouseError(
            "signed lock or closed dependency wheelhouse refused"
        ) from exc

    expected_names = tuple(item.distribution for item in intent.artifacts)
    if (
        closed.lock.registry_payload_sha256 != intent.catalog_sha256
        or set(closed.lock.roots) != set(expected_names)
        or len(closed.lock.roots) != len(expected_names)
    ):
        raise InstallerLockedWheelhouseError(
            "signed lock registry or root set differs from installer intent"
        )

    observed = {item.distribution: item for item in closed.inspection.wheels}
    if len(observed) != len(closed.inspection.wheels):
        raise InstallerLockedWheelhouseError("duplicate locked wheel distribution")
    # A signed dependency lock can include third-party transitive requirements,
    # but cannot silently add another PDS distribution to an installer request.
    actual_pds = {name for name in observed if name in _DIST}
    if actual_pds != set(expected_names) or any(
        name.startswith("pds-") and name not in _DIST for name in observed
    ):
        raise InstallerLockedWheelhouseError(
            "extra or missing PDS wheel in closed dependency lock"
        )
    for expected, candidate in zip(intent.artifacts, candidates, strict=True):
        locked = observed.get(expected.distribution)
        if (
            locked is None
            or type(candidate) is not SignedWheelCandidate
            or candidate.distribution != expected.distribution
            or not isinstance(candidate.wheel_path, Path)
            or candidate.wheel_path != wheelhouse / locked.filename
            or locked.version != expected.version
            or locked.sha256 != expected.sha256
        ):
            raise InstallerLockedWheelhouseError(
                "requested signed wheel differs from locked wheelhouse bytes"
            )

    try:
        matched = review_installer_signed_wheels(
            raw_intent,
            candidates=candidates,
            registry_envelope=registry_envelope,
            trust=trust,
            now=now,
        )
    except (InstallerSignedWheelBridgeError, OSError, ValueError) as exc:
        raise InstallerLockedWheelhouseError(
            "publisher-signed wheel verification refused"
        ) from exc
    if (
        matched.status != "SIGNED_WHEEL_BYTES_MATCH_UNTRUSTED_INTENT_ONLY"
        or matched.request_sha256 != hashlib.sha256(raw_intent).hexdigest()
        or matched.registry_payload_sha256 != intent.catalog_sha256
        or matched.matched_distributions != expected_names
        or matched.matched_wheel_sha256
        != tuple(item.sha256 for item in intent.artifacts)
        or matched.authority != _NO_AUTHORITY
        or any(
            getattr(matched, name) is not False
            for name in (
                "authorized_to_provision",
                "authorized_to_register_service",
                "authorized_to_publish_receipt",
                "authorized_to_activate_or_launch",
            )
        )
    ):
        raise InstallerLockedWheelhouseError(
            "signed wheel bridge asserts inconsistent evidence"
        )

    external = tuple(sorted(name for name in observed if name not in actual_pds))
    return LockedInstallerWheelhouseReview(
        status="SIGNED_CLOSED_WHEELHOUSE_MATCHES_UNTRUSTED_INSTALLER_INTENT_ONLY",
        request_sha256=matched.request_sha256,
        registry_payload_sha256=intent.catalog_sha256,
        signed_lock_payload_sha256=closed.lock.payload_sha256,
        signed_lock_revision=closed.lock.revision,
        python_minor=closed.lock.python_minor,
        platform_tag=closed.lock.platform,
        pds_distributions=expected_names,
        external_dependency_distributions=external,
        dependency_edge_count=len(closed.inspection.dependency_edges),
    )


def main(argv: list[str] | None = None) -> int:
    """Describe the read-only contract; do not accept files or approval flags."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(
        json.dumps(
            {
                "status": "INDEPENDENT_SIGNED_DEPENDENCY_LOCK_NOT_SUBMITTED",
                "verification_contract": (
                    "SIGNED_CLOSED_WHEELHOUSE_MATCHES_UNTRUSTED_INSTALLER_INTENT_ONLY"
                ),
                "root_trust_independently_pinned": False,
                "persistent_rollback_checkpoints_established": False,
                "administrator_authenticated": False,
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
