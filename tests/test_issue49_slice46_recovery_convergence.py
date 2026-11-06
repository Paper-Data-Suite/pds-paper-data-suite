"""Slice 46: operator-only convergence of bounded service/local recovery claims."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_local_receipt_recovery import ForwardRecoveryObservation
from paper_data_suite.evergreen_recovery_convergence import (
    RecoveryConvergenceError,
    compare_recovery_convergence,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)

NOW = datetime(2026, 10, 21, 19, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
SERVICE_AUTH = "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
LOCAL_AUTH = "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"
PRIOR_STATUS = "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED"
NEXT_STATUS = "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
STOPPED_PRIOR = "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"
STOPPED_NEXT = "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidate(tx: str, stage: str, wheels: str) -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        tx,
        1,
        stage,
        wheels,
        "3" * 64,
        "4" * 64,
        (("quillan", "5" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )


@pytest.fixture
def ready() -> dict[str, Any]:
    previous = make_untrusted_active_receipt(
        candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"prior-prepared",
        registry_envelope=b"prior-registry",
        lock_envelope=b"prior-lock",
        native_envelope=b"prior-native",
        generation=1,
        recorded_at=NOW - timedelta(minutes=2),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"next-prepared",
        registry_envelope=b"next-registry",
        lock_envelope=b"next-lock",
        native_envelope=b"next-native",
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, sha(previous)),
    )
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, previous, successor)
    request_hash = sha(serialize_witness_commit_request(request))
    service = WitnessWriterQuiescenceState(
        INSTALL, request_hash, STOPPED_PRIOR, 1, sha(previous)
    )
    local = ForwardRecoveryObservation(NEXT, 1, 1, sha(previous), PRIOR_STATUS)
    return {
        "request": request,
        "service": service,
        "local": local,
        "prior": previous,
        "successor": successor,
    }


def compare(ready: dict[str, Any], **changes: Any) -> Any:
    args: dict[str, Any] = {
        "request": ready["request"],
        "service": ready["service"],
        "local": ready["local"],
    }
    return compare_recovery_convergence(**{**args, **changes})


def test_old_head_agreement_is_not_rollback_permission(ready: dict[str, Any]) -> None:
    result = compare(ready)
    assert result.finding == "MATCHED_PRIOR_HEAD_REVIEW_STILL_REQUIRED"
    assert "verify" in result.next_action.lower()
    assert result.observed_witness_revision == 1
    assert result.observed_generation == 1
    assert result.transaction_id == NEXT
    assert result.authority == SERVICE_AUTH
    assert not hasattr(result, "rollback") and not hasattr(result, "launch")


def test_new_head_agreement_requires_forward_reconciliation(
    ready: dict[str, Any],
) -> None:
    request = ready["request"]
    service = replace(
        ready["service"],
        status=STOPPED_NEXT,
        signed_revision=2,
        signed_head_sha256=request.successor_sha256,
    )
    local = replace(
        ready["local"],
        status=NEXT_STATUS,
        witness_revision=2,
        generation=2,
        observed_receipt_sha256=request.successor_sha256,
    )
    result = compare(ready, service=service, local=local)
    assert result.finding == "MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED"
    assert result.observed_generation == 2
    assert result.successor_sha256 == request.successor_sha256
    assert result.authority == SERVICE_AUTH


@pytest.mark.parametrize(
    "state",
    [
        "ADMITTED_NOT_DISPATCHED",
        "CAS_MAY_BE_IN_FLIGHT",
        "STOP_REQUESTED_NO_DISPATCH",
        "STOP_REQUESTED_MAY_BE_IN_FLIGHT",
    ],
)
def test_unsealed_gate_never_authorizes_recovery(
    ready: dict[str, Any], state: str
) -> None:
    service = replace(
        ready["service"],
        status=state,
        signed_revision=None,
        signed_head_sha256=None,
    )
    result = compare(ready, service=service)
    assert result.finding == "WRITER_NOT_QUIESCED_HEAD_ONLY_OBSERVED"
    assert "stop" in result.next_action
    assert result.authority == SERVICE_AUTH


def test_unsealed_gate_with_successor_head_is_still_pending(
    ready: dict[str, Any],
) -> None:
    service = replace(
        ready["service"],
        status="STOP_REQUESTED_MAY_BE_IN_FLIGHT",
        signed_revision=None,
        signed_head_sha256=None,
    )
    local = replace(
        ready["local"],
        status=NEXT_STATUS,
        witness_revision=2,
        generation=2,
        observed_receipt_sha256=ready["request"].successor_sha256,
    )
    assert compare(ready, service=service, local=local).finding == (
        "WRITER_NOT_QUIESCED_HEAD_ONLY_OBSERVED"
    )


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("installation_id", "d" * 32),
        ("request_sha256", "0" * 64),
        ("authority", "CAN_ACTIVATE"),
        ("status", "FUTURE_READY_TO_LAUNCH"),
        ("signed_revision", True),
        ("signed_revision", 2),
        ("signed_head_sha256", "0" * 64),
    ],
)
def test_invalid_service_claim_refused(
    ready: dict[str, Any], field: str, wrong: Any
) -> None:
    service = replace(ready["service"], **{field: wrong})
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, service=service)


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("transaction_id", "d" * 32),
        ("authority", "CAN_ROLLBACK"),
        ("status", "ACTIVATED"),
        ("witness_revision", True),
        ("witness_revision", 2),
        ("generation", True),
        ("generation", 2),
        ("observed_receipt_sha256", "f" * 64),
    ],
)
def test_invalid_local_observation_refused(
    ready: dict[str, Any], field: str, wrong: Any
) -> None:
    local = replace(ready["local"], **{field: wrong})
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, local=local)


def test_service_prior_local_successor_is_conflict(ready: dict[str, Any]) -> None:
    req = ready["request"]
    next_local = replace(
        ready["local"],
        status=NEXT_STATUS,
        witness_revision=2,
        generation=2,
        observed_receipt_sha256=req.successor_sha256,
    )
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, local=next_local)


def test_service_successor_local_prior_is_conflict(ready: dict[str, Any]) -> None:
    next_service = replace(
        ready["service"],
        status=STOPPED_NEXT,
        signed_revision=2,
        signed_head_sha256=ready["request"].successor_sha256,
    )
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, service=next_service)


def test_pending_gate_cannot_supply_bogus_signed_head(ready: dict[str, Any]) -> None:
    unfinished = replace(ready["service"], status="ADMITTED_NOT_DISPATCHED")
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, service=unfinished)


def test_changed_successor_request_rejected_as_unbound(ready: dict[str, Any]) -> None:
    request = replace(ready["request"], witness_id="another_witness")
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, request=request)


def test_noncanonical_or_wrong_request_type_fails(ready: dict[str, Any]) -> None:
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, request=None)
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, request=replace(ready["request"], expected_witness_revision=0))


def test_non_object_claim_types_are_rejected(ready: dict[str, Any]) -> None:
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, local={"status": PRIOR_STATUS})
    with pytest.raises(RecoveryConvergenceError):
        compare(ready, service={"status": STOPPED_PRIOR})


def test_inspection_never_launches_writes_or_communicates(
    ready: dict[str, Any],
) -> None:
    with (
        patch("subprocess.run", side_effect=AssertionError("no execution")),
        patch("socket.create_connection", side_effect=AssertionError("no network")),
        patch("pathlib.Path.write_bytes", side_effect=AssertionError("no writes")),
    ):
        result = compare(ready)
    assert result.authority == SERVICE_AUTH
    assert ready["local"].authority == LOCAL_AUTH


def test_result_is_repeatable_and_has_no_authority(ready: dict[str, Any]) -> None:
    first = compare(ready)
    second = compare(ready)
    assert first == second
    assert first.request_sha256 == ready["service"].request_sha256
    assert first.predecessor_sha256 == sha(ready["prior"])
    assert first.successor_sha256 == sha(ready["successor"])
