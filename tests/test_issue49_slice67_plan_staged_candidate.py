"""Slice 67: signed plan, prepared record and installed stage must agree."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import paper_data_suite.evergreen_plan_staged_candidate as module
from paper_data_suite.evergreen_catalog_stage_correlation import (
    CatalogStageCorrelation,
    CatalogStageCorrelationError,
    CatalogStagedWheel,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    PreparedWheel,
    UnverifiedPreparedRecord,
    parse_unverified_prepared_record,
    serialize_prepared_record,
)
from paper_data_suite.evergreen_plan_staged_candidate import (
    PlanStagedCandidateError,
    inspect_plan_bound_staged_candidate,
)
from paper_data_suite.evergreen_plan_wheelhouse_preflight import (
    PlanWheelhousePreflight,
    PlanWheelhousePreflightError,
)

NOW = datetime(2026, 10, 25, 21, tzinfo=UTC)
TX = "f" * 32
BASELINE = "e" * 32
REGISTRY = "a" * 64
LOCK = "b" * 64
PIP = "c" * 64
NATIVE = "d" * 64


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "managed-software"
    classroom = tmp_path / "classroom"
    stage = root / "candidate" / "stage"
    wheelhouse = root / "candidate" / "wheelhouse"
    stage.mkdir(parents=True)
    wheelhouse.mkdir(parents=True)
    classroom.mkdir()
    (classroom / "student-work.txt").write_text("unchanged")
    (stage / "test-stage.txt").write_text("do not mutate")
    (wheelhouse / "test-wheel.txt").write_text("do not mutate")
    pds = (
        SimpleNamespace(
            component_id="core",
            distribution="pds-core",
            version="0.7.0",
            filename="pds_core-0.7.0-py3-none-any.whl",
            sha256="1" * 64,
            publisher_payload_sha256="3" * 64,
        ),
        SimpleNamespace(
            component_id="quillan",
            distribution="pds-quillan",
            version="0.10.0",
            filename="pds_quillan-0.10.0-py3-none-any.whl",
            sha256="2" * 64,
            publisher_payload_sha256="4" * 64,
        ),
    )
    external = (("packaging", "25.0", "5" * 64),)
    checked = PlanWheelhousePreflight(
        BASELINE,
        3,
        REGISTRY,
        LOCK,
        4,
        "3.11",
        "win_arm64",
        pds,
        external,
    )
    record = UnverifiedPreparedRecord(
        TX,
        NOW,
        "3.11",
        "win_arm64",
        REGISTRY,
        "6" * 64,
        LOCK,
        4,
        ("pds-core", "pds-quillan"),
        (
            PreparedWheel("pds-core", "0.7.0", pds[0].filename, "1" * 64),
            PreparedWheel("pds-quillan", "0.10.0", pds[1].filename, "2" * 64),
            PreparedWheel(
                "packaging", "25.0", "packaging-25.0-py3-none-any.whl", "5" * 64
            ),
        ),
        (("pds-quillan", "pds-core"),),
    )
    prepared = serialize_prepared_record(record)
    stage_evidence = CatalogStageCorrelation(
        TX,
        REGISTRY,
        PIP,
        NATIVE,
        tuple(
            CatalogStagedWheel(
                item.component_id,
                item.distribution,
                item.version,
                item.sha256,
                item.publisher_payload_sha256,
            )
            for item in pds
        ),
    )
    witnessed = SimpleNamespace(transaction_id=BASELINE, witness_revision=3)
    snapshot = SimpleNamespace(registry=SimpleNamespace(payload_sha256=REGISTRY))
    calls: list[str] = []

    def inspect_plan(*args: Any, **kwargs: Any) -> PlanWheelhousePreflight:
        calls.append("plan")
        assert args == (snapshot, witnessed, wheelhouse)
        assert kwargs["requested_targets"] == {"quillan": "0.10.0"}
        return checked

    def inspect_prepared(
        raw: bytes, path: Path, **kwargs: Any
    ) -> UnverifiedPreparedRecord:
        calls.append("prepared")
        assert raw == prepared and path == wheelhouse
        return parse_unverified_prepared_record(raw)

    def inspect_stage(*args: Any, **kwargs: Any) -> CatalogStageCorrelation:
        calls.append("stage")
        assert args == (snapshot, stage, wheelhouse)
        assert kwargs["prepared_record"] == prepared
        return stage_evidence

    monkeypatch.setattr(module, "CatalogSnapshot", SimpleNamespace)
    monkeypatch.setattr(module, "WitnessSelectedStageObservation", SimpleNamespace)
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    monkeypatch.setattr(module, "inspect_plan_bound_wheelhouse", inspect_plan)
    monkeypatch.setattr(
        module, "verify_prepared_record_against_wheelhouse", inspect_prepared
    )
    monkeypatch.setattr(module, "inspect_catalog_bound_staged_bytes", inspect_stage)
    args = dict(
        snapshot=snapshot,
        witnessed=witnessed,
        software_root=root,
        classroom_workspace=classroom,
        stage_root=stage,
        wheelhouse=wheelhouse,
        prepared_record=prepared,
        requested_targets={"quillan": "0.10.0"},
        python_minor="3.11",
        platform_tag="win_arm64",
        registry_envelope=b"signed registry",
        lock_envelope=b"signed lock",
        module_envelopes={"core": b"signed core", "quillan": b"signed quillan"},
        native_envelope=b"signed native",
        trust=SimpleNamespace(),
        now=NOW,
    )
    return {
        "args": args,
        "checked": checked,
        "record": record,
        "stage_evidence": stage_evidence,
        "calls": calls,
        "root": root,
        "classroom": classroom,
        "stage": stage,
        "wheelhouse": wheelhouse,
    }


def run(ready: dict[str, Any], **changes: Any) -> Any:
    return inspect_plan_bound_staged_candidate(**{**ready["args"], **changes})


def test_crosscheck_twice_without_execution_or_mutation(ready: dict[str, Any]) -> None:
    root = ready["root"]
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with (
        patch("subprocess.run", side_effect=AssertionError("execute")),
        patch("socket.create_connection", side_effect=AssertionError("network")),
    ):
        result = run(ready)
    assert result.transaction_id == TX
    assert result.baseline_transaction_id == BASELINE
    assert result.baseline_witness_revision == 3
    assert result.signed_lock_payload_sha256 == LOCK
    assert result.pip_inventory_sha256 == PIP
    assert result.native_payload_sha256 == NATIVE
    assert result.external_wheels == (("packaging", "25.0", "5" * 64),)
    assert result.status == "PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE"
    assert "NO_ACTIVE_INSTALL" in result.authority
    assert ready["calls"] == ["plan", "prepared", "stage"] * 2
    assert before == {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    assert (ready["classroom"] / "student-work.txt").read_text() == "unchanged"
    for method in ("install", "activate", "launch", "commit", "stage", "rollback"):
        assert not hasattr(result, method)


@pytest.mark.parametrize(
    "field,value",
    [
        ("snapshot", object()),
        ("software_root", "not-a-path"),
        ("stage_root", "not-a-path"),
        ("wheelhouse", None),
        ("trust", None),
        ("prepared_record", "not bytes"),
        ("module_envelopes", {}),
        ("now", datetime(2026, 10, 25, 21)),
        ("layout", "invalid"),
    ],
)
def test_invalid_inputs_refuse_before_audit(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(PlanStagedCandidateError, match="inputs"):
        run(ready, **{field: value})
    assert ready["calls"] == []


def test_outside_software_root_refuses(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanStagedCandidateError, match="refused"):
        run(ready, stage_root=ready["classroom"])
    assert ready["calls"] == []


def test_stage_and_wheels_must_be_distinct(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanStagedCandidateError, match="isolated"):
        run(ready, stage_root=ready["wheelhouse"])
    assert ready["calls"] == []


def test_staging_cannot_overlap_classroom_workspace(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanStagedCandidateError, match="refused"):
        run(ready, classroom_workspace=ready["root"])
    assert ready["calls"] == []


def test_signed_plan_baseline_disagreement_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ready["checked"]
    monkeypatch.setattr(
        module,
        "inspect_plan_bound_wheelhouse",
        lambda *args, **kwargs: replace(original, baseline_witness_revision=99),
    )
    with pytest.raises(PlanStagedCandidateError, match="baseline"):
        run(ready)


def test_prepared_wheel_disagreement_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prior = module.verify_prepared_record_against_wheelhouse

    def wrong(*args: Any, **kwargs: Any) -> UnverifiedPreparedRecord:
        record = prior(*args, **kwargs)
        wheels = record.wheels[:-1]
        return replace(record, wheels=wheels)

    monkeypatch.setattr(module, "verify_prepared_record_against_wheelhouse", wrong)
    with pytest.raises(PlanStagedCandidateError, match="prepared transaction"):
        run(ready)


def test_prepared_lock_disagreement_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prior = module.verify_prepared_record_against_wheelhouse
    monkeypatch.setattr(
        module,
        "verify_prepared_record_against_wheelhouse",
        lambda *a, **k: replace(prior(*a, **k), lock_payload_sha256="0" * 64),
    )
    with pytest.raises(PlanStagedCandidateError, match="prepared transaction"):
        run(ready)


def test_staged_module_digest_disagreement_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ready["stage_evidence"]
    modules = list(original.modules)
    modules[0] = replace(modules[0], wheel_sha256="0" * 64)
    monkeypatch.setattr(
        module,
        "inspect_catalog_bound_staged_bytes",
        lambda *args, **kwargs: replace(original, modules=tuple(modules)),
    )
    with pytest.raises(PlanStagedCandidateError, match="staged bytes"):
        run(ready)


def test_staged_transaction_disagreement_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ready["stage_evidence"]
    monkeypatch.setattr(
        module,
        "inspect_catalog_bound_staged_bytes",
        lambda *args, **kwargs: replace(original, transaction_id="0" * 32),
    )
    with pytest.raises(PlanStagedCandidateError, match="staged bytes"):
        run(ready)


def test_changed_second_stage_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = module.inspect_catalog_bound_staged_bytes
    calls = 0

    def changed(*args: Any, **kwargs: Any) -> CatalogStageCorrelation:
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            return replace(result, pip_inventory_sha256="0" * 64)
        return result

    monkeypatch.setattr(module, "inspect_catalog_bound_staged_bytes", changed)
    with pytest.raises(PlanStagedCandidateError, match="changed during audit"):
        run(ready)


def test_signed_wheelhouse_refusal_propagates(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise PlanWheelhousePreflightError("untrusted")

    monkeypatch.setattr(module, "inspect_plan_bound_wheelhouse", fail)
    with pytest.raises(PlanStagedCandidateError, match="refused"):
        run(ready)


def test_prepared_refusal_propagates(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise PreparedRecordError("tampered")

    monkeypatch.setattr(module, "verify_prepared_record_against_wheelhouse", fail)
    with pytest.raises(PlanStagedCandidateError, match="refused"):
        run(ready)


def test_staged_native_refusal_propagates(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise CatalogStageCorrelationError("native digest")

    monkeypatch.setattr(module, "inspect_catalog_bound_staged_bytes", fail)
    with pytest.raises(PlanStagedCandidateError, match="refused"):
        run(ready)
