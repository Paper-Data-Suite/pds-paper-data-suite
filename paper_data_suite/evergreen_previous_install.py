"""Issue #49: reverify a selected prior software slot, WITHOUT activation trust.

A locally replaceable pointer or receipt has no signing authority. This module
rechecks signed wheel/native bytes under independently trusted publisher keys,
binds those observations to an exact local record, and returns non-authorizing
prior-byte evidence. It does not certify that the slot was EVER active.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, cast

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    read_candidate_selection,
)
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    _relative_child,
    _safe_root,
)

_MAX_RECORD: Final = 8192
_HASH: Final = re.compile(r"[0-9a-f]{64}\Z")
_ID: Final = re.compile(r"[0-9a-f]{32}\Z")
_REF: Final = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")


class PreviousInstallationError(ValueError):
    """Previous-slot metadata or its cryptographic stage recheck is invalid."""


@dataclass(frozen=True, slots=True)
class PreviousSlotObservation:
    """Freshly reverified prior software BYTES, not historical installation trust."""

    transaction_id: str
    stage_relative_path: str
    wheelhouse_relative_path: str
    selection_generation: int
    prepared_sha256: str
    registry_envelope_sha256: str
    lock_envelope_sha256: str
    native_envelope_sha256: str
    native_payload_sha256: str
    native_revision: int


@dataclass(frozen=True, slots=True)
class VerifiedPreviousSlotBytes:
    """Matches a local record and signed bytes; not a launch/rollback credential."""

    observation: PreviousSlotObservation
    record_sha256: str


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checked(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        raise PreviousInstallationError(f"invalid previous-slot {label}")
    return value


def _ref(value: object, label: str) -> str:
    raw = _checked(value, _REF, label)
    if any(segment in {".", ".."} for segment in raw.split("/")):
        raise PreviousInstallationError(f"unsafe previous-slot {label}")
    return raw


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PreviousInstallationError("duplicate previous-slot JSON member")
        result[key] = value
    return result


def _encode(observation: PreviousSlotObservation) -> bytes:
    raw = json.dumps(
        {
            "record_type": "pds_evergreen_previous_slot_byte_observation",
            "schema_version": 1,
            "phase": "reverified_bytes_not_active_receipt",
            "transaction_id": observation.transaction_id,
            "stage_relative_path": observation.stage_relative_path,
            "wheelhouse_relative_path": observation.wheelhouse_relative_path,
            "selection_generation": observation.selection_generation,
            "prepared_sha256": observation.prepared_sha256,
            "registry_envelope_sha256": observation.registry_envelope_sha256,
            "lock_envelope_sha256": observation.lock_envelope_sha256,
            "native_envelope_sha256": observation.native_envelope_sha256,
            "native_payload_sha256": observation.native_payload_sha256,
            "native_revision": observation.native_revision,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(raw) > _MAX_RECORD:
        raise PreviousInstallationError("previous-slot observation too large")
    return raw


def parse_untrusted_previous_slot_record(data: bytes) -> PreviousSlotObservation:
    """Strict parse only: NEVER interprets an editable file as authorization."""
    if type(data) is not bytes or not 1 <= len(data) <= _MAX_RECORD:
        raise PreviousInstallationError("invalid previous-slot record length")
    try:
        parsed: object = json.loads(data.decode("utf-8"), object_pairs_hook=_unique)
    except PreviousInstallationError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise PreviousInstallationError("invalid previous-slot JSON") from error
    if not isinstance(parsed, dict):
        raise PreviousInstallationError("previous-slot record must be object")
    item = cast(dict[str, object], parsed)
    if item.keys() != {
        "record_type",
        "schema_version",
        "phase",
        "transaction_id",
        "stage_relative_path",
        "wheelhouse_relative_path",
        "selection_generation",
        "prepared_sha256",
        "registry_envelope_sha256",
        "lock_envelope_sha256",
        "native_envelope_sha256",
        "native_payload_sha256",
        "native_revision",
    }:
        raise PreviousInstallationError("unknown or missing previous-slot fields")
    if (
        item["record_type"] != "pds_evergreen_previous_slot_byte_observation"
        or type(item["schema_version"]) is not int
        or item["schema_version"] != 1
        or item["phase"] != "reverified_bytes_not_active_receipt"
    ):
        raise PreviousInstallationError("unsupported previous-slot record identity")
    generation, revision = item["selection_generation"], item["native_revision"]
    if (
        type(generation) is not int
        or type(revision) is not int
        or not 1 <= generation <= 2**53 - 1
        or not 1 <= revision <= 2**53 - 1
    ):
        raise PreviousInstallationError("invalid previous-slot revision or generation")
    observation = PreviousSlotObservation(
        _checked(item["transaction_id"], _ID, "transaction ID"),
        _ref(item["stage_relative_path"], "stage path"),
        _ref(item["wheelhouse_relative_path"], "wheelhouse path"),
        generation,
        _checked(item["prepared_sha256"], _HASH, "prepared digest"),
        _checked(item["registry_envelope_sha256"], _HASH, "registry digest"),
        _checked(item["lock_envelope_sha256"], _HASH, "lock digest"),
        _checked(item["native_envelope_sha256"], _HASH, "native digest"),
        _checked(item["native_payload_sha256"], _HASH, "native payload digest"),
        revision,
    )
    if _encode(observation) != data:
        raise PreviousInstallationError("noncanonical previous-slot record")
    return observation


def observe_previous_slot(
    software_root: Path,
    *,
    classroom_workspace: Path,
    wheelhouse: Path,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None = None,
) -> PreviousSlotObservation:
    """Reverify the currently selected physical slot without executing it.

    The current pointer is NOT a trusted source of historical active state.
    This function only proves the observed software bytes match signed inputs
    at this time. Fresh metadata is required; expired offline provenance needs
    a separately designed authenticated install-continuity protocol.
    """
    try:
        root = _safe_root(software_root, classroom_workspace)
        selected = read_candidate_selection(
            root, classroom_workspace=classroom_workspace
        )
        if selected is None:
            raise PreviousInstallationError("no previous software slot selected")
        stage = root / selected.stage_relative_path
        stage_rel = _relative_child(root, stage)
        wheel_rel = _relative_child(root, wheelhouse)
        if stage_rel != selected.stage_relative_path:
            raise PreviousInstallationError("previous stage path is inconsistent")
        if (
            _digest(prepared_record) != selected.prepared_sha256
            or _digest(evidence_envelope) != selected.native_envelope_sha256
        ):
            raise PreviousInstallationError("prior selection's evidence changed")
        observed = verify_signed_staged_native_evidence(
            stage,
            wheelhouse,
            evidence_envelope=evidence_envelope,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
    except (UpdateJournalError, ActivationSlotError, NativeEvidenceError) as error:
        raise PreviousInstallationError(
            "previous software reauthentication failed"
        ) from error
    if (
        observed.transaction_id != selected.transaction_id
        or observed.stage_root != stage
    ):
        raise PreviousInstallationError("previous selected transaction differs")
    return PreviousSlotObservation(
        selected.transaction_id,
        stage_rel,
        wheel_rel,
        selected.generation,
        _digest(prepared_record),
        _digest(registry_envelope),
        _digest(lock_envelope),
        _digest(evidence_envelope),
        observed.payload_sha256,
        observed.revision,
    )


def capture_previous_slot_record(
    software_root: Path,
    *,
    classroom_workspace: Path,
    wheelhouse: Path,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None = None,
) -> bytes:
    """Create canonical untrusted observation bytes, with NO filesystem writes."""
    return _encode(
        observe_previous_slot(
            software_root,
            classroom_workspace=classroom_workspace,
            wheelhouse=wheelhouse,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            evidence_envelope=evidence_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
    )


def verify_previous_slot_record(
    record: bytes,
    software_root: Path,
    *,
    classroom_workspace: Path,
    wheelhouse: Path,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    expected_record_sha256: str | None = None,
    layout: str | None = None,
) -> VerifiedPreviousSlotBytes:
    """Require exact prior record and reverified stage; NO historical trust claim.

    `expected_record_sha256` must come from independently continuous prior
    state. A hash stored beside this receipt does NOT establish continuity.
    """
    parsed = parse_untrusted_previous_slot_record(record)
    digest = _digest(record)
    if expected_record_sha256 is not None:
        expected = _checked(expected_record_sha256, _HASH, "expected record digest")
        if digest != expected:
            raise PreviousInstallationError(
                "previous-slot expected receipt hash differs"
            )
    current = observe_previous_slot(
        software_root,
        classroom_workspace=classroom_workspace,
        wheelhouse=wheelhouse,
        prepared_record=prepared_record,
        registry_envelope=registry_envelope,
        lock_envelope=lock_envelope,
        evidence_envelope=evidence_envelope,
        trust=trust,
        now=now,
        layout=layout,
    )
    if parsed != current:
        raise PreviousInstallationError(
            "previous-slot record differs from reverified bytes"
        )
    return VerifiedPreviousSlotBytes(current, digest)


__all__ = (
    "PreviousInstallationError",
    "PreviousSlotObservation",
    "VerifiedPreviousSlotBytes",
    "capture_previous_slot_record",
    "observe_previous_slot",
    "parse_untrusted_previous_slot_record",
    "verify_previous_slot_record",
)
