"""Slice 76: plan-bound read-only correlation; no bearer activation rights.

The pinned recovery function is replaced by a synthetic result for boundary
unit tests. Slice 50-56 tests independently verify real signatures, mTLS,
local signed-head verification and signed installed-wheel/native-byte audits.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_attested_forward_handoff import AttestedForwardHandoff
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_forward_recovery_handoff import ForwardRecoveryHandoff
from paper_data_suite.evergreen_fresh_attested_recovery import (
    FreshAttestedRecoveryObservation,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_pinned_remote_recovery import (
    PinnedRemoteRecoveryError,
    PinnedRemoteRecoveryObservation,
)
from paper_data_suite.evergreen_plan_forward_recovery import (
    PlanForwardRecoveryError,
    inspect_plan_bound_forward_recovery,
)
from paper_data_suite.evergreen_plan_inert_selection import PlanPendingInertSelection
from paper_data_suite.evergreen_plan_service_admission import (
    PlanSuccessorServiceAdmission,
)
from paper_data_suite.evergreen_plan_service_dispatch import (
    PlanSuccessorServiceSignedRecovery,
)
from paper_data_suite.evergreen_plan_successor_draft import PlanSuccessorDraftReview
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
from paper_data_suite.evergreen_recovery_observation_https import (
    ProvisionedRecoveryObservationHttpsClient,
)
from paper_data_suite.evergreen_service_recovery_attestation import (
    VerifiedRecoveryServiceAttestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)

NOW = datetime(2026, 10, 26, 23, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"


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
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    old = make_untrusted_active_receipt(
        candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"old-p",
        registry_envelope=b"old-r",
        lock_envelope=b"old-l",
        native_envelope=b"old-n",
        generation=1,
        recorded_at=NOW - timedelta(minutes=3),
        previous=None,
    )
    new = make_untrusted_active_receipt(
        candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"new-p",
        registry_envelope=b"new-r",
        lock_envelope=b"new-l",
        native_envelope=b"new-n",
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, sha(old)),
    )
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, old, new)
    raw = serialize_witness_commit_request(request)
    review = PlanSuccessorDraftReview(
        NEXT, INSTALL, 2, 1, 2, 1, sha(old), sha(new), sha(raw), raw
    )
    admission = PlanSuccessorServiceAdmission(
        INSTALL, NEXT, sha(raw), sha(old), sha(new), 1, 2, 1
    )
    signed = PlanSuccessorServiceSignedRecovery(
        INSTALL,
        NEXT,
        sha(raw),
        2,
        sha(new),
        "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED",
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        "SIGNED_SUCCESSOR_REQUIRES_PROTECTED_FORWARD_RECOVERY",
    )
    selected = PlanPendingInertSelection(NEXT, 2, 1, 2, 1, sha(old), "candidate/two")
    service = VerifiedRecoveryServiceAttestation(
        INSTALL, NEXT, sha(raw), sha(new), 2, 2, NOW, NOW + timedelta(seconds=60)
    )
    forward = ForwardRecoveryHandoff(
        INSTALL,
        NEXT,
        sha(raw),
        sha(new),
        2,
        2,
        "candidate/two",
        "candidate/wheels",
        "4" * 64,
        "3" * 64,
    )
    signed_handoff = AttestedForwardHandoff(service, forward, "9" * 64)
    fresh = FreshAttestedRecoveryObservation(signed_handoff)
    remote = PinnedRemoteRecoveryObservation(fresh, "9" * 64)
    calls: list[dict[str, Any]] = []

    def inspect(*args: Any, **kwargs: Any) -> PinnedRemoteRecoveryObservation:
        calls.append(kwargs)
        return remote

    import paper_data_suite.evergreen_plan_forward_recovery as module

    monkeypatch.setattr(module, "inspect_pinned_remote_forward_recovery", inspect)
    # Bypass constructors ONLY in synthetic boundary tests. Production obtains
    # these objects from real signed release policy and pinned HTTPS setup.
    trust = object.__new__(TrustedKeyring)
    client = object.__new__(ProvisionedRecoveryObservationHttpsClient)
    inputs: dict[str, Any] = dict(
        review=review,
        admission=admission,
        signed_recovery=signed,
        selected=selected,
        software_root=tmp_path / "software",
        classroom_workspace=tmp_path / "workspace",
        service_client=client,
        witness_transport=lambda _: b"synthetic",
        pinned_witness_public_key=b"x" * 32,
        candidate=ProposedCandidateEvidence(b"new-p", b"new-r", b"new-l", b"new-n"),
        candidate_module_envelopes={"quillan": b"synthetic"},
        trust=trust,
        now=NOW,
    )
    return dict(inputs=inputs, calls=calls, remote=remote, module=module)


def inspect(ready: dict[str, Any], **changes: Any) -> Any:
    return inspect_plan_bound_forward_recovery(**(ready["inputs"] | changes))


def test_matching_forward_review_is_inert(ready: dict[str, Any]) -> None:
    result = inspect(ready)
    assert result.transaction_id == NEXT
    assert result.installation_id == INSTALL
    assert result.successor_generation == 2
    assert result.witness_revision == 2
    assert result.stage_relative_path == "candidate/two"
    assert result.pip_inventory_sha256 == "4" * 64
    assert result.native_payload_sha256 == "3" * 64
    assert (
        result.status
        == "PLAN_SUCCESSOR_BYTES_REVIEWED_FORWARD_FINALIZATION_STILL_REQUIRED"
    )
    assert "NO_LAUNCH" in result.authority
    assert len(ready["calls"]) == 1
    assert ready["calls"][0]["request"].installation_id == INSTALL


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transaction_id", "d" * 32),
        ("installation_id", "d" * 32),
        ("request_sha256", "e" * 64),
        ("serialized_request", b"changed"),
        ("journal_revision", True),
        ("status", "SERVICE_APPROVED"),
        ("authority", "CAN_LAUNCH"),
    ],
)
def test_forged_plan_rejected_before_remote(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(PlanForwardRecoveryError):
        inspect(ready, review=replace(ready["inputs"]["review"], **{field: value}))
    assert ready["calls"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_sha256", "e" * 64),
        ("expected_witness_revision", 10),
        ("successor_generation", True),
        ("fence_status", "CAS_MAY_HAVE_BEEN_DISPATCHED"),
        ("status", "CAN_DISPATCH"),
        ("authority", "CAN_LAUNCH"),
    ],
)
def test_forged_admission_rejected_before_remote(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(PlanForwardRecoveryError):
        inspect(
            ready, admission=replace(ready["inputs"]["admission"], **{field: value})
        )
    assert ready["calls"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_sha256", "f" * 64),
        ("witness_revision", True),
        ("signed_receipt_sha256", "f" * 64),
        ("fence_status", "PREPARED_NO_DISPATCH"),
        ("writer_status", "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"),
        ("status", "SIGNED_PRIOR_UNRESOLVED_NO_ROLLBACK_GRANT"),
        ("authority", "CAN_LAUNCH"),
    ],
)
def test_false_or_prior_signed_result_refused_before_remote(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(PlanForwardRecoveryError):
        inspect(
            ready,
            signed_recovery=replace(
                ready["inputs"]["signed_recovery"], **{field: value}
            ),
        )
    assert ready["calls"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transaction_id", "d" * 32),
        ("journal_revision", True),
        ("selected_generation", 3),
        ("witness_revision", 4),
        ("predecessor_receipt_sha256", "f" * 64),
        ("candidate_stage_relative_path", "foreign/stage"),
        ("status", "LAUNCH_READY"),
        ("authority", "CAN_LAUNCH"),
    ],
)
def test_wrong_selected_slot_refused_before_remote(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(PlanForwardRecoveryError):
        inspect(ready, selected=replace(ready["inputs"]["selected"], **{field: value}))
    assert ready["calls"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_client", None),
        ("pinned_witness_public_key", b"short"),
        ("witness_transport", None),
        ("now", datetime(2026, 10, 26)),
        ("trust", None),
        ("software_root", "/tmp/unsafe"),
        ("candidate", None),
    ],
)
def test_missing_recovery_prerequisites_refused_before_remote(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(PlanForwardRecoveryError):
        inspect(ready, **{field: value})
    assert ready["calls"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_sha256", "f" * 64),
        ("successor_receipt_sha256", "f" * 64),
        ("generation", 3),
        ("witness_revision", 9),
        ("stage_relative_path", "different/slot"),
        ("pip_inventory_sha256", "f" * 64),
        ("native_payload_sha256", "f" * 64),
        ("status", "READY_FOR_LAUNCH"),
        ("authority", "LAUNCH_GRANTED"),
    ],
)
def test_changed_pinned_handoff_refused(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    old = ready["remote"]
    wrong = replace(
        old.fresh_observation.attested_handoff.forward_handoff, **{field: value}
    )
    inner = replace(old.fresh_observation.attested_handoff, forward_handoff=wrong)
    ready["remote"] = replace(
        old, fresh_observation=replace(old.fresh_observation, attested_handoff=inner)
    )
    ready["module"].inspect_pinned_remote_forward_recovery = lambda *a, **k: ready[
        "remote"
    ]
    with pytest.raises(PlanForwardRecoveryError):
        inspect(ready)


def test_remote_failure_does_not_touch_package_or_workspace(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    software = ready["inputs"]["software_root"]
    workspace = ready["inputs"]["classroom_workspace"]
    software.mkdir()
    workspace.mkdir()
    (software / "leave_me").write_bytes(b"software")
    (workspace / "leave_me").write_bytes(b"classroom")

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise PinnedRemoteRecoveryError("synthetic outage")

    monkeypatch.setattr(
        ready["module"], "inspect_pinned_remote_forward_recovery", unavailable
    )
    with pytest.raises(PlanForwardRecoveryError):
        inspect(ready)
    assert (software / "leave_me").read_bytes() == b"software"
    assert (workspace / "leave_me").read_bytes() == b"classroom"


def test_no_downstream_remote_query_when_service_witness_is_prior(
    ready: dict[str, Any],
) -> None:
    signed = replace(
        ready["inputs"]["signed_recovery"],
        status="SIGNED_PRIOR_UNRESOLVED_NO_ROLLBACK_GRANT",
    )
    with pytest.raises(PlanForwardRecoveryError):
        inspect(ready, signed_recovery=signed)
    assert ready["calls"] == []


def test_remote_signed_service_identity_mismatch_refused(ready: dict[str, Any]) -> None:
    old = ready["remote"]
    wrong_service = replace(
        old.fresh_observation.attested_handoff.service_observation,
        transaction_id="d" * 32,
    )
    inner = replace(
        old.fresh_observation.attested_handoff, service_observation=wrong_service
    )
    remote = replace(
        old, fresh_observation=replace(old.fresh_observation, attested_handoff=inner)
    )
    ready["module"].inspect_pinned_remote_forward_recovery = lambda *a, **k: remote
    with pytest.raises(PlanForwardRecoveryError):
        inspect(ready)


def test_missing_remote_observation_refused(ready: dict[str, Any]) -> None:
    ready["module"].inspect_pinned_remote_forward_recovery = lambda *a, **k: None
    with pytest.raises(PlanForwardRecoveryError):
        inspect(ready)
