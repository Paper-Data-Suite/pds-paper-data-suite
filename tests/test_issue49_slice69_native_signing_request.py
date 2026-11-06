"""Slice 69: native signing requests do not become trusted native evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import paper_data_suite.evergreen_plan_native_request as module
from paper_data_suite.evergreen_plan_native_request import (
    NativeSigningRequestError,
    prepare_unsigned_native_evidence_request,
)
from paper_data_suite.evergreen_plan_stage_installer import IsolatedPlanStageResult
from paper_data_suite.evergreen_plan_wheelhouse_preflight import (
    PlanWheelhousePreflightError,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    PublisherPipPreflightError,
)

NOW = datetime(2026, 10, 26, 1, tzinfo=UTC)
TX = "f" * 32
BASE = "e" * 32
PIN = "a" * 64
LOCK = "b" * 64
INVENTORY = "c" * 64


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    software = tmp_path / "software"
    classroom = tmp_path / "classroom"
    wheels = software / "wheelhouse"
    stage = software / "candidate-builds" / TX
    stage.mkdir(parents=True)
    classroom.mkdir()
    wheels.mkdir()
    (classroom / "private.txt").write_bytes(b"student data must not be read")
    (stage / "bin").mkdir()
    (stage / "bin/python").write_bytes(b"verified native python placeholder")
    (stage / "bin/quillan").write_bytes(b"verified launcher placeholder")
    installed = IsolatedPlanStageResult(
        TX, stage, b"prepared", INVENTORY, BASE, 4, LOCK
    )
    snapshot = SimpleNamespace(registry=SimpleNamespace(payload_sha256=PIN))
    witnessed = SimpleNamespace(transaction_id=BASE, witness_revision=4)
    trust = SimpleNamespace()
    checked = SimpleNamespace(
        baseline_transaction_id=BASE,
        baseline_witness_revision=4,
        registry_payload_sha256=PIN,
        signed_lock_payload_sha256=LOCK,
    )
    prepared = SimpleNamespace(
        transaction_id=TX,
        registry_payload_sha256=PIN,
        lock_payload_sha256=LOCK,
        trust_fingerprint="d" * 64,
        python_minor="3.11",
        platform="win_arm64",
    )
    pip = SimpleNamespace(
        transaction_id=TX,
        stage_root=stage,
        wheelhouse=wheels,
        pip_inventory_sha256=INVENTORY,
        registry_payload_sha256=PIN,
        lock_payload_sha256=LOCK,
    )
    runtime = SimpleNamespace(
        transaction_id=TX,
        stage_root=stage,
        console_launchers=(SimpleNamespace(path=stage / "bin/quillan"),),
    )
    calls: list[str] = []

    def track(kind: str, value: Any) -> Any:
        def callback(*args: Any, **kwargs: Any) -> Any:
            calls.append(kind)
            return value

        return callback

    monkeypatch.setattr(module, "CatalogSnapshot", SimpleNamespace)
    monkeypatch.setattr(module, "WitnessSelectedStageObservation", SimpleNamespace)
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    monkeypatch.setattr(module, "inspect_plan_bound_wheelhouse", track("plan", checked))
    monkeypatch.setattr(
        module, "verify_prepared_record_against_wheelhouse", track("prepared", prepared)
    )
    monkeypatch.setattr(module, "_match_prepared", track("match", None))
    monkeypatch.setattr(
        module, "audit_publisher_bound_pip_candidate", track("publisher-pip", pip)
    )
    monkeypatch.setattr(module, "inspect_staged_virtualenv", track("runtime", runtime))
    return {
        "args": dict(
            snapshot=snapshot,
            witnessed=witnessed,
            installed=installed,
            software_root=software,
            classroom_workspace=classroom,
            wheelhouse=wheels,
            requested_targets={"quillan": "0.10.0"},
            python_minor="3.11",
            platform_tag="win_arm64",
            registry_envelope=b"signed registry",
            lock_envelope=b"signed lock",
            module_envelopes={"quillan": b"signed publisher"},
            trust=trust,
            now=NOW,
            revision=10,
            issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=1),
            layout="posix",
        ),
        "calls": calls,
        "checked": checked,
        "prepared": prepared,
        "pip": pip,
        "runtime": runtime,
        "stage": stage,
        "software": software,
        "classroom": classroom,
    }


def run(ready: dict[str, Any], **changes: Any) -> Any:
    return prepare_unsigned_native_evidence_request(**{**ready["args"], **changes})


def test_native_signing_request_matches_exact_expected_schema_and_hash(
    ready: dict[str, Any],
) -> None:
    data_before = (ready["classroom"] / "private.txt").read_bytes()
    with (
        patch("subprocess.run", side_effect=AssertionError("execute")),
        patch("socket.create_connection", side_effect=AssertionError("network")),
    ):
        request = run(ready)
    assert request.transaction_id == TX
    assert request.file_count == 2
    assert request.signed_lock_payload_sha256 == LOCK
    assert request.pip_inventory_sha256 == INVENTORY
    assert request.status.startswith("UNSIGNED_")
    assert request.authority == (
        "NO_SIGNING_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY"
    )
    assert hashlib.sha256(request.payload).hexdigest() == request.payload_sha256
    decoded = json.loads(request.payload)
    assert decoded == {
        "record_type": "pds_evergreen_staged_native_evidence",
        "schema_version": 1,
        "revision": 10,
        "issued_at": "2026-10-26T00:59:00Z",
        "expires_at": "2026-10-26T02:00:00Z",
        "transaction_id": TX,
        "registry_payload_sha256": PIN,
        "lock_payload_sha256": LOCK,
        "trust_fingerprint": "d" * 64,
        "python_minor": "3.11",
        "platform": "win_arm64",
        "files": [
            {
                "relative_path": name,
                "sha256": hashlib.sha256(
                    (ready["stage"] / name).read_bytes()
                ).hexdigest(),
                "size": (ready["stage"] / name).stat().st_size,
            }
            for name in ("bin/python", "bin/quillan")
        ],
    }
    assert "signatures" not in decoded
    assert "private.txt" not in request.payload.decode()
    assert (ready["classroom"] / "private.txt").read_bytes() == data_before
    assert not (ready["software"] / "active-receipt.json").exists()
    assert (
        ready["calls"] == ["plan", "prepared", "match", "publisher-pip", "runtime"] * 2
    )


@pytest.mark.parametrize(
    "change",
    [
        {"trust": None},
        {"revision": 0},
        {"revision": True},
        {"revision": 2**53},
        {"now": datetime(2026, 10, 26, 1)},
        {"issued_at": datetime(2026, 10, 26, 1)},
        {"expires_at": NOW},
        {"issued_at": NOW + timedelta(minutes=1)},
        {"expires_at": NOW + timedelta(days=31)},
        {"layout": "win-guess"},
        {"module_envelopes": {}},
        {"module_envelopes": {"quillan": "unsigned"}},
    ],
)
def test_invalid_signing_request_refuses_before_signed_inspection(
    ready: dict[str, Any], change: dict[str, Any]
) -> None:
    with pytest.raises(NativeSigningRequestError):
        run(ready, **change)
    assert ready["calls"] == []


def test_changed_baseline_observation_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "inspect_plan_bound_wheelhouse",
        lambda *a, **k: SimpleNamespace(
            **{**vars(ready["checked"]), "baseline_witness_revision": 9}
        ),
    )
    with pytest.raises(NativeSigningRequestError, match="drifted"):
        run(ready)


def test_stage_must_match_transaction_specific_managed_candidate(
    ready: dict[str, Any], tmp_path: Path
) -> None:
    foreign = tmp_path / "untrusted-stage"
    foreign.mkdir()
    with pytest.raises(NativeSigningRequestError):
        run(ready, installed=replace(ready["args"]["installed"], stage_root=foreign))
    assert ready["calls"] == []


def test_installed_inventory_digest_drift_refuses(ready: dict[str, Any]) -> None:
    with pytest.raises(NativeSigningRequestError, match="drifted"):
        run(
            ready,
            installed=replace(
                ready["args"]["installed"], pip_inventory_sha256="0" * 64
            ),
        )


def test_missing_native_interpreter_refuses(ready: dict[str, Any]) -> None:
    (ready["stage"] / "bin/python").unlink()
    with pytest.raises(NativeSigningRequestError):
        run(ready)


def test_untrusted_native_symlink_refuses(ready: dict[str, Any]) -> None:
    path = ready["stage"] / "bin/python"
    target = ready["stage"] / "bin/quillan"
    path.unlink()
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlinks unavailable")
    with pytest.raises(NativeSigningRequestError):
        run(ready)


def test_native_file_change_between_passes_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = module._native_rows
    count = 0

    def changed(stage: Path, names: tuple[str, ...]) -> Any:
        nonlocal count
        count += 1
        if count == 2:
            (stage / "bin/quillan").write_bytes(b"tampered after first inspection")
        return original(stage, names)

    monkeypatch.setattr(module, "_native_rows", changed)
    with pytest.raises(NativeSigningRequestError, match="changed"):
        run(ready)
    assert len(ready["calls"]) == 10


@pytest.mark.parametrize("kind", ["plan", "publisher-pip"])
def test_signed_or_installed_verifier_refusal_never_emits_request(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    error = (
        PlanWheelhousePreflightError("unsigned")
        if kind == "plan"
        else PublisherPipPreflightError("pip drift")
    )
    field = (
        "inspect_plan_bound_wheelhouse"
        if kind == "plan"
        else "audit_publisher_bound_pip_candidate"
    )
    monkeypatch.setattr(module, field, lambda *a, **k: (_ for _ in ()).throw(error))
    with pytest.raises(NativeSigningRequestError, match="refused"):
        run(ready)
