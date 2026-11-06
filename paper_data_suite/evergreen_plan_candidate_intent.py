"""Issue #49 Slice 70: persist plan-bound candidate intent after native signing.

The signing authority is external. The supplied envelope MUST pass the existing
root-quorum verifier, and an exact fresh unsigned request is recomputed before
writing an ordinary update-intent journal. The journal is mutable same-user
bookkeeping, never a trusted active-state receipt or activation permission.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, cast

from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_plan_native_request import (
    NativeSigningRequestError,
    UnsignedNativeSigningRequest,
    prepare_unsigned_native_evidence_request,
)
from paper_data_suite.evergreen_plan_stage_installer import IsolatedPlanStageResult
from paper_data_suite.evergreen_plan_staged_candidate import (
    PlanStagedCandidateError,
    inspect_plan_bound_staged_candidate,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
    begin_verified_update_intent,
    load_update_intent,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)

_CONSENT: Final = "RECORD_SIGNED_CANDIDATE_VERIFIED_INTENT"
_MAX_NATIVE_ENVELOPE: Final = 32 * 1024
_MAX_PAYLOAD: Final = 24 * 1024
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_UTC: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class PlanCandidateIntentError(ValueError):
    """Independently signed candidate cannot be durably recorded as an intent."""


@dataclass(frozen=True, slots=True)
class RecordedPlanCandidateIntent:
    """Candidate journal reference: not an active installation credential."""

    transaction_id: str
    journal_revision: int
    native_payload_sha256: str
    pip_inventory_sha256: str
    baseline_transaction_id: str
    baseline_witness_revision: int
    status: str = "CANDIDATE_VERIFIED_INTENT_NOT_ACTIVATED"
    authority: str = "NO_SELECTION_SWITCH_RECEIPT_WRITE_OR_LAUNCH_AUTHORITY"


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise PlanCandidateIntentError("duplicate signed evidence field")
        output[key] = value
    return output


def _object(raw: bytes, label: str) -> dict[str, object]:
    try:
        parsed: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except PlanCandidateIntentError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise PlanCandidateIntentError(f"malformed {label}") from error
    if not isinstance(parsed, dict):
        raise PlanCandidateIntentError(f"invalid {label} object")
    return cast(dict[str, object], parsed)


def _native_payload(envelope: bytes) -> tuple[bytes, dict[str, object]]:
    """Extract bytes ONLY for equality checks; this does NOT verify signatures."""
    outer = _object(envelope, "native evidence envelope")
    if outer.keys() != {"envelope_version", "payload_b64", "signatures"}:
        raise PlanCandidateIntentError("unexpected native evidence envelope fields")
    if type(outer["envelope_version"]) is not int or outer["envelope_version"] != 1:
        raise PlanCandidateIntentError("unsupported native envelope version")
    value = outer["payload_b64"]
    if not isinstance(value, str) or len(value) > 4 * ((_MAX_PAYLOAD + 2) // 3):
        raise PlanCandidateIntentError("invalid native evidence encoding")
    try:
        payload = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise PlanCandidateIntentError("invalid native evidence base64") from error
    if (
        not 1 <= len(payload) <= _MAX_PAYLOAD
        or base64.b64encode(payload).decode("ascii") != value
    ):
        raise PlanCandidateIntentError("noncanonical native evidence payload")
    return payload, _object(payload, "native evidence payload")


def _signed_clock(value: object) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PlanCandidateIntentError("noncanonical signed native evidence clock")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise PlanCandidateIntentError("invalid native evidence clock") from error


def record_signed_plan_candidate_intent(
    snapshot: CatalogSnapshot,
    witnessed: WitnessSelectedStageObservation,
    installed: IsolatedPlanStageResult,
    unsigned_request: UnsignedNativeSigningRequest,
    software_root: Path,
    *,
    classroom_workspace: Path,
    wheelhouse: Path,
    requested_targets: dict[str, str | None],
    python_minor: str,
    platform_tag: str,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    native_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    explicit_consent: str,
    previous_receipt_sha256: str | None = None,
    layout: str | None = None,
) -> RecordedPlanCandidateIntent:
    """Reconcile independently signed native bytes, then persist intent ONLY.

    Native signatures require independently provisioned root trust and physical
    provenance review. Fresh witness observation here is transient; the later
    activator MUST repeat protected witness/CAS checks. A failed post-write
    check leaves an unselected journal for explicit reconciliation, never an
    automatic retry or promotion.
    """
    if (
        explicit_consent != _CONSENT
        or type(explicit_consent) is not str
        or not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(witnessed, WitnessSelectedStageObservation)
        or not isinstance(installed, IsolatedPlanStageResult)
        or not isinstance(unsigned_request, UnsignedNativeSigningRequest)
        or not isinstance(software_root, Path)
        or not isinstance(classroom_workspace, Path)
        or not isinstance(wheelhouse, Path)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or type(native_envelope) is not bytes
        or not 1 <= len(native_envelope) <= _MAX_NATIVE_ENVELOPE
        or type(registry_envelope) is not bytes
        or type(lock_envelope) is not bytes
        or type(module_envelopes) is not dict
        or not 1 <= len(module_envelopes) <= 32
        or any(
            type(k) is not str or type(v) is not bytes
            for k, v in module_envelopes.items()
        )
        or type(requested_targets) is not dict
        or layout not in (None, "posix", "windows")
        or (
            previous_receipt_sha256 is not None
            and (
                type(previous_receipt_sha256) is not str
                or _SHA.fullmatch(previous_receipt_sha256) is None
            )
        )
    ):
        raise PlanCandidateIntentError("signed candidate intent inputs invalid")
    if (
        type(installed.transaction_id) is not str
        or _TX.fullmatch(installed.transaction_id) is None
    ):
        raise PlanCandidateIntentError("invalid staged candidate identity")
    try:
        root = _safe_root(software_root, classroom_workspace)
        stage = installed.stage_root.absolute()
        wheels = wheelhouse.absolute()
        stage_relative = _relative_child(root, stage)
        wheel_relative = _relative_child(root, wheels)
        if (
            stage != root / "candidate-builds" / installed.transaction_id
            or stage == wheels
            or stage in wheels.parents
            or wheels in stage.parents
        ):
            raise PlanCandidateIntentError("candidate paths are not isolated")
        if (
            load_update_intent(
                root,
                classroom_workspace=classroom_workspace,
                transaction_id=installed.transaction_id,
            )
            is not None
        ):
            raise PlanCandidateIntentError("candidate intent already exists")
        # CRITICAL: authenticate signer, signed scope, and actual native bytes
        # BEFORE consulting the unsigned request for a plan-to-journal grant.
        signed = verify_signed_staged_native_evidence(
            stage,
            wheels,
            evidence_envelope=native_envelope,
            prepared_record=installed.prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
        payload, claims = _native_payload(native_envelope)
        if (
            signed.transaction_id != installed.transaction_id
            or signed.stage_root != stage
            or hashlib.sha256(payload).hexdigest() != signed.payload_sha256
            or unsigned_request.payload != payload
            or unsigned_request.payload_sha256 != signed.payload_sha256
            or unsigned_request.transaction_id != installed.transaction_id
            or unsigned_request.file_count != len(signed.binaries)
        ):
            raise PlanCandidateIntentError(
                "signed native envelope differs from request"
            )
        # The unsigned request could be caller-forged. Recompute from exact
        # package and executable bytes, using ONLY authenticated time/revision.
        regenerated = prepare_unsigned_native_evidence_request(
            snapshot,
            witnessed,
            installed,
            root,
            classroom_workspace=classroom_workspace,
            wheelhouse=wheels,
            requested_targets=requested_targets,
            python_minor=python_minor,
            platform_tag=platform_tag,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            module_envelopes=module_envelopes,
            trust=trust,
            now=now,
            revision=signed.revision,
            issued_at=_signed_clock(claims.get("issued_at")),
            expires_at=_signed_clock(claims.get("expires_at")),
            layout=layout,
        )
        if regenerated != unsigned_request:
            raise PlanCandidateIntentError("signed request changed from physical stage")
        observed = inspect_plan_bound_staged_candidate(
            snapshot,
            witnessed,
            root,
            classroom_workspace=classroom_workspace,
            stage_root=stage,
            wheelhouse=wheels,
            prepared_record=installed.prepared_record,
            requested_targets=requested_targets,
            python_minor=python_minor,
            platform_tag=platform_tag,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            module_envelopes=module_envelopes,
            native_envelope=native_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
        if (
            observed.transaction_id != installed.transaction_id
            or observed.baseline_transaction_id != witnessed.transaction_id
            or observed.baseline_witness_revision != witnessed.witness_revision
            or observed.registry_payload_sha256 != snapshot.registry.payload_sha256
            or observed.signed_lock_payload_sha256
            != installed.signed_lock_payload_sha256
            or observed.pip_inventory_sha256 != installed.pip_inventory_sha256
            or observed.native_payload_sha256 != signed.payload_sha256
            or observed.prepared_record_sha256
            != hashlib.sha256(installed.prepared_record).hexdigest()
            or observed.status != "PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE"
            or observed.authority
            != "NO_ACTIVE_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY"
        ):
            raise PlanCandidateIntentError(
                "signed installed candidate does not match plan"
            )
        journal = begin_verified_update_intent(
            root,
            classroom_workspace=classroom_workspace,
            stage_root=stage,
            wheelhouse=wheels,
            prepared_record=installed.prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            evidence_envelope=native_envelope,
            trust=trust,
            now=now,
            previous_receipt_sha256=previous_receipt_sha256,
            layout=layout,
        )
        if (
            journal.transaction_id != installed.transaction_id
            or journal.phase is not UpdatePhase.CANDIDATE_VERIFIED
            or journal.revision != 1
            or journal.stage_relative_path != stage_relative
            or journal.wheelhouse_relative_path != wheel_relative
            or journal.prepared_sha256
            != hashlib.sha256(installed.prepared_record).hexdigest()
            or journal.native_envelope_sha256
            != hashlib.sha256(native_envelope).hexdigest()
            or journal.expected_previous_receipt_sha256 != previous_receipt_sha256
            or load_update_intent(
                root,
                classroom_workspace=classroom_workspace,
                transaction_id=installed.transaction_id,
            )
            != journal
        ):
            raise PlanCandidateIntentError("persisted intent needs reconciliation")
        return RecordedPlanCandidateIntent(
            installed.transaction_id,
            journal.revision,
            signed.payload_sha256,
            installed.pip_inventory_sha256,
            witnessed.transaction_id,
            witnessed.witness_revision,
        )
    except (
        NativeEvidenceError,
        NativeSigningRequestError,
        PlanStagedCandidateError,
        UpdateJournalError,
        OSError,
    ) as error:
        raise PlanCandidateIntentError(
            "independently signed candidate could not be journaled"
        ) from error


__all__ = (
    "PlanCandidateIntentError",
    "RecordedPlanCandidateIntent",
    "record_signed_plan_candidate_intent",
)
