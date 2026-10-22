"""Issue #49 Slice 47: requalify physical successor bytes after a witnessed CAS.

Read-only, opt-in recovery preflight. The durable proposal and supplied
convergence finding are locally mutable assertions, NEVER authorization.
A fresh signed witness-successor read and two actual publisher/pip/native
stage audits are mandatory. No launch, active receipt write or capsule removal.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from paper_data_suite.evergreen_activation_slots import ActivationSlotError
from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_local_receipt_recovery import (
    LocalReceiptRecoveryError,
    _ordinary_read,
    _parse,
    _release,
    _snapshot,
    _with_locks,
)
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    VerifiedNativeEvidence,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
from paper_data_suite.evergreen_publisher_pip_preflight import (
    ObservedPublisherPipCandidate,
    PublisherPipPreflightError,
    audit_publisher_bound_pip_candidate,
)
from paper_data_suite.evergreen_recovery_convergence import (
    RecoveryConvergenceFinding,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    _relative_child,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    inspect_uncertain_witness_commit,
    serialize_witness_commit_request,
)


class ForwardByteRequalificationError(ValueError):
    """A selected successor cannot be read-only requalified for recovery."""


@dataclass(frozen=True, slots=True)
class ObservedForwardSuccessorBytes:
    """Ephemeral signed-byte observation, NEVER local receipt/launch authority."""

    transaction_id: str
    generation: int
    successor_receipt_sha256: str
    witness_revision: int
    pip_inventory_sha256: str
    native_payload_sha256: str
    stage_relative_path: str
    status: str = "POST_CAS_SIGNED_BYTES_OBSERVED_FORWARD_RECOVERY_STILL_REQUIRED"
    authority: str = "NO_LAUNCH_ROLLBACK_OR_RECEIPT_COMMIT_AUTHORITY"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _candidate_envelopes(value: object) -> bool:
    return (
        type(value) is dict
        and 1 <= len(value) <= 32
        and all(
            type(name) is str and type(data) is bytes and 1 <= len(data) <= 128 * 1024
            for name, data in value.items()
        )
    )


def requalify_witnessed_successor_bytes(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    convergence: RecoveryConvergenceFinding,
    candidate: ProposedCandidateEvidence,
    candidate_module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    witness_transport: CheckpointWitnessTransport,
    pinned_public_key: bytes,
    now: datetime,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    native_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> ObservedForwardSuccessorBytes:
    """Reaudit exact candidate installed bytes against a *fresh signed* head.

    Cooperative selection then transaction locks guard local observations.
    They do not defend against hostile same-user writes or independently prove
    service-owned writer termination. This function MUST NOT finalize updates.
    """
    if (
        not isinstance(convergence, RecoveryConvergenceFinding)
        or convergence.finding != "MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED"
        or convergence.authority != "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
        or not isinstance(candidate, ProposedCandidateEvidence)
        or not isinstance(trust, TrustedKeyring)
        or not _candidate_envelopes(candidate_module_envelopes)
        or type(pinned_public_key) is not bytes
        or len(pinned_public_key) != 32
        or not callable(witness_transport)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.astimezone(timezone.utc).microsecond != 0
        or layout not in (None, "windows" if os.name == "nt" else "posix")
        or any(
            type(raw) is not bytes or not 1 <= len(raw) <= 128 * 1024
            for raw in (
                candidate.prepared_record,
                candidate.registry_envelope,
                candidate.lock_envelope,
                candidate.native_envelope,
            )
        )
    ):
        raise ForwardByteRequalificationError("invalid bounded requalification inputs")
    modules = dict(candidate_module_envelopes)
    try:
        root, sl, sf, jl, jf, proposal_path = _with_locks(
            software_root, classroom_workspace, transaction_id
        )
    except (ActivationSlotError, UpdateJournalError) as error:
        raise ForwardByteRequalificationError(
            "software coordination is locked"
        ) from error
    try:
        raw = _ordinary_read(proposal_path)
        if raw is None:
            raise ForwardByteRequalificationError("missing durable successor proposal")
        persisted, _ = _parse(raw)
        request = persisted.request
        before = _snapshot(root, classroom_workspace, transaction_id, request)
        if persisted != before:
            raise ForwardByteRequalificationError("pending local state has drifted")
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
        exact_request_sha = _sha(serialize_witness_commit_request(request))
        if (
            transaction_id != successor.transaction_id
            or convergence.transaction_id != transaction_id
            or convergence.installation_id != request.installation_id
            or convergence.request_sha256 != exact_request_sha
            or convergence.predecessor_sha256 != request.predecessor_sha256
            or convergence.successor_sha256 != request.successor_sha256
            or convergence.observed_generation != successor.generation
            or convergence.observed_witness_revision
            != request.expected_witness_revision + 1
            or any(
                _sha(content) != expected
                for content, expected in (
                    (candidate.prepared_record, successor.prepared_sha256),
                    (candidate.registry_envelope, successor.registry_sha256),
                    (candidate.lock_envelope, successor.lock_sha256),
                    (candidate.native_envelope, successor.native_envelope_sha256),
                )
            )
        ):
            raise ForwardByteRequalificationError(
                "proposal or convergence identity changed"
            )
        stage = root / successor.stage_relative_path
        wheels = root / successor.wheelhouse_relative_path
        _relative_child(root, stage)
        _relative_child(root, wheels)
        if stage == wheels or stage in wheels.parents or wheels in stage.parents:
            raise ForwardByteRequalificationError("candidate stage overlaps wheelhouse")

        def audit() -> tuple[ObservedPublisherPipCandidate, VerifiedNativeEvidence]:
            pip_observed = audit_publisher_bound_pip_candidate(
                stage,
                wheels,
                prepared_record=candidate.prepared_record,
                registry_envelope=candidate.registry_envelope,
                lock_envelope=candidate.lock_envelope,
                module_envelopes=modules,
                trust=trust,
                now=now,
                registry_checkpoint=registry_checkpoint,
                lock_checkpoint=lock_checkpoint,
                layout=layout,
            )
            native = verify_signed_staged_native_evidence(
                stage,
                wheels,
                prepared_record=candidate.prepared_record,
                registry_envelope=candidate.registry_envelope,
                lock_envelope=candidate.lock_envelope,
                evidence_envelope=candidate.native_envelope,
                trust=trust,
                now=now,
                checkpoint=native_checkpoint,
                layout=layout,
            )
            if (
                pip_observed.transaction_id != transaction_id
                or pip_observed.stage_root != stage
                or pip_observed.wheelhouse != wheels
                or pip_observed.pip_inventory_sha256 != successor.pip_inventory_sha256
                or pip_observed.publisher_digests != successor.publisher_digests
                or pip_observed.root_console_targets != successor.root_console_targets
                or pip_observed.external_distributions
                != successor.external_distributions
                or native.transaction_id != transaction_id
                or native.stage_root != stage
                or native.payload_sha256 != successor.native_payload_sha256
            ):
                raise ForwardByteRequalificationError(
                    "fresh signed candidate installed bytes differ "
                    "from successor receipt"
                )
            return pip_observed, native

        first = audit()
        observed_since = time.monotonic()
        # The witness transport is read-only: it can only attest a signed head.
        signed = inspect_uncertain_witness_commit(
            request,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
            minimum_witness_revision=request.expected_witness_revision + 1,
        )
        if (
            signed.status != "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
            or signed.witness_revision != convergence.observed_witness_revision
            or signed.generation != convergence.observed_generation
            or signed.receipt_sha256 != request.successor_sha256
        ):
            raise ForwardByteRequalificationError(
                "signed head does not confirm successor"
            )
        second = audit()
        if first != second:
            raise ForwardByteRequalificationError(
                "candidate bytes changed across witness"
            )
        # Existing witness statement has a 60-second signed expiry; with its
        # date supplied by the caller, allow a conservative elapsed budget.
        if time.monotonic() - observed_since > 45.0:
            raise ForwardByteRequalificationError(
                "signed observation freshness elapsed"
            )
        if (
            candidate_module_envelopes != modules
            or _ordinary_read(proposal_path) != raw
            or _snapshot(root, classroom_workspace, transaction_id, request) != before
        ):
            raise ForwardByteRequalificationError("pending state drifted during audit")
        return ObservedForwardSuccessorBytes(
            transaction_id,
            successor.generation,
            request.successor_sha256,
            signed.witness_revision,
            second[0].pip_inventory_sha256,
            second[1].payload_sha256,
            successor.stage_relative_path,
        )
    except (
        ActiveReceiptError,
        ActivationSlotError,
        UpdateJournalError,
        LocalReceiptRecoveryError,
        WitnessCommitProtocolError,
        PublisherPipPreflightError,
        NativeEvidenceError,
    ) as error:
        raise ForwardByteRequalificationError(
            "post-commit physical requalification refused"
        ) from error
    finally:
        _release(sl, sf, jl, jf)


__all__ = (
    "ForwardByteRequalificationError",
    "ObservedForwardSuccessorBytes",
    "requalify_witnessed_successor_bytes",
)
