"""Slice 93: reconcile durable one-shot dispatch, without another process call."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_issue49_slice92_launch_dispatch import (
    ACTOR,
    INSTALL,
    NOW,
    run_launch,
)

from paper_data_suite.evergreen_plan_launch_dispatch import (
    IndependentProcessStartReadback,
    LaunchDispatchError,
)
from paper_data_suite.evergreen_plan_launch_reconciliation import (
    LaunchReconciliationError,
    ProtectedLaunchReconciler,
    ProtectedLaunchReconciliationCertificate,
    ProtectedLaunchReconciliationObservation,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest

pytest_plugins = ("test_issue49_slice92_launch_dispatch",)


@pytest.fixture
def dispatched(dispatch_ready: dict[str, Any]) -> dict[str, Any]:
    r = dispatch_ready
    run_launch(r)
    r["dispatch_claim"] = r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
    r["reconciliation"] = ProtectedLaunchReconciler(r["launch_dispatch"])
    return r


def reconcile(r: dict[str, Any], **changes: Any) -> Any:
    args: dict[str, Any] = dict(
        request_bytes=r["raw"],
        reservation=r["reservation"],
        preclaim=r["preclaim"],
        record=r["record"],
        intent=r["intent"],
        marker=r["marker"],
        claim=r["claim"],
        convergence=r["certified"],
        clearance_preflight=r["preflight"],
        predelete_marker=r["delete_marker"],
        delete_claim=r["delete_claim"],
        postdelete_certificate=r["postdelete_certificate"],
        launcher_preflight=r["readiness_record"],
        launch_intent=r["launch_reservation"],
        prelaunch_marker=r["prelaunch_marker"],
        launch_dispatch_claim=r["dispatch_claim"],
        service_context=ACTOR,
        independently_read_postdelete=r["post"],
        independently_confirm_delete_termination=r["termination_reader"],
        independently_inspect_process=r["read_process"],
        witness_transport=r["witness"],
        pinned_public_key=r["public"],
        now=NOW,
    )
    return r["reconciliation"].reconcile_once(**(args | changes))


def test_reconcile_true_after_durable_launch_claim(
    dispatched: dict[str, Any],
) -> None:
    r = dispatched
    prior_calls = list(r["start_calls"])
    prior_receipt = r["active"].read_bytes()
    untouched = (r["local"] / "student-work.txt").read_bytes()
    result = reconcile(r)
    assert isinstance(result, ProtectedLaunchReconciliationCertificate)
    assert result.status == (
        "PROCESS_START_INDEPENDENTLY_RECONCILED_NO_ACTIVATION_AUTHORITY"
    )
    assert result.authority.startswith("NO_LAUNCH_RETRY_ACTIVATE")
    assert r["reconciliation"].observe(INSTALL, service_context=ACTOR) == result
    assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
    assert r["start_calls"] == prior_calls == ["one-independent-service-launch"]
    assert len(r["process_reads"]) == 3
    assert r["active"].read_bytes() == prior_receipt == r["new"]
    assert (r["local"] / "student-work.txt").read_bytes() == untouched
    assert not (r["local"] / "pending-slot-recovery.json").exists()
    assert not r["db"].in_transaction
    assert not hasattr(r["reconciliation"], "dispatch")
    assert not hasattr(r["reconciliation"], "activate")
    assert not hasattr(r["reconciliation"], "retry")


def test_duplicate_certification_refused_before_physical_reads(
    dispatched: dict[str, Any],
) -> None:
    r = dispatched
    reconcile(r)
    before = (
        len(r["process_reads"]),
        len(r["witness_reads"]),
        len(r["start_calls"]),
    )
    with pytest.raises(LaunchReconciliationError, match="already reconciled"):
        reconcile(r)
    assert before == (
        len(r["process_reads"]),
        len(r["witness_reads"]),
        len(r["start_calls"]),
    )


def test_lost_launch_ack_can_be_reconciled_without_relaunch(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    real = r["service_start"]

    def lost_ack(req: WitnessCommitRequest, exe: str, ctx: object) -> None:
        real(req, exe, ctx)
        raise OSError("launcher acknowledgment lost after possible start")

    with pytest.raises(LaunchDispatchError, match="outcome uncertain"):
        run_launch(r, service_owned_launch=lost_ack)
    r["dispatch_claim"] = r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
    r["reconciliation"] = ProtectedLaunchReconciler(r["launch_dispatch"])
    answer = reconcile(r)
    assert isinstance(answer, ProtectedLaunchReconciliationCertificate)
    assert len(r["start_calls"]) == 1
    with pytest.raises(LaunchDispatchError, match="already claimed"):
        run_launch(r)
    assert len(r["start_calls"]) == 1


@pytest.mark.parametrize(
    "observed,status",
    [
        (False, "PROCESS_NOT_OBSERVED_NO_RELAUNCH_AUTHORITY"),
        (None, "PROCESS_OUTCOME_UNKNOWN_NO_RELAUNCH_AUTHORITY"),
    ],
)
def test_no_process_or_unknown_never_creates_certificate(
    dispatched: dict[str, Any],
    observed: bool | None,
    status: str,
) -> None:
    r = dispatched
    r["observed_start"] = observed
    before = len(r["start_calls"])
    result = reconcile(r)
    assert isinstance(result, ProtectedLaunchReconciliationObservation)
    assert result.status == status
    assert r["reconciliation"].observe(INSTALL, service_context=ACTOR) is None
    assert len(r["start_calls"]) == before == 1
    with pytest.raises(LaunchDispatchError, match="already claimed"):
        run_launch(r)


def test_late_independent_start_observation_does_not_relaunch(
    dispatched: dict[str, Any],
) -> None:
    r = dispatched
    r["observed_start"] = None
    assert isinstance(reconcile(r), ProtectedLaunchReconciliationObservation)
    r["observed_start"] = True
    assert isinstance(reconcile(r), ProtectedLaunchReconciliationCertificate)
    assert len(r["start_calls"]) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("prelaunch_marker_sha256", "f" * 64),
        ("protected_launch_intent_sha256", "f" * 64),
        ("launcher_readiness_preflight_sha256", "f" * 64),
        ("executable_identity_sha256", "f" * 64),
        ("service_boundary_sha256", "f" * 64),
        ("target_identity_sha256", "f" * 64),
        ("renewed_runtime_evidence_sha256", "f" * 64),
        ("status", "LAUNCH_ACCEPTED"),
        ("authority", "LAUNCH_RETRY_ALLOWED"),
    ],
)
def test_forged_dispatch_claim_refused(
    dispatched: dict[str, Any],
    field: str,
    value: str,
) -> None:
    r = dispatched
    forged = replace(r["dispatch_claim"], **{field: value})
    with pytest.raises(LaunchReconciliationError):
        reconcile(r, launch_dispatch_claim=forged)
    assert not r["reconciliation"].observe(INSTALL, service_context=ACTOR)
    assert len(r["start_calls"]) == 1


def test_missing_durable_dispatch_refused(dispatched: dict[str, Any]) -> None:
    r = dispatched
    r["db"].execute("DELETE FROM plan_launch_dispatch_v1")
    with pytest.raises(LaunchReconciliationError, match="durable launch chain"):
        reconcile(r)
    assert r["reconciliation"].observe(INSTALL, service_context=ACTOR) is None


def test_corrupted_durable_dispatch_refused(dispatched: dict[str, Any]) -> None:
    r = dispatched
    r["db"].execute(
        "UPDATE plan_launch_dispatch_v1 SET executable_identity_sha256 = ?",
        ("0" * 64,),
    )
    with pytest.raises(LaunchReconciliationError, match="durable launch chain"):
        reconcile(r)


def test_missing_upstream_prelaunch_record_refused(
    dispatched: dict[str, Any],
) -> None:
    r = dispatched
    r["db"].execute("DELETE FROM plan_prelaunch_uncertainty_v1")
    with pytest.raises(LaunchReconciliationError, match="durable launch chain"):
        reconcile(r)


@pytest.mark.parametrize("bad", [None, "teacher", "student", True])
def test_unauthorized_service_context_refused(
    dispatched: dict[str, Any],
    bad: object,
) -> None:
    with pytest.raises(LaunchReconciliationError, match="authorization"):
        reconcile(dispatched, service_context=bad)


@pytest.mark.parametrize(
    "field",
    [
        "exclusive_launcher_service_fence_held",
        "no_second_dispatch_observed",
        "successor_receipt_independently_confirmed",
        "capsule_still_absent_independently_confirmed",
        "protected_software_and_classroom_files_unchanged",
    ],
)
def test_false_independent_process_fence_blocks_certificate(
    dispatched: dict[str, Any],
    field: str,
) -> None:
    r = dispatched
    original = r["read_process"]

    def bad(req: WitnessCommitRequest, ctx: object) -> IndependentProcessStartReadback:
        return replace(original(req, ctx), **{field: False})

    with pytest.raises(LaunchReconciliationError, match="observation invalid"):
        reconcile(r, independently_inspect_process=bad)
    assert not r["reconciliation"].observe(INSTALL, service_context=ACTOR)


@pytest.mark.parametrize(
    "field",
    [
        "installation_id",
        "transaction_id",
        "executable_identity_sha256",
        "service_boundary_sha256",
        "target_identity_sha256",
    ],
)
def test_forged_independent_process_identity_refused(
    dispatched: dict[str, Any],
    field: str,
) -> None:
    r = dispatched
    original = r["read_process"]

    def bad(req: WitnessCommitRequest, ctx: object) -> IndependentProcessStartReadback:
        return replace(original(req, ctx), **{field: "0" * 64})

    with pytest.raises(LaunchReconciliationError, match="observation invalid"):
        reconcile(r, independently_inspect_process=bad)


def test_process_observation_drift_refused(dispatched: dict[str, Any]) -> None:
    r = dispatched
    reader = r["read_process"]
    calls: list[int] = []

    def changing(
        req: WitnessCommitRequest, ctx: object
    ) -> IndependentProcessStartReadback:
        calls.append(1)
        answer = reader(req, ctx)
        return replace(answer, process_start_observed=(len(calls) == 1))

    with pytest.raises(LaunchReconciliationError, match="drifted"):
        reconcile(r, independently_inspect_process=changing)
    assert len(calls) == 2
    assert not r["reconciliation"].observe(INSTALL, service_context=ACTOR)


def test_lost_independent_process_reader_refused(
    dispatched: dict[str, Any],
) -> None:
    def offline(req: WitnessCommitRequest, ctx: object) -> Any:
        raise OSError("privileged process service offline")

    with pytest.raises(LaunchReconciliationError, match="evidence unavailable"):
        reconcile(dispatched, independently_inspect_process=offline)
    assert not dispatched["reconciliation"].observe(INSTALL, service_context=ACTOR)


def test_fresh_signed_witness_failure_refused(
    dispatched: dict[str, Any],
) -> None:
    def broken(payload: bytes) -> bytes:
        raise ConnectionError("signed witness offline")

    with pytest.raises(LaunchReconciliationError, match="witness unavailable"):
        reconcile(dispatched, witness_transport=broken)


def test_capsule_reappears_before_reconciliation_refused(
    dispatched: dict[str, Any],
) -> None:
    r = dispatched
    (r["local"] / "pending-slot-recovery.json").write_bytes(b"unexpected")
    with pytest.raises(LaunchReconciliationError, match="capsule"):
        reconcile(r)
    assert len(r["start_calls"]) == 1


def test_successor_receipt_changed_refused(dispatched: dict[str, Any]) -> None:
    r = dispatched
    r["active"].write_bytes(b"forged successor receipt")
    with pytest.raises(LaunchReconciliationError):
        reconcile(r)
    assert not r["reconciliation"].observe(INSTALL, service_context=ACTOR)


def test_durable_certificate_survives_database_reopen(
    dispatched: dict[str, Any],
) -> None:
    r = dispatched
    certificate = reconcile(r)
    assert isinstance(certificate, ProtectedLaunchReconciliationCertificate)
    db2 = sqlite3.connect(Path(r["db_path"]), isolation_level=None)
    try:
        row = db2.execute(
            "SELECT * FROM plan_launch_reconciliation_v1 WHERE installation_id = ?",
            (INSTALL,),
        ).fetchone()
        assert row is not None
        assert row[0] == INSTALL
        assert row[-1] == certificate.status
    finally:
        db2.close()


def test_corrupted_durable_certificate_refused(
    dispatched: dict[str, Any],
) -> None:
    r = dispatched
    reconcile(r)
    r["db"].execute(
        "UPDATE plan_launch_reconciliation_v1 "
        "SET process_observation_sha256 = ? WHERE installation_id = ?",
        ("not-a-sha", INSTALL),
    )
    with pytest.raises(LaunchReconciliationError, match="corrupt"):
        r["reconciliation"].observe(INSTALL, service_context=ACTOR)
    with pytest.raises(LaunchReconciliationError, match="already reconciled"):
        reconcile(r)


def test_open_transaction_refused(dispatched: dict[str, Any]) -> None:
    r = dispatched
    db = r["db"]
    db.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LaunchReconciliationError, match="evidence unavailable"):
            reconcile(r)
    finally:
        db.execute("ROLLBACK")


def test_reconciler_requires_exact_dispatcher(
    dispatched: dict[str, Any],
) -> None:
    with pytest.raises(LaunchReconciliationError, match="database required"):
        ProtectedLaunchReconciler(object())  # type: ignore[arg-type]


def test_no_launcher_callback_in_reconciliation_api(
    dispatched: dict[str, Any],
) -> None:
    r = dispatched
    with pytest.raises(TypeError):
        reconcile(r, service_owned_launch=r["service_start"])
    assert len(r["start_calls"]) == 1
