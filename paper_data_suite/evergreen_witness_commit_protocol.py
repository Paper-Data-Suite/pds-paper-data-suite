"""Issue #49 Slice 42: independently approved witness CAS and lost-ACK probe.

No network write endpoint, application launch, receipt persistence, or automatic
recovery is installed. Only a separately operated witness service may call the
explicit commit adapter, using its OWN authenticated approval and checkpoint
store. Neither a local draft nor a successful CAS proves software activation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, cast

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_store import (
    CheckpointStoreError,
    CommittedCheckpoint,
    MonotonicCheckpointStore,
)
from paper_data_suite.evergreen_checkpoint_witness import (
    CheckpointWitnessError,
    CheckpointWitnessTransport,
    issue_witness_challenge,
    verify_witness_statement,
)
from paper_data_suite.evergreen_successor_receipt_draft import (
    WitnessBoundSuccessorDraft,
)

_MAX_REQUEST: Final = 48 * 1024
_MAX_RECEIPT: Final = 16 * 1024
_MAX_GENERATION: Final = 2**53 - 1
_HASH: Final = re.compile(r"[0-9a-f]{64}\Z")
_INSTALL: Final = re.compile(r"[0-9a-f]{32}\Z")
_WITNESS: Final = re.compile(r"[a-z][a-z0-9_-]{2,63}\Z")


class WitnessCommitProtocolError(ValueError):
    """Witness CAS request, service approval, or signed reconciliation refused."""


class IndependentCommitApproval(Protocol):
    """Independent service-owned physical activation/consent approval policy.

    The service MUST authenticate ``context`` independently of all request
    bytes, validate installed executable state using separately protected
    deployment evidence, and require an operator-authorized activation. A
    locally supplied callable or boolean is NOT independent approval.
    """

    def __call__(self, request: WitnessCommitRequest, context: object, /) -> bool: ...


@dataclass(frozen=True, slots=True)
class WitnessCommitRequest:
    """Untrusted canonical proposal. Never a bearer credential or CAS grant."""

    installation_id: str
    witness_id: str
    expected_witness_revision: int
    previous_receipt_bytes: bytes
    successor_receipt_bytes: bytes

    @property
    def predecessor_sha256(self) -> str:
        return hashlib.sha256(self.previous_receipt_bytes).hexdigest()

    @property
    def successor_sha256(self) -> str:
        return hashlib.sha256(self.successor_receipt_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class UnconfirmedWitnessCommit:
    """A witness-side CAS return, NOT an authenticated client ACK or launch."""

    installation_id: str
    previous_witness_revision: int
    committed_witness_revision: int
    successor_generation: int
    successor_sha256: str
    status: str = "SERVICE_CAS_RETURNED_INDEPENDENT_READBACK_REQUIRED"


@dataclass(frozen=True, slots=True)
class SignedCommitHeadObservation:
    """Signed readback only: never resolves local software or pending capsule."""

    installation_id: str
    witness_revision: int
    generation: int
    receipt_sha256: str
    status: str


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validated(request: WitnessCommitRequest) -> tuple[int, int]:
    if (
        not isinstance(request, WitnessCommitRequest)
        or type(request.installation_id) is not str
        or not _INSTALL.fullmatch(request.installation_id)
        or type(request.witness_id) is not str
        or not _WITNESS.fullmatch(request.witness_id)
        or type(request.expected_witness_revision) is not int
        or not 1 <= request.expected_witness_revision < _MAX_GENERATION
        or type(request.previous_receipt_bytes) is not bytes
        or type(request.successor_receipt_bytes) is not bytes
        or not 1 <= len(request.previous_receipt_bytes) <= _MAX_RECEIPT
        or not 1 <= len(request.successor_receipt_bytes) <= _MAX_RECEIPT
    ):
        raise WitnessCommitProtocolError("invalid bounded witness commit request")
    try:
        old = parse_untrusted_active_receipt(request.previous_receipt_bytes)
        new = parse_untrusted_active_receipt(request.successor_receipt_bytes)
    except ActiveReceiptError as error:
        raise WitnessCommitProtocolError("invalid canonical receipt inputs") from error
    if (
        old.generation >= _MAX_GENERATION
        or new.generation != old.generation + 1
        or new.previous_receipt_sha256 != request.predecessor_sha256
        or new.transaction_id == old.transaction_id
        or new.recorded_at < old.recorded_at
        or new.stage_relative_path == old.stage_relative_path
        or new.wheelhouse_relative_path == old.wheelhouse_relative_path
    ):
        raise WitnessCommitProtocolError("non-successor or reused software identity")
    return old.generation, new.generation


def make_witness_commit_request(
    draft: WitnessBoundSuccessorDraft,
    *,
    installation_id: str,
    witness_id: str,
    previous_receipt_bytes: bytes,
) -> WitnessCommitRequest:
    """Bind a Slice-41 draft to one witness head, with NO authorization."""
    if (
        not isinstance(draft, WitnessBoundSuccessorDraft)
        or type(draft.receipt_bytes) is not bytes
        or type(previous_receipt_bytes) is not bytes
        or _sha(draft.receipt_bytes) != draft.proposed_receipt_sha256
        or _sha(previous_receipt_bytes) != draft.previous_receipt_sha256
    ):
        raise WitnessCommitProtocolError("successor draft does not bind exact bytes")
    request = WitnessCommitRequest(
        installation_id,
        witness_id,
        draft.expected_witness_revision,
        previous_receipt_bytes,
        draft.receipt_bytes,
    )
    prior_generation, next_generation = _validated(request)
    proposed = parse_untrusted_active_receipt(draft.receipt_bytes)
    if (
        draft.previous_generation != prior_generation
        or draft.proposed_generation != next_generation
        or draft.transaction_id != proposed.transaction_id
    ):
        raise WitnessCommitProtocolError("draft generation/transaction mismatch")
    return request


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WitnessCommitProtocolError("duplicate witness request key")
        result[key] = value
    return result


def serialize_witness_commit_request(request: WitnessCommitRequest) -> bytes:
    """Canonical bounded transport syntax, NOT authentication or permission."""
    _validated(request)
    raw = json.dumps(
        {
            "record_type": "pds_witness_successor_commit_request",
            "schema_version": 1,
            "installation_id": request.installation_id,
            "witness_id": request.witness_id,
            "expected_witness_revision": request.expected_witness_revision,
            "predecessor_sha256": request.predecessor_sha256,
            "successor_sha256": request.successor_sha256,
            "predecessor_b64": base64.b64encode(request.previous_receipt_bytes).decode(
                "ascii"
            ),
            "successor_b64": base64.b64encode(request.successor_receipt_bytes).decode(
                "ascii"
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    if len(raw) > _MAX_REQUEST:
        raise WitnessCommitProtocolError("witness request exceeds size bound")
    return raw


def _decode(value: object) -> bytes:
    if type(value) is not str or not 1 <= len(value) <= 4 * ((_MAX_RECEIPT + 2) // 3):
        raise WitnessCommitProtocolError("invalid receipt base64 length")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise WitnessCommitProtocolError("invalid receipt base64") from error
    if (
        not 1 <= len(result) <= _MAX_RECEIPT
        or base64.b64encode(result).decode("ascii") != value
    ):
        raise WitnessCommitProtocolError("noncanonical receipt base64")
    return result


def parse_witness_commit_request(raw: bytes) -> WitnessCommitRequest:
    """Strict client proposal parser; external service still MUST authorize."""
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_REQUEST:
        raise WitnessCommitProtocolError("invalid witness request size")
    try:
        document: object = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except WitnessCommitProtocolError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise WitnessCommitProtocolError("malformed witness request") from error
    if not isinstance(document, dict):
        raise WitnessCommitProtocolError("witness request must be an object")
    data = cast(dict[str, object], document)
    if (
        data.keys()
        != {
            "record_type",
            "schema_version",
            "installation_id",
            "witness_id",
            "expected_witness_revision",
            "predecessor_sha256",
            "successor_sha256",
            "predecessor_b64",
            "successor_b64",
        }
        or data["record_type"] != "pds_witness_successor_commit_request"
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise WitnessCommitProtocolError("unsupported witness request schema")
    request = WitnessCommitRequest(
        cast(str, data["installation_id"]),
        cast(str, data["witness_id"]),
        cast(int, data["expected_witness_revision"]),
        _decode(data["predecessor_b64"]),
        _decode(data["successor_b64"]),
    )
    _validated(request)
    prior_hash = data["predecessor_sha256"]
    next_hash = data["successor_sha256"]
    if (
        type(prior_hash) is not str
        or type(next_hash) is not str
        or not _HASH.fullmatch(prior_hash)
        or not _HASH.fullmatch(next_hash)
        or prior_hash != request.predecessor_sha256
        or next_hash != request.successor_sha256
        or serialize_witness_commit_request(request) != raw
    ):
        raise WitnessCommitProtocolError("request digest or canonical encoding differs")
    return request


def _signed_head(
    request: WitnessCommitRequest,
    transport: CheckpointWitnessTransport,
    *,
    pinned_public_key: bytes,
    now: datetime,
    minimum_revision: int | None = None,
) -> SignedCommitHeadObservation:
    """Read a SINGLE fresh signed challenge and compare to BOTH exact receipts.

    Do not issue two network requests: the witness forbids reused challenges.
    A transport failure or unknown/forged response is unresolved, NOT a safe
    old-head observation. The same signed reply can be verified against either
    receipt without replaying a challenge to the witness service.
    """
    _validated(request)
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
        or type(pinned_public_key) is not bytes
        or len(pinned_public_key) != 32
        or not callable(transport)
    ):
        raise WitnessCommitProtocolError("missing trusted witness readback inputs")
    try:
        challenge = issue_witness_challenge(
            installation_id=request.installation_id, now=now
        )
        reply = transport(challenge.bytes)
        for content, label in (
            (
                request.successor_receipt_bytes,
                "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED",
            ),
            (
                request.previous_receipt_bytes,
                "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED",
            ),
        ):
            try:
                observed = verify_witness_statement(
                    challenge=challenge,
                    signed_reply=reply,
                    receipt_bytes=content,
                    pinned_public_key=pinned_public_key,
                    expected_witness_id=request.witness_id,
                    now=now,
                    minimum_witness_revision=minimum_revision,
                )
            except CheckpointWitnessError:
                continue
            if label.startswith("SUCCESSOR"):
                if observed.witness_revision != request.expected_witness_revision + 1:
                    raise WitnessCommitProtocolError(
                        "unexpected successor witness revision"
                    )
            elif observed.witness_revision != request.expected_witness_revision:
                raise WitnessCommitProtocolError(
                    "stale or unexpected predecessor revision"
                )
            return SignedCommitHeadObservation(
                request.installation_id,
                observed.witness_revision,
                observed.receipt.receipt.generation,
                observed.receipt.digest,
                label,
            )
    except CheckpointWitnessError as error:
        raise WitnessCommitProtocolError(
            "signed witness readback unavailable"
        ) from error
    except Exception as error:
        if isinstance(error, WitnessCommitProtocolError):
            raise
        raise WitnessCommitProtocolError(
            "signed witness readback unavailable"
        ) from error
    raise WitnessCommitProtocolError(
        "unrecognized, divergent or unauthenticated head; manual reconciliation"
    )


def inspect_uncertain_witness_commit(
    request: WitnessCommitRequest,
    *,
    witness_transport: CheckpointWitnessTransport,
    pinned_public_key: bytes,
    now: datetime,
    minimum_witness_revision: int | None = None,
) -> SignedCommitHeadObservation:
    """After lost ACK, classify signed head; NEVER retry commit or rollback.

    A prior-head observation is NOT proof no request remains in-flight; an
    operator must separately fence pending writes before any offline rollback.
    A confirmed successor requires forward reconciliation of local receipt,
    pointer and physical installed software. No local state is modified.
    """
    return _signed_head(
        request,
        witness_transport,
        pinned_public_key=pinned_public_key,
        now=now,
        minimum_revision=minimum_witness_revision,
    )


def commit_independently_approved_successor(
    request: WitnessCommitRequest,
    *,
    store: MonotonicCheckpointStore,
    service_context: object,
    independently_approve: IndependentCommitApproval,
    witness_transport: CheckpointWitnessTransport,
    pinned_public_key: bytes,
    now: datetime,
) -> UnconfirmedWitnessCommit:
    """SERVICE-SIDE ONLY: explicit authorized CAS; never a teacher CLI API.

    ``independently_approve`` MUST be owned by a separately administered
    witness and certify protected activation evidence + explicit consent.
    ``service_context`` MUST be authenticated by that service. Production may
    NEVER construct either from teacher-local strings, locally saved files,
    receipt drafts or caller-supplied public keys. This adapter does not expose
    a write URL, persist a local receipt, clear recovery, or authorize launch.
    """
    prior_generation, next_generation = _validated(request)
    if not isinstance(store, MonotonicCheckpointStore) or not callable(
        independently_approve
    ):
        raise WitnessCommitProtocolError("missing independently managed service")
    before = _signed_head(
        request,
        witness_transport,
        pinned_public_key=pinned_public_key,
        now=now,
        minimum_revision=request.expected_witness_revision,
    )
    if (
        before.status != "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED"
        or before.generation != prior_generation
    ):
        raise WitnessCommitProtocolError("predecessor checkpoint CAS not current")
    try:
        authorized = independently_approve(request, service_context)
    except Exception as error:
        raise WitnessCommitProtocolError(
            "independent deployment approval failed"
        ) from error
    if authorized is not True:
        raise WitnessCommitProtocolError("independent deployment approval refused")
    try:
        outcome: CommittedCheckpoint = store.commit_receipt(
            request.installation_id,
            request.successor_receipt_bytes,
            context=service_context,
        )
    except CheckpointStoreError as error:
        # Even a caught exception after a write may have an uncertain durable
        # outcome. The caller MUST perform a fresh signed readback and never
        # assume that a failed local return implies safe rollback.
        raise WitnessCommitProtocolError(
            "witness CAS refused or outcome ambiguous; signed readback required"
        ) from error
    if (
        outcome.installation_id != request.installation_id
        or outcome.revision != request.expected_witness_revision + 1
        or outcome.generation != next_generation
        or outcome.receipt_sha256 != request.successor_sha256
        or outcome.previous_sha256 != request.predecessor_sha256
    ):
        raise WitnessCommitProtocolError(
            "unexpected witness CAS return; readback required"
        )
    return UnconfirmedWitnessCommit(
        request.installation_id,
        request.expected_witness_revision,
        outcome.revision,
        next_generation,
        request.successor_sha256,
    )


__all__ = (
    "IndependentCommitApproval",
    "SignedCommitHeadObservation",
    "UnconfirmedWitnessCommit",
    "WitnessCommitProtocolError",
    "WitnessCommitRequest",
    "commit_independently_approved_successor",
    "inspect_uncertain_witness_commit",
    "make_witness_commit_request",
    "parse_witness_commit_request",
    "serialize_witness_commit_request",
)
