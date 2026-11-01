"""Issue #49 Slice 118: read-only interrupted checkpoint-CAS recovery classification.

All checkpoint, journal, and proposal inputs are locally forgeable. This pure
classifier NEVER establishes OS custody, changes files, clears an intent,
resumes an installer, publishes a receipt, or grants launch authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, cast

from paper_data_suite.evergreen_windows_installer_checkpoint_cas import (
    CheckpointCasProposal,
    InstallerCheckpointCasError,
    parse_claimed_checkpoint,
)

_NO_AUTHORITY: Final = (
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
)
_PREPARED: Final = "INTENT_PREPARED"
_REPLACED: Final = "CHECKPOINT_REPLACED_CLAIMED"
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_MAX: Final = 4096
_FIELDS: Final = frozenset(
    {
        "schema",
        "phase",
        "transaction_id",
        "request_sha256",
        "previous_checkpoint_sha256",
        "previous_generation",
        "proposed_checkpoint_sha256",
        "proposed_generation",
    }
)


class InstallerCheckpointRecoveryError(ValueError):
    """Malformed journal or inconsistent interrupted-checkpoint observation."""


@dataclass(frozen=True, slots=True)
class CheckpointRecoveryObservation:
    """Read-only classification; requires a separate native recovery custodian."""

    status: str
    claimed_journal_phase: str
    claimed_current_generation: int
    expected_previous_sha256: str
    proposed_checkpoint_sha256: str
    proposal_digest: str
    native_custody_verified: bool = False
    durable_journal_verified: bool = False
    independent_antirollback_verified: bool = False
    permitted_to_discard_journal: bool = False
    permitted_to_retry_replacement: bool = False
    permitted_to_publish_receipt: bool = False
    permitted_to_activate_or_launch: bool = False
    authority: str = _NO_AUTHORITY


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise InstallerCheckpointRecoveryError("duplicate journal JSON key")
        obj[key] = value
    return obj


def _canon(value: dict[str, object]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def parse_claimed_checkpoint_journal(raw: bytes) -> dict[str, object]:
    """Strictly validate a locally supplied journal, not its OS provenance."""
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX:
        raise InstallerCheckpointRecoveryError("invalid journal size")
    try:
        decoded: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except InstallerCheckpointRecoveryError:
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise InstallerCheckpointRecoveryError("invalid journal JSON") from error
    if not isinstance(decoded, dict) or set(decoded) != _FIELDS:
        raise InstallerCheckpointRecoveryError("unexpected journal fields")
    obj = cast(dict[str, object], decoded)
    if type(obj["schema"]) is not int or obj["schema"] != 1:
        raise InstallerCheckpointRecoveryError("unsupported journal schema")
    if obj["phase"] not in (_PREPARED, _REPLACED) or type(obj["phase"]) is not str:
        raise InstallerCheckpointRecoveryError("unrecognized journal phase")
    if (
        type(obj["transaction_id"]) is not str
        or _TX.fullmatch(obj["transaction_id"]) is None
    ):
        raise InstallerCheckpointRecoveryError("invalid transaction identity")
    if obj["transaction_id"] == "0" * 32:
        raise InstallerCheckpointRecoveryError("zero transaction identity")
    for key in (
        "request_sha256",
        "previous_checkpoint_sha256",
        "proposed_checkpoint_sha256",
    ):
        val = obj[key]
        if type(val) is not str or _SHA.fullmatch(val) is None or val == "0" * 64:
            raise InstallerCheckpointRecoveryError("invalid journal digest")
    a, b = obj["previous_generation"], obj["proposed_generation"]
    if type(a) is not int or type(b) is not int or a != 0 or b != 1:
        raise InstallerCheckpointRecoveryError(
            "invalid new-install generation transition"
        )
    if _canon(obj) != raw:
        raise InstallerCheckpointRecoveryError("journal bytes are not canonical")
    return obj


def _checked_proposal(
    proposal: CheckpointCasProposal, previous: bytes
) -> tuple[dict[str, object], dict[str, object]]:
    if (
        type(proposal) is not CheckpointCasProposal
        or proposal.status != ("PROPOSED_PROTECTED_CHECKPOINT_CAS_NOT_APPLIED")
        or proposal.authority != _NO_AUTHORITY
    ):
        raise InstallerCheckpointRecoveryError("invalid checkpoint proposal identity")
    if any(
        type(getattr(proposal, key)) is not bool or getattr(proposal, key)
        for key in (
            "protected_baseline_authenticated",
            "atomic_write_performed",
            "service_or_admin_authenticated",
            "authorized_to_provision",
            "authorized_to_register_service",
            "authorized_to_publish_receipt",
            "authorized_to_activate_or_launch",
        )
    ):
        raise InstallerCheckpointRecoveryError("unearned checkpoint proposal authority")
    try:
        old = parse_claimed_checkpoint(previous)
        new = parse_claimed_checkpoint(proposal.proposed_record_bytes)
    except (InstallerCheckpointCasError, TypeError, ValueError) as error:
        raise InstallerCheckpointRecoveryError("invalid checkpoint record") from error
    if (
        old["generation"] != 0
        or new["generation"] != 1
        or proposal.expected_generation != 0
        or proposal.proposed_generation != 1
        or hashlib.sha256(previous).hexdigest() != proposal.expected_previous_sha256
        or hashlib.sha256(proposal.proposed_record_bytes).hexdigest()
        != proposal.proposed_record_sha256
        or new["last_request_sha256"] != proposal.request_sha256
        or new["trust_policy_sha256"] != old["trust_policy_sha256"]
        or new["trust_policy_revision"] != old["trust_policy_revision"]
        or type(new["last_transaction_id"]) is not str
    ):
        raise InstallerCheckpointRecoveryError("checkpoint proposal contradicts bytes")
    return old, new


def prepare_claimed_checkpoint_journal(
    proposal: CheckpointCasProposal, *, claimed_previous_bytes: bytes
) -> bytes:
    """Prepare INTENT bytes only; NEVER write a journal or acquire a lock."""
    _, new = _checked_proposal(proposal, claimed_previous_bytes)
    result: dict[str, object] = {
        "schema": 1,
        "phase": _PREPARED,
        "transaction_id": new["last_transaction_id"],
        "request_sha256": proposal.request_sha256,
        "previous_checkpoint_sha256": proposal.expected_previous_sha256,
        "previous_generation": 0,
        "proposed_checkpoint_sha256": proposal.proposed_record_sha256,
        "proposed_generation": 1,
    }
    raw = _canon(result)
    parse_claimed_checkpoint_journal(raw)
    return raw


def classify_claimed_checkpoint_recovery(
    proposal: CheckpointCasProposal,
    *,
    claimed_previous_bytes: bytes,
    claimed_current_bytes: bytes,
    claimed_journal_bytes: bytes,
) -> CheckpointRecoveryObservation:
    """Classify only; every non-refusal needs fresh native custody proofs.

    PREPARED+old requires independent revalidation before replacement.
    PREPARED+new means replacement may have occurred before journal update.
    REPLACED+new still requires independent commit/receipt evidence.
    REPLACED+old or any third state is inconsistent, not a recovery permit.
    """
    _checked_proposal(proposal, claimed_previous_bytes)
    journal = parse_claimed_checkpoint_journal(claimed_journal_bytes)
    expected = parse_claimed_checkpoint_journal(
        prepare_claimed_checkpoint_journal(
            proposal, claimed_previous_bytes=claimed_previous_bytes
        )
    )
    if any(journal[k] != expected[k] for k in _FIELDS if k != "phase"):
        raise InstallerCheckpointRecoveryError(
            "journal disagrees with exact CAS proposal"
        )
    try:
        current = parse_claimed_checkpoint(claimed_current_bytes)
    except (InstallerCheckpointCasError, TypeError) as error:
        raise InstallerCheckpointRecoveryError(
            "invalid observed current checkpoint"
        ) from error
    observed_digest = hashlib.sha256(claimed_current_bytes).hexdigest()
    phase = cast(str, journal["phase"])
    if observed_digest == proposal.expected_previous_sha256 and phase == _PREPARED:
        status = "OLD_CHECKPOINT_REQUIRES_NATIVE_REVALIDATION_BEFORE_CAS"
    elif observed_digest == proposal.proposed_record_sha256:
        status = (
            "REPLACEMENT_OBSERVED_JOURNAL_NOT_FINALIZED"
            if phase == _PREPARED
            else "REPLACEMENT_CLAIMED_REQUIRES_NATIVE_COMMIT_ATTESTATION"
        )
    else:
        raise InstallerCheckpointRecoveryError(
            "journal and current checkpoint are inconsistent: refuse recovery"
        )
    return CheckpointRecoveryObservation(
        status=status,
        claimed_journal_phase=phase,
        claimed_current_generation=cast(int, current["generation"]),
        expected_previous_sha256=proposal.expected_previous_sha256,
        proposed_checkpoint_sha256=proposal.proposed_record_sha256,
        proposal_digest=hashlib.sha256(proposal.proposed_record_bytes).hexdigest(),
    )


__all__ = (
    "CheckpointRecoveryObservation",
    "InstallerCheckpointRecoveryError",
    "classify_claimed_checkpoint_recovery",
    "parse_claimed_checkpoint_journal",
    "prepare_claimed_checkpoint_journal",
)
