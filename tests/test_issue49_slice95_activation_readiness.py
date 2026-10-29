"""Slice 95: activation readiness is protected, append-once, and non-activating."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_issue49_slice92_launch_dispatch import ACTOR, INSTALL, NOW
from test_issue49_slice94_launch_health_preflight import record_health

from paper_data_suite.evergreen_plan_activation_readiness import (
    ActivationReadinessError,
    IndependentActivationFenceInspection,
    ProtectedActivationReadinessLedger,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest

pytest_plugins = ("test_issue49_slice94_launch_health_preflight",)


@pytest.fixture
def activation_ready(health_ready: dict[str, Any]) -> dict[str, Any]:
    r = health_ready
    r["health_record"] = record_health(r)
    r["activation_ledger"] = ProtectedActivationReadinessLedger(r["health_ledger"])
    r["activation_reads"] = []

    def fence_reader(
        request: WitnessCommitRequest, context: object
    ) -> IndependentActivationFenceInspection:
        r["activation_reads"].append(1)
        assert context is ACTOR
        health = r["health_reader"](request, context)
        return IndependentActivationFenceInspection(
            installation_id=request.installation_id,
            transaction_id=r["reservation"].transaction_id,
            executable_identity_sha256=r["dispatch_claim"].executable_identity_sha256,
            service_boundary_sha256=r["dispatch_claim"].service_boundary_sha256,
            target_identity_sha256=r["intent"].target_identity_sha256,
            process_instance_sha256=health.process_instance_sha256,
            activation_fence_sha256="e" * 64,
            no_prior_activation_attempt_observed=True,
            no_slot_transition_observed=True,
            exclusive_activation_fence_held=True,
            approved_successor_still_active=True,
            approved_process_still_healthy=True,
            protected_classroom_files_unchanged=True,
            no_recovery_operation_in_flight=True,
            no_second_launch_dispatch_observed=True,
        )

    r["fence_reader"] = fence_reader
    return r


def reserve(r: dict[str, Any], **changes: Any) -> Any:
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
        launch_reconciliation=r["launch_certificate"],
        postlaunch_health_preflight=r["health_record"],
        service_context=ACTOR,
        independently_read_postdelete=r["post"],
        independently_confirm_delete_termination=r["termination_reader"],
        independently_inspect_process=r["read_process"],
        independently_inspect_health=r["health_reader"],
        independently_inspect_activation=r["fence_reader"],
        witness_transport=r["witness"],
        pinned_public_key=r["public"],
        now=NOW,
    )
    return r["activation_ledger"].record_once(**(args | changes))


def test_reservation_is_durable_and_inert(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    before_receipt = r["active"].read_bytes()
    before_protected = (r["local"] / "student-work.txt").read_bytes()
    before_launches = list(r["start_calls"])
    item = reserve(r)
    assert item.status == "ACTIVATION_READINESS_RESERVED_NO_ACTIVATION_DISPATCH"
    assert item.authority.startswith("NO_ACTIVATE_DISPATCH_SWITCH")
    assert item.postlaunch_health_preflight_sha256 != "0" * 64
    assert item.activation_fence_evidence_sha256 != "0" * 64
    assert r["activation_ledger"].observe(INSTALL, service_context=ACTOR) == item
    assert len(r["activation_reads"]) == 2
    assert r["start_calls"] == before_launches == ["one-independent-service-launch"]
    assert r["active"].read_bytes() == before_receipt
    assert (r["local"] / "student-work.txt").read_bytes() == before_protected
    assert not r["db"].in_transaction
    for forbidden in ("activate", "dispatch", "launch", "retry", "switch"):
        assert not hasattr(r["activation_ledger"], forbidden)


def test_duplicate_does_not_read_more_evidence(
    activation_ready: dict[str, Any],
) -> None:
    r = activation_ready
    reserve(r)
    before = (len(r["activation_reads"]), len(r["start_calls"]))
    with pytest.raises(ActivationReadinessError, match="already reserved"):
        reserve(r)
    assert before == (len(r["activation_reads"]), len(r["start_calls"]))


@pytest.mark.parametrize(
    "field",
    [
        "no_prior_activation_attempt_observed",
        "no_slot_transition_observed",
        "exclusive_activation_fence_held",
        "approved_successor_still_active",
        "approved_process_still_healthy",
        "protected_classroom_files_unchanged",
        "no_recovery_operation_in_flight",
        "no_second_launch_dispatch_observed",
    ],
)
def test_false_fence_refused(activation_ready: dict[str, Any], field: str) -> None:
    r = activation_ready
    reader = r["fence_reader"]

    def invalid(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(reader(req, ctx), **{field: False})

    with pytest.raises(ActivationReadinessError, match="activation fence invalid"):
        reserve(r, independently_inspect_activation=invalid)
    assert r["activation_ledger"].observe(INSTALL, service_context=ACTOR) is None
    assert len(r["start_calls"]) == 1


@pytest.mark.parametrize(
    "field",
    [
        "installation_id",
        "transaction_id",
        "executable_identity_sha256",
        "service_boundary_sha256",
        "target_identity_sha256",
        "process_instance_sha256",
        "activation_fence_sha256",
    ],
)
def test_forged_fence_identity_refused(
    activation_ready: dict[str, Any], field: str
) -> None:
    r = activation_ready
    reader = r["fence_reader"]

    def invalid(req: WitnessCommitRequest, ctx: object) -> Any:
        value = "0" * 64 if field == "activation_fence_sha256" else "f" * 64
        return replace(reader(req, ctx), **{field: value})

    with pytest.raises(ActivationReadinessError, match="activation fence invalid"):
        reserve(r, independently_inspect_activation=invalid)


def test_fence_evidence_drift_refused(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    reader = r["fence_reader"]
    reads: list[int] = []

    def drift(req: WitnessCommitRequest, ctx: object) -> Any:
        reads.append(1)
        return replace(
            reader(req, ctx),
            activation_fence_sha256=("e" if len(reads) == 1 else "f") * 64,
        )

    with pytest.raises(ActivationReadinessError, match="drifted"):
        reserve(r, independently_inspect_activation=drift)
    assert len(reads) == 2
    assert r["activation_ledger"].observe(INSTALL, service_context=ACTOR) is None


def test_changed_health_after_prior_preflight_refused(
    activation_ready: dict[str, Any],
) -> None:
    r = activation_ready
    reader = r["health_reader"]

    def new_heartbeat(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(reader(req, ctx), heartbeat_sequence=102)

    with pytest.raises(ActivationReadinessError, match="changed since preflight"):
        reserve(r, independently_inspect_health=new_heartbeat)


def test_changed_process_refused(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    r["observed_start"] = False
    with pytest.raises(ActivationReadinessError, match="confirmed process start"):
        reserve(r)
    assert len(r["start_calls"]) == 1


def test_forged_persisted_health_refused(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    r["db"].execute(
        "UPDATE plan_launch_health_preflight_v1 "
        "SET runtime_health_evidence_sha256 = ? WHERE installation_id = ?",
        ("f" * 64, INSTALL),
    )
    with pytest.raises(ActivationReadinessError, match="durable activation chain"):
        reserve(r)


def test_forged_health_argument_refused(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    forged = replace(r["health_record"], runtime_health_evidence_sha256="f" * 64)
    with pytest.raises(ActivationReadinessError, match="durable activation chain"):
        reserve(r, postlaunch_health_preflight=forged)


def test_capsule_reappears_refused(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    (r["local"] / "pending-slot-recovery.json").write_bytes(b"unplanned")
    with pytest.raises(ActivationReadinessError):
        reserve(r)


def test_successor_receipt_mutation_refused(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    r["active"].write_bytes(b"changed")
    with pytest.raises(ActivationReadinessError):
        reserve(r)


def test_offline_signed_witness_refused(activation_ready: dict[str, Any]) -> None:
    def offline(raw: bytes) -> bytes:
        raise OSError("no witness")

    with pytest.raises(ActivationReadinessError, match="witness unavailable"):
        reserve(activation_ready, witness_transport=offline)


@pytest.mark.parametrize("context", [None, True, "teacher", "untrusted"])
def test_unauthorized_context_refused(
    activation_ready: dict[str, Any], context: object
) -> None:
    with pytest.raises(ActivationReadinessError, match="authorization"):
        reserve(activation_ready, service_context=context)


def test_bad_persisted_reservation_refused(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    reserve(r)
    r["db"].execute(
        "UPDATE plan_activation_readiness_v1 "
        "SET activation_fence_evidence_sha256 = ? WHERE installation_id = ?",
        ("invalid", INSTALL),
    )
    with pytest.raises(ActivationReadinessError, match="corrupt"):
        r["activation_ledger"].observe(INSTALL, service_context=ACTOR)


def test_reservation_survives_reopen(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    result = reserve(r)
    db2 = sqlite3.connect(Path(r["db_path"]), isolation_level=None)
    try:
        row = db2.execute(
            "SELECT * FROM plan_activation_readiness_v1 WHERE installation_id = ?",
            (INSTALL,),
        ).fetchone()
        assert row is not None
        assert len(row) == 16
        assert row[0] == INSTALL
        assert row[-1] == result.status
    finally:
        db2.close()


def test_external_transaction_refused(activation_ready: dict[str, Any]) -> None:
    r = activation_ready
    r["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ActivationReadinessError, match="evidence unavailable"):
            reserve(r)
    finally:
        r["db"].execute("ROLLBACK")


def test_ledger_requires_exact_health_ledger(activation_ready: dict[str, Any]) -> None:
    with pytest.raises(ActivationReadinessError, match="database required"):
        ProtectedActivationReadinessLedger(object())  # type: ignore[arg-type]


def test_does_not_accept_process_launcher(activation_ready: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        reserve(
            activation_ready,
            service_owned_launch=activation_ready["service_start"],
        )
    assert len(activation_ready["start_calls"]) == 1
