"""Slice 94: launch health evidence remains non-activating and one-shot."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_issue49_slice92_launch_dispatch import ACTOR, INSTALL, NOW, run_launch
from test_issue49_slice93_launch_reconciliation import reconcile

from paper_data_suite.evergreen_plan_launch_health_preflight import (
    IndependentProcessHealthInspection,
    LaunchHealthPreflightError,
    ProtectedLaunchHealthPreflight,
    ProtectedLaunchHealthPreflightLedger,
)
from paper_data_suite.evergreen_plan_launch_reconciliation import (
    ProtectedLaunchReconciliationCertificate,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest

pytest_plugins = ("test_issue49_slice93_launch_reconciliation",)


@pytest.fixture
def health_ready(dispatch_ready: dict[str, Any]) -> dict[str, Any]:
    r = dispatch_ready
    run_launch(r)
    r["dispatch_claim"] = r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
    from paper_data_suite.evergreen_plan_launch_reconciliation import (
        ProtectedLaunchReconciler,
    )

    r["reconciliation"] = ProtectedLaunchReconciler(r["launch_dispatch"])
    certificate = reconcile(r)
    assert isinstance(certificate, ProtectedLaunchReconciliationCertificate)
    r["launch_certificate"] = certificate
    r["health_ledger"] = ProtectedLaunchHealthPreflightLedger(r["reconciliation"])
    r["health_reads"] = []
    r["health_heartbeat"] = 101

    def health_reader(
        request: WitnessCommitRequest, context: object
    ) -> IndependentProcessHealthInspection:
        r["health_reads"].append(1)
        assert context is ACTOR
        return IndependentProcessHealthInspection(
            installation_id=request.installation_id,
            transaction_id=r["reservation"].transaction_id,
            executable_identity_sha256=r["dispatch_claim"].executable_identity_sha256,
            service_boundary_sha256=r["dispatch_claim"].service_boundary_sha256,
            target_identity_sha256=r["intent"].target_identity_sha256,
            process_instance_sha256="a" * 64,
            readiness_probe_sha256="b" * 64,
            heartbeat_sequence=r["health_heartbeat"],
            exact_process_instance_still_running=True,
            launcher_service_fence_held=True,
            no_second_launch_attempt_observed=True,
            approved_executable_still_mapped=True,
            runtime_readiness_probe_succeeded=True,
            successor_receipt_independently_confirmed=True,
            capsule_still_absent_independently_confirmed=True,
            protected_classroom_files_unchanged=True,
        )

    r["health_reader"] = health_reader
    return r


def record_health(r: dict[str, Any], **changes: Any) -> ProtectedLaunchHealthPreflight:
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
        service_context=ACTOR,
        independently_read_postdelete=r["post"],
        independently_confirm_delete_termination=r["termination_reader"],
        independently_inspect_process=r["read_process"],
        independently_inspect_health=r["health_reader"],
        witness_transport=r["witness"],
        pinned_public_key=r["public"],
        now=NOW,
    )
    return r["health_ledger"].record_once(**(args | changes))


def test_good_health_records_only_diagnostic_certificate(
    health_ready: dict[str, Any],
) -> None:
    r = health_ready
    prior_calls = list(r["start_calls"])
    original_receipt = r["active"].read_bytes()
    protected_bytes = (r["local"] / "student-work.txt").read_bytes()
    record = record_health(r)
    assert record.status == (
        "POSTLAUNCH_RUNTIME_HEALTH_PREFLIGHT_RECORDED_NO_ACTIVATION_AUTHORITY"
    )
    assert record.authority.startswith("NO_PROCESS_LAUNCH_RETRY_ACTIVATE")
    assert r["health_ledger"].observe(INSTALL, service_context=ACTOR) == record
    assert len(r["health_reads"]) == 2
    assert r["start_calls"] == prior_calls == ["one-independent-service-launch"]
    assert r["active"].read_bytes() == original_receipt == r["new"]
    assert (r["local"] / "student-work.txt").read_bytes() == protected_bytes
    assert not r["db"].in_transaction
    for method in ("activate", "dispatch", "retry", "switch", "rollback"):
        assert not hasattr(r["health_ledger"], method)


def test_duplicate_refused_before_physical_inspection(
    health_ready: dict[str, Any],
) -> None:
    r = health_ready
    record_health(r)
    before = (len(r["health_reads"]), len(r["start_calls"]))
    with pytest.raises(LaunchHealthPreflightError, match="already recorded"):
        record_health(r)
    assert before == (len(r["health_reads"]), len(r["start_calls"]))


@pytest.mark.parametrize(
    "field",
    [
        "exact_process_instance_still_running",
        "launcher_service_fence_held",
        "no_second_launch_attempt_observed",
        "approved_executable_still_mapped",
        "runtime_readiness_probe_succeeded",
        "successor_receipt_independently_confirmed",
        "capsule_still_absent_independently_confirmed",
        "protected_classroom_files_unchanged",
    ],
)
def test_false_runtime_attestation_refused(
    health_ready: dict[str, Any],
    field: str,
) -> None:
    r = health_ready
    reader = r["health_reader"]

    def bad(
        req: WitnessCommitRequest, ctx: object
    ) -> IndependentProcessHealthInspection:
        return replace(reader(req, ctx), **{field: False})

    with pytest.raises(LaunchHealthPreflightError, match="runtime health invalid"):
        record_health(r, independently_inspect_health=bad)
    assert r["health_ledger"].observe(INSTALL, service_context=ACTOR) is None
    assert len(r["start_calls"]) == 1


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
def test_forged_health_identity_refused(
    health_ready: dict[str, Any],
    field: str,
) -> None:
    r = health_ready
    reader = r["health_reader"]

    def bad(
        req: WitnessCommitRequest, ctx: object
    ) -> IndependentProcessHealthInspection:
        return replace(reader(req, ctx), **{field: "f" * 64})

    with pytest.raises(LaunchHealthPreflightError, match="runtime health invalid"):
        record_health(r, independently_inspect_health=bad)


@pytest.mark.parametrize("bad", [0, -1, True, "101", 2**53])
def test_unacceptable_heartbeat_refused(
    health_ready: dict[str, Any],
    bad: object,
) -> None:
    r = health_ready
    reader = r["health_reader"]

    def invalid(
        req: WitnessCommitRequest, ctx: object
    ) -> IndependentProcessHealthInspection:
        return replace(reader(req, ctx), heartbeat_sequence=bad)

    with pytest.raises(LaunchHealthPreflightError, match="runtime health invalid"):
        record_health(r, independently_inspect_health=invalid)


def test_runtime_health_drift_refused(health_ready: dict[str, Any]) -> None:
    r = health_ready
    reader = r["health_reader"]
    reads: list[int] = []

    def changing(
        req: WitnessCommitRequest, ctx: object
    ) -> IndependentProcessHealthInspection:
        reads.append(1)
        return replace(reader(req, ctx), heartbeat_sequence=100 + len(reads))

    with pytest.raises(LaunchHealthPreflightError, match="drifted"):
        record_health(r, independently_inspect_health=changing)
    assert len(reads) == 2
    assert r["health_ledger"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_signed_witness_refused(health_ready: dict[str, Any]) -> None:
    def offline(payload: bytes) -> bytes:
        raise OSError("witness offline")

    with pytest.raises(LaunchHealthPreflightError, match="witness unavailable"):
        record_health(health_ready, witness_transport=offline)


def test_missing_process_and_no_relaunch(health_ready: dict[str, Any]) -> None:
    r = health_ready
    r["observed_start"] = False
    with pytest.raises(LaunchHealthPreflightError, match="confirmed process start"):
        record_health(r)
    assert len(r["start_calls"]) == 1


def test_process_start_sample_changed_since_reconciliation(
    health_ready: dict[str, Any],
) -> None:
    r = health_ready
    reader = r["read_process"]

    def changed(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(reader(req, ctx), process_start_observed=None)

    with pytest.raises(LaunchHealthPreflightError, match="confirmed process start"):
        record_health(r, independently_inspect_process=changed)


def test_forged_launch_certificate_refused(health_ready: dict[str, Any]) -> None:
    r = health_ready
    forged = replace(r["launch_certificate"], process_observation_sha256="f" * 64)
    with pytest.raises(LaunchHealthPreflightError, match="durable health chain"):
        record_health(r, launch_reconciliation=forged)


def test_missing_persisted_reconciliation_refused(
    health_ready: dict[str, Any],
) -> None:
    r = health_ready
    r["db"].execute("DELETE FROM plan_launch_reconciliation_v1")
    with pytest.raises(LaunchHealthPreflightError, match="durable health chain"):
        record_health(r)


def test_capsule_reappears_refused(health_ready: dict[str, Any]) -> None:
    r = health_ready
    (r["local"] / "pending-slot-recovery.json").write_bytes(b"unplanned")
    with pytest.raises(LaunchHealthPreflightError):
        record_health(r)
    assert len(r["start_calls"]) == 1


def test_corrupted_successor_receipt_refused(health_ready: dict[str, Any]) -> None:
    r = health_ready
    r["active"].write_bytes(b"changed receipt")
    with pytest.raises(LaunchHealthPreflightError):
        record_health(r)


@pytest.mark.parametrize("context", [None, True, "teacher", "untrusted"])
def test_untrusted_service_context_refused(
    health_ready: dict[str, Any],
    context: object,
) -> None:
    with pytest.raises(LaunchHealthPreflightError, match="authorization"):
        record_health(health_ready, service_context=context)


def test_invalid_persisted_certificate_refused(
    health_ready: dict[str, Any],
) -> None:
    r = health_ready
    record_health(r)
    r["db"].execute(
        "UPDATE plan_launch_health_preflight_v1 "
        "SET runtime_health_evidence_sha256 = ? WHERE installation_id = ?",
        ("invalid", INSTALL),
    )
    with pytest.raises(LaunchHealthPreflightError, match="corrupt"):
        r["health_ledger"].observe(INSTALL, service_context=ACTOR)


def test_durable_certificate_can_be_reopened(health_ready: dict[str, Any]) -> None:
    r = health_ready
    result = record_health(r)
    db2 = sqlite3.connect(Path(r["db_path"]), isolation_level=None)
    try:
        row = db2.execute(
            "SELECT * FROM plan_launch_health_preflight_v1 WHERE installation_id = ?",
            (INSTALL,),
        ).fetchone()
        assert row is not None
        assert row[0] == INSTALL
        assert row[-1] == result.status
    finally:
        db2.close()


def test_external_open_transaction_refused(health_ready: dict[str, Any]) -> None:
    r = health_ready
    r["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LaunchHealthPreflightError, match="evidence unavailable"):
            record_health(r)
    finally:
        r["db"].execute("ROLLBACK")


def test_health_ledger_requires_exact_reconciler(
    health_ready: dict[str, Any],
) -> None:
    with pytest.raises(LaunchHealthPreflightError, match="database required"):
        ProtectedLaunchHealthPreflightLedger(object())  # type: ignore[arg-type]


def test_no_process_dispatch_or_activation_api(health_ready: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        record_health(health_ready, service_owned_launch=health_ready["service_start"])
    assert len(health_ready["start_calls"]) == 1
