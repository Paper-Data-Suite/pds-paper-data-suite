"""Slice 48: successor recovery correlation never becomes activation authority."""

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
from paper_data_suite.evergreen_forward_byte_requalification import (
    ObservedForwardSuccessorBytes,
)
from paper_data_suite.evergreen_forward_recovery_handoff import (
    ForwardRecoveryHandoffError,
    prepare_forward_recovery_handoff,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_recovery_convergence import RecoveryConvergenceFinding
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)

NOW = datetime(2026, 10, 21, 21, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
SERVICE_AUTH = "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
BYTES_AUTH = "NO_LAUNCH_ROLLBACK_OR_RECEIPT_COMMIT_AUTHORITY"


def digest(raw: bytes) -> str:
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
    prior = make_untrusted_active_receipt(
        candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"old prepared",
        registry_envelope=b"old registry",
        lock_envelope=b"old lock",
        native_envelope=b"old native",
        generation=1,
        recorded_at=NOW - timedelta(minutes=2),
        previous=None,
    )
    new = make_untrusted_active_receipt(
        candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"next prepared",
        registry_envelope=b"next registry",
        lock_envelope=b"next lock",
        native_envelope=b"next native",
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, digest(prior)),
    )
    request = WitnessCommitRequest(INSTALL, "independent_witness", 1, prior, new)
    request_digest = digest(serialize_witness_commit_request(request))
    convergence = RecoveryConvergenceFinding(
        INSTALL,
        NEXT,
        request_digest,
        digest(prior),
        digest(new),
        2,
        2,
        "MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED",
        "Verify protected successor software and reconcile active receipt forward",
    )
    # These are typed test observations; not a substitute for a real signed
    # readback or physical signed wheel / pip / native-file verification.
    requalified = ObservedForwardSuccessorBytes(
        NEXT,
        2,
        digest(new),
        2,
        "4" * 64,
        "3" * 64,
        "candidate/two",
    )
    service = WitnessWriterQuiescenceState(
        INSTALL,
        request_digest,
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        2,
        digest(new),
    )
    return {
        "request": request,
        "convergence": convergence,
        "requalified": requalified,
        "service": service,
    }


def handoff(ready: dict[str, Any], **changes: Any) -> Any:
    kwargs: dict[str, Any] = {
        "request": ready["request"],
        "convergence": ready["convergence"],
        "requalified": ready["requalified"],
        "service": ready["service"],
    }
    return prepare_forward_recovery_handoff(**{**kwargs, **changes})


def test_consistent_successor_generates_only_operator_handoff(
    ready: dict[str, Any],
) -> None:
    result = handoff(ready)
    assert result.installation_id == INSTALL
    assert result.transaction_id == NEXT
    assert result.generation == 2
    assert result.witness_revision == 2
    assert result.successor_receipt_sha256 == ready["request"].successor_sha256
    assert result.request_sha256 == ready["service"].request_sha256
    assert result.stage_relative_path == "candidate/two"
    assert result.wheelhouse_relative_path == "candidate/wheels"
    assert result.pip_inventory_sha256 == "4" * 64
    assert result.native_payload_sha256 == "3" * 64
    assert result.status == (
        "FORWARD_HANDOFF_REQUIRES_PROTECTED_ACTIVATION_RECONCILIATION"
    )
    assert result.authority == "NO_LAUNCH_ROLLBACK_RECEIPT_OR_SWITCH_AUTHORITY"
    for forbidden in ("launch", "activate", "rollback", "commit", "switch"):
        assert not hasattr(result, forbidden)
    assert result == handoff(ready)


@pytest.mark.parametrize(
    "field, value",
    [
        ("finding", "MATCHED_PRIOR_HEAD_REVIEW_STILL_REQUIRED"),
        ("authority", "CAN_ACTIVATE"),
        ("installation_id", "d" * 32),
        ("transaction_id", "d" * 32),
        ("request_sha256", "f" * 64),
        ("predecessor_sha256", "f" * 64),
        ("successor_sha256", "f" * 64),
        ("observed_witness_revision", 1),
        ("observed_witness_revision", True),
        ("observed_generation", 1),
        ("observed_generation", True),
    ],
)
def test_convergence_mismatch_refused(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    convergence = replace(ready["convergence"], **{field: value})
    with pytest.raises(ForwardRecoveryHandoffError):
        handoff(ready, convergence=convergence)


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "CAS_MAY_BE_IN_FLIGHT"),
        ("status", "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"),
        ("authority", "CAN_ROLLBACK"),
        ("installation_id", "d" * 32),
        ("request_sha256", "0" * 64),
        ("signed_revision", None),
        ("signed_revision", 1),
        ("signed_head_sha256", None),
        ("signed_head_sha256", "0" * 64),
    ],
)
def test_service_gate_mismatch_refused(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    service = replace(ready["service"], **{field: value})
    with pytest.raises(ForwardRecoveryHandoffError):
        handoff(ready, service=service)


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "PHYSICAL_ACTIVATION_CONFIRMED"),
        ("authority", "CAN_COMMIT"),
        ("transaction_id", "d" * 32),
        ("generation", 1),
        ("generation", True),
        ("successor_receipt_sha256", "0" * 64),
        ("witness_revision", 1),
        ("witness_revision", True),
        ("stage_relative_path", "prior/one"),
        ("pip_inventory_sha256", "f" * 64),
        ("native_payload_sha256", "f" * 64),
    ],
)
def test_byte_observation_mismatch_refused(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    requalified = replace(ready["requalified"], **{field: value})
    with pytest.raises(ForwardRecoveryHandoffError):
        handoff(ready, requalified=requalified)


def test_wrong_witness_identity_changes_request_digest(ready: dict[str, Any]) -> None:
    request = replace(ready["request"], witness_id="another_witness")
    with pytest.raises(ForwardRecoveryHandoffError):
        handoff(ready, request=request)


def test_invalid_request_and_objects_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(ForwardRecoveryHandoffError):
        handoff(ready, request=None)
    with pytest.raises(ForwardRecoveryHandoffError):
        handoff(ready, request=replace(ready["request"], expected_witness_revision=0))
    with pytest.raises(ForwardRecoveryHandoffError):
        handoff(ready, convergence={"finding": "successor"})
    with pytest.raises(ForwardRecoveryHandoffError):
        handoff(ready, requalified=None)
    with pytest.raises(ForwardRecoveryHandoffError):
        handoff(ready, service=True)


def test_pure_function_never_writes_executes_or_reaches_network(
    ready: dict[str, Any],
) -> None:
    with (
        patch("subprocess.run", side_effect=AssertionError("subprocess")),
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("pathlib.Path.write_bytes", side_effect=AssertionError("filesystem")),
    ):
        result = handoff(ready)
    assert result.authority == "NO_LAUNCH_ROLLBACK_RECEIPT_OR_SWITCH_AUTHORITY"
    assert ready["service"].authority == SERVICE_AUTH
    assert ready["requalified"].authority == BYTES_AUTH


def test_swapped_pip_and_native_digests_are_refused(ready: dict[str, Any]) -> None:
    requalified = replace(
        ready["requalified"],
        pip_inventory_sha256=ready["requalified"].native_payload_sha256,
        native_payload_sha256=ready["requalified"].pip_inventory_sha256,
    )
    with pytest.raises(ForwardRecoveryHandoffError, match="disagree"):
        handoff(ready, requalified=requalified)
