"""Issue #49 Slice 117: prepare a protected checkpoint compare-and-swap proposal.

PURE TRANSITION LOGIC ONLY. The previous bytes, pinned policy and signed-wheel
review are caller-controlled in this Python process, so they confer NO custody,
administrator identity, authorization, filesystem write, service or launch.
An independent native installer must obtain its baseline from OS-protected
state, authenticate the signed inputs, and perform a durable locked CAS itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, cast

from paper_data_suite.evergreen_windows_installer_intent import (
    InstallerIntentError,
    parse_untrusted_installer_intent,
)
from paper_data_suite.evergreen_windows_installer_trust_checkpoint_review import (
    InstallerTrustCheckpointReview,
)

_NO_AUTHORITY: Final = (
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
)
_REVIEW_STATUS: Final = "PINNED_TRUST_AND_REVISION_EVIDENCE_MATCH_SIGNED_WHEELS_ONLY"
_STATUS: Final = "PROPOSED_PROTECTED_CHECKPOINT_CAS_NOT_APPLIED"
_MAX_BYTES: Final = 4096
_MAX_REVISION: Final = 2**53 - 1
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_ZERO_SHA: Final = "0" * 64
_ZERO_TX: Final = "0" * 32
_FIELDS: Final = frozenset(
    {
        "schema",
        "generation",
        "trust_policy_sha256",
        "trust_policy_revision",
        "registry_revision",
        "registry_sha256",
        "lock_revision",
        "lock_sha256",
        "last_transaction_id",
        "last_request_sha256",
    }
)


class InstallerCheckpointCasError(ValueError):
    """Untrusted checkpoint transition cannot be proposed safely."""


@dataclass(frozen=True, slots=True)
class CheckpointCasProposal:
    """Unprivileged proposed record: NOT a durable write or approval token."""

    status: str
    expected_previous_sha256: str
    expected_generation: int
    proposed_generation: int
    proposed_record_bytes: bytes
    proposed_record_sha256: str
    request_sha256: str
    protected_baseline_authenticated: bool = False
    atomic_write_performed: bool = False
    service_or_admin_authenticated: bool = False
    authorized_to_provision: bool = False
    authorized_to_register_service: bool = False
    authorized_to_publish_receipt: bool = False
    authorized_to_activate_or_launch: bool = False
    authority: str = _NO_AUTHORITY


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InstallerCheckpointCasError("duplicate checkpoint JSON key")
        result[key] = value
    return result


def _canonical(obj: dict[str, object]) -> bytes:
    return json.dumps(
        obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _revision(value: object, *, zero_allowed: bool = False) -> int:
    minimum = 0 if zero_allowed else 1
    if type(value) is not int or not minimum <= value <= _MAX_REVISION:
        raise InstallerCheckpointCasError("checkpoint has invalid revision/generation")
    return value


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise InstallerCheckpointCasError("invalid checkpoint digest")
    return value


def _tx(value: object) -> str:
    if type(value) is not str or _TX.fullmatch(value) is None:
        raise InstallerCheckpointCasError("invalid checkpoint transaction ID")
    return value


def parse_claimed_checkpoint(raw: bytes) -> dict[str, object]:
    """Strictly parse local bytes. Parsing NEVER establishes protected custody."""
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_BYTES:
        raise InstallerCheckpointCasError("missing or oversized checkpoint bytes")
    try:
        decoded: object = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs
        )
    except InstallerCheckpointCasError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise InstallerCheckpointCasError("invalid checkpoint JSON") from error
    if not isinstance(decoded, dict) or set(decoded) != _FIELDS:
        raise InstallerCheckpointCasError("unexpected checkpoint schema fields")
    obj = cast(dict[str, object], decoded)
    if type(obj["schema"]) is not int or obj["schema"] != 1:
        raise InstallerCheckpointCasError("unsupported checkpoint schema")
    generation = _revision(obj["generation"], zero_allowed=True)
    _revision(obj["trust_policy_revision"])
    registry_revision = _revision(obj["registry_revision"], zero_allowed=True)
    lock_revision = _revision(obj["lock_revision"], zero_allowed=True)
    policy_digest = _sha(obj["trust_policy_sha256"])
    registry_digest = _sha(obj["registry_sha256"])
    lock_digest = _sha(obj["lock_sha256"])
    transaction = _tx(obj["last_transaction_id"])
    request_digest = _sha(obj["last_request_sha256"])
    if policy_digest == _ZERO_SHA:
        raise InstallerCheckpointCasError("trust policy not pinned in baseline")
    if generation == 0:
        if (
            registry_revision != 0
            or lock_revision != 0
            or registry_digest != _ZERO_SHA
            or lock_digest != _ZERO_SHA
            or transaction != _ZERO_TX
            or request_digest != _ZERO_SHA
        ):
            raise InstallerCheckpointCasError("malformed privileged genesis checkpoint")
    elif (
        not registry_revision
        or not lock_revision
        or registry_digest == _ZERO_SHA
        or lock_digest == _ZERO_SHA
        or transaction == _ZERO_TX
        or request_digest == _ZERO_SHA
    ):
        raise InstallerCheckpointCasError("malformed progressed checkpoint")
    if _canonical(obj) != raw:
        raise InstallerCheckpointCasError("noncanonical checkpoint bytes")
    return obj


def _monotonic(
    old_revision: int, old_digest: str, new_revision: int, new_digest: str
) -> None:
    if new_revision < old_revision or (
        new_revision == old_revision and new_digest != old_digest
    ):
        raise InstallerCheckpointCasError(
            "checkpoint revision rollback or equivocation"
        )


def propose_installer_checkpoint_cas(
    raw_intent: bytes,
    *,
    review: InstallerTrustCheckpointReview,
    claimed_previous_bytes: bytes,
) -> CheckpointCasProposal:
    """Prepare a deterministic CAS record; NEVER touch protected Windows state.

    Only an independently authenticated native service can establish the old
    record's custody, serialize a durable transaction and enforce the CAS.
    A fabricated baseline/review can produce a proposal but NEVER an approval.
    This slice deliberately forbids trust-root rotation and receipt mutation.
    """
    try:
        intent = parse_untrusted_installer_intent(raw_intent)
    except InstallerIntentError as error:
        raise InstallerCheckpointCasError("invalid installer intent") from error
    old = parse_claimed_checkpoint(claimed_previous_bytes)
    request_digest = hashlib.sha256(raw_intent).hexdigest()
    if (
        type(review) is not InstallerTrustCheckpointReview
        or review.status != _REVIEW_STATUS
        or review.request_sha256 != request_digest
        or review.registry_payload_sha256 != intent.catalog_sha256
        or review.artifact_distributions
        != tuple(item.distribution for item in intent.artifacts)
        or review.authority != _NO_AUTHORITY
        or any(
            type(getattr(review, name)) is not bool or getattr(review, name)
            for name in (
                "pin_independently_provisioned",
                "checkpoint_custody_independently_established",
                "administrator_authenticated",
                "authorized_to_provision",
                "authorized_to_register_service",
                "authorized_to_publish_receipt",
                "authorized_to_activate_or_launch",
            )
        )
    ):
        raise InstallerCheckpointCasError("inconsistent or authority-claiming review")
    previous_generation = cast(int, old["generation"])
    if previous_generation == _MAX_REVISION:
        raise InstallerCheckpointCasError("checkpoint generation exhausted")
    for revision in (
        review.trust_policy_revision,
        review.registry_revision,
        review.signed_lock_revision,
    ):
        _revision(revision)
    for digest in (
        review.trust_policy_sha256,
        review.registry_payload_sha256,
        review.signed_lock_payload_sha256,
    ):
        if _sha(digest) == _ZERO_SHA:
            raise InstallerCheckpointCasError("uninitialized new digest")
    if (
        old["trust_policy_sha256"] != review.trust_policy_sha256
        or old["trust_policy_revision"] != review.trust_policy_revision
    ):
        raise InstallerCheckpointCasError("root rotation requires separate protocol")
    _monotonic(
        cast(int, old["registry_revision"]),
        cast(str, old["registry_sha256"]),
        review.registry_revision,
        review.registry_payload_sha256,
    )
    _monotonic(
        cast(int, old["lock_revision"]),
        cast(str, old["lock_sha256"]),
        review.signed_lock_revision,
        review.signed_lock_payload_sha256,
    )
    if old["last_transaction_id"] == intent.transaction_id:
        raise InstallerCheckpointCasError("transaction replay against claimed baseline")
    if previous_generation != 0:
        raise InstallerCheckpointCasError(
            "new-install intent cannot replace an existing installation checkpoint"
        )
    next_record = {
        "schema": 1,
        "generation": previous_generation + 1,
        "trust_policy_sha256": review.trust_policy_sha256,
        "trust_policy_revision": review.trust_policy_revision,
        "registry_revision": review.registry_revision,
        "registry_sha256": review.registry_payload_sha256,
        "lock_revision": review.signed_lock_revision,
        "lock_sha256": review.signed_lock_payload_sha256,
        "last_transaction_id": intent.transaction_id,
        "last_request_sha256": request_digest,
    }
    proposed = _canonical(next_record)
    if len(proposed) > _MAX_BYTES:
        raise InstallerCheckpointCasError("proposed record too large")
    return CheckpointCasProposal(
        status=_STATUS,
        expected_previous_sha256=hashlib.sha256(claimed_previous_bytes).hexdigest(),
        expected_generation=previous_generation,
        proposed_generation=previous_generation + 1,
        proposed_record_bytes=proposed,
        proposed_record_sha256=hashlib.sha256(proposed).hexdigest(),
        request_sha256=request_digest,
    )


__all__ = (
    "CheckpointCasProposal",
    "InstallerCheckpointCasError",
    "parse_claimed_checkpoint",
    "propose_installer_checkpoint_cas",
)
