"""Slice 68: explicit isolated wheel install; no selected or classroom mutation."""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import paper_data_suite.evergreen_plan_stage_installer as module
from paper_data_suite.evergreen_plan_stage_installer import (
    PlanStageInstallError,
    install_authenticated_plan_to_isolated_stage,
)
from paper_data_suite.evergreen_plan_staged_candidate import PlanStagedCandidateError
from paper_data_suite.evergreen_plan_wheelhouse_preflight import (
    PlanWheelhousePreflight,
    PlanWheelhousePreflightError,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    PublisherPipPreflightError,
)

NOW = datetime(2026, 10, 25, 21, tzinfo=UTC)
TX = "f" * 32
PREPARED = b"strictly serialized prepared record"
CONSENT = "INSTALL_AUTHENTICATED_WHEELS_IN_NEW_ISOLATED_STAGE"


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "managed-software"
    classroom = tmp_path / "classroom"
    wheels = root / "signed-wheels"
    wheels.mkdir(parents=True)
    classroom.mkdir()
    (classroom / "student-data.txt").write_text("never modify this")
    (wheels / "immutable-source.txt").write_bytes(b"signatures before installation")
    candidate = root / "candidate-builds" / TX
    signed = (
        SimpleNamespace(
            component_id="core",
            distribution="pds-core",
            version="0.7.0",
            filename="pds_core-0.7.0-py3-none-any.whl",
            sha256="a" * 64,
            publisher_payload_sha256="1" * 64,
            console_script="pds-core",
        ),
        SimpleNamespace(
            component_id="quillan",
            distribution="pds-quillan",
            version="0.10.0",
            filename="pds_quillan-0.10.0-py3-none-any.whl",
            sha256="b" * 64,
            publisher_payload_sha256="2" * 64,
            console_script="quillan",
        ),
    )
    checked = PlanWheelhousePreflight(
        "e" * 32,
        4,
        "c" * 64,
        "d" * 64,
        5,
        f"{sys.version_info.major}.{sys.version_info.minor}",
        sysconfig.get_platform().lower(),
        signed,
        (("packaging", "25.0", "e" * 64),),
    )
    record = SimpleNamespace(
        wheels=(
            SimpleNamespace(filename="pds_core-0.7.0-py3-none-any.whl"),
            SimpleNamespace(filename="pds_quillan-0.10.0-py3-none-any.whl"),
            SimpleNamespace(filename="packaging-25.0-py3-none-any.whl"),
        )
    )
    observed = SimpleNamespace(
        transaction_id=TX,
        stage_root=candidate,
        wheelhouse=wheels,
        registry_payload_sha256="c" * 64,
        lock_payload_sha256="d" * 64,
        pip_inventory_sha256="0" * 64,
        root_console_targets=(
            ("pds-core", "pds-core", "pds_core.cli:main"),
            ("pds-quillan", "quillan", "quillan.cli:main"),
        ),
    )
    snapshot = SimpleNamespace(registry=SimpleNamespace(payload_sha256="c" * 64))
    witnessed = SimpleNamespace(transaction_id="e" * 32, witness_revision=4)
    trust = SimpleNamespace()
    calls: list[str] = []
    argv_calls: list[tuple[str, ...]] = []

    def preflight(*args: Any, **kwargs: Any) -> Any:
        calls.append("signed-preflight")
        assert args == (snapshot, witnessed, wheels)
        assert kwargs["requested_targets"] == {"quillan": "0.10.0"}
        return checked

    def prepared(*args: Any, **kwargs: Any) -> Any:
        calls.append("prepared")
        assert args == (wheels,)
        assert kwargs["transaction_id"] == TX
        return record

    def check_prepared(check: Any, rec: Any) -> None:
        calls.append("match-prepared")
        assert check is checked and rec is record

    def pip_audit(*args: Any, **kwargs: Any) -> Any:
        calls.append("pip-audit")
        assert args == (candidate, wheels)
        assert kwargs["prepared_record"] == PREPARED
        return observed

    def process(argv: list[str], **kwargs: Any) -> Any:
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["check"] is False
        assert kwargs["cwd"] == root
        env = kwargs["env"]
        assert env["PIP_NO_INDEX"] == "1"
        assert env["PIP_CONFIG_FILE"] == os.devnull
        assert "PYTHONPATH" not in env and "PIP_INDEX_URL" not in env
        assert not any(arg.startswith("https://") for arg in argv)
        assert not any("--index-url" in arg for arg in argv)
        argv_calls.append(tuple(argv))
        if argv[2] == "venv":
            calls.append("venv")
            path = Path(argv[-1])
            assert path == candidate and "--without-pip" in argv
            python_file = path / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            python_file.parent.mkdir(parents=True)
            python_file.write_bytes(b"copied Python executable placeholder")
        elif argv[2] == "pip":
            calls.append("pip")
            assert argv[3] == "--python"
            assert "--no-index" in argv
            assert "--no-deps" in argv
            assert "--no-cache-dir" in argv
            assert "--no-compile" in argv
            assert set(argv[-3:]) == {
                str(wheels / item.filename) for item in record.wheels
            }
        else:
            raise AssertionError("unapproved installer command")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module, "CatalogSnapshot", SimpleNamespace)
    monkeypatch.setattr(module, "WitnessSelectedStageObservation", SimpleNamespace)
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    monkeypatch.setattr(module, "inspect_plan_bound_wheelhouse", preflight)
    monkeypatch.setattr(module, "prepare_composition_record", prepared)
    monkeypatch.setattr(module, "_match_prepared", check_prepared)
    monkeypatch.setattr(module, "serialize_prepared_record", lambda rec: PREPARED)
    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", pip_audit)
    monkeypatch.setattr(module.subprocess, "run", process)
    return dict(
        args=dict(
            snapshot=snapshot,
            witnessed=witnessed,
            software_root=root,
            classroom_workspace=classroom,
            wheelhouse=wheels,
            transaction_id=TX,
            explicit_consent=CONSENT,
            requested_targets={"quillan": "0.10.0"},
            python_minor=checked.python_minor,
            platform_tag=checked.platform_tag,
            registry_envelope=b"registry",
            lock_envelope=b"lock",
            module_envelopes={"core": b"publisher1", "quillan": b"publisher2"},
            trust=trust,
            now=NOW,
        ),
        calls=calls,
        process=process,
        argv_calls=argv_calls,
        checked=checked,
        observed=observed,
        root=root,
        classroom=classroom,
        wheels=wheels,
        candidate=candidate,
    )


def run(ready: dict[str, Any], **changes: Any) -> Any:
    return install_authenticated_plan_to_isolated_stage(**{**ready["args"], **changes})


def test_exact_offline_wheel_install_to_new_unselected_candidate(
    ready: dict[str, Any],
) -> None:
    classroom = ready["classroom"] / "student-data.txt"
    wheel = ready["wheels"] / "immutable-source.txt"
    before = classroom.read_bytes(), wheel.read_bytes()
    with patch("socket.create_connection", side_effect=AssertionError("network")):
        result = run(ready)
    assert result.stage_root == ready["candidate"]
    assert result.transaction_id == TX
    assert result.prepared_record == PREPARED
    assert result.pip_inventory_sha256 == "0" * 64
    assert result.status == "PIP_CANDIDATE_INSTALLED_NATIVE_EVIDENCE_STILL_REQUIRED"
    assert "NO_ACTIVE_RECEIPT" in result.authority
    assert ready["calls"] == [
        "signed-preflight",
        "prepared",
        "match-prepared",
        "signed-preflight",
        "venv",
        "pip",
        "pip-audit",
        "signed-preflight",
    ]
    assert len(ready["argv_calls"]) == 2
    assert not (ready["root"] / "candidate-selection.json").exists()
    assert not (ready["root"] / "candidate-selection.lock").exists()
    assert (classroom.read_bytes(), wheel.read_bytes()) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"explicit_consent": ""},
        {"explicit_consent": "yes"},
        {"transaction_id": "x" * 32},
        {"transaction_id": "../" + TX},
        {"python_minor": "3.99"},
        {"platform_tag": "win_fake"},
        {"trust": None},
        {"module_envelopes": {"quillan": "not bytes"}},
        {"now": datetime(2026, 10, 25)},
    ],
)
def test_missing_authority_refuses_before_files_or_execution(
    ready: dict[str, Any], changes: dict[str, Any]
) -> None:
    with pytest.raises(PlanStageInstallError, match="inputs|consent"):
        run(ready, **changes)
    assert ready["calls"] == []
    assert not ready["candidate"].exists()


def test_existing_candidate_refuses_before_execution(ready: dict[str, Any]) -> None:
    ready["candidate"].mkdir(parents=True)
    with pytest.raises(PlanStageInstallError, match="already exists"):
        run(ready)
    assert ready["calls"] == []


def test_wheelhouse_outside_software_refuses(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanStageInstallError):
        run(ready, wheelhouse=ready["classroom"])
    assert ready["calls"] == []


def test_workspace_same_as_software_refuses(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanStageInstallError):
        run(ready, classroom_workspace=ready["root"])
    assert ready["calls"] == []


def test_existing_selection_lock_refuses_without_writes(ready: dict[str, Any]) -> None:
    (ready["root"] / "candidate-selection.lock").write_bytes(b"another operation")
    with pytest.raises(PlanStageInstallError, match="refused"):
        run(ready)
    assert ready["calls"] == []
    assert not ready["candidate"].exists()


def test_invalid_signed_plan_refuses_before_directory_creation(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "inspect_plan_bound_wheelhouse",
        lambda *a, **k: (_ for _ in ()).throw(PlanWheelhousePreflightError("bad")),
    )
    with pytest.raises(PlanStageInstallError):
        run(ready)
    assert not ready["candidate"].exists()


def test_wrong_signed_baseline_refuses_before_directory_creation(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ready["checked"]
    monkeypatch.setattr(
        module,
        "inspect_plan_bound_wheelhouse",
        lambda *a, **k: replace(original, baseline_witness_revision=999),
    )
    with pytest.raises(PlanStageInstallError, match="baseline"):
        run(ready)
    assert not ready["candidate"].exists()


def test_signed_wheels_changed_between_preflight_refuses_before_execution(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ready["checked"]
    counter = 0

    def drift(*args: Any, **kwargs: Any) -> Any:
        nonlocal counter
        counter += 1
        return replace(original, signed_lock_revision=123) if counter == 2 else original

    monkeypatch.setattr(module, "inspect_plan_bound_wheelhouse", drift)
    with pytest.raises(PlanStageInstallError, match="changed"):
        run(ready)
    assert not ready["candidate"].exists()
    assert "venv" not in ready["calls"]


def test_failed_prepared_correspondence_refuses_before_execution(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "_match_prepared",
        lambda *a, **k: (_ for _ in ()).throw(PlanStagedCandidateError("no match")),
    )
    with pytest.raises(PlanStageInstallError):
        run(ready)
    assert not ready["candidate"].exists()
    assert "venv" not in ready["calls"]


@pytest.mark.parametrize("step", ["venv", "pip"])
def test_subprocess_failure_never_selects_stage(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    normal = ready["process"]

    def fail(argv: list[str], **kwargs: Any) -> Any:
        if argv[2] == step:
            return SimpleNamespace(returncode=1)
        return normal(argv, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", fail)
    with pytest.raises(PlanStageInstallError, match="subprocess failed"):
        run(ready)
    assert not (ready["root"] / "candidate-selection.json").exists()
    assert ready["candidate"].exists()  # incomplete stage retained, NOT selected
    assert not (ready["root"] / "candidate-selection.lock").exists()


def test_missing_candidate_python_refuses_without_pip_execution(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_venv(argv: list[str], **kwargs: Any) -> Any:
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_venv)
    with pytest.raises(PlanStageInstallError, match="Python missing"):
        run(ready)
    assert not (ready["root"] / "candidate-selection.json").exists()


def test_pip_audit_failure_leaves_only_unselected_incomplete_stage(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refusal(*args: Any, **kwargs: Any) -> Any:
        raise PublisherPipPreflightError("unverified")

    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", refusal)
    with pytest.raises(PlanStageInstallError, match="refused"):
        run(ready)
    assert ready["candidate"].exists()
    assert not (ready["root"] / "candidate-selection.json").exists()


def test_audit_mismatch_refuses_complete_candidate(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "audit_publisher_bound_pip_candidate",
        lambda *a, **k: SimpleNamespace(
            **{
                **ready["observed"].__dict__,
                "pip_inventory_sha256": "z" * 64,
                "transaction_id": "x" * 32,
            }
        ),
    )
    with pytest.raises(PlanStageInstallError, match="differs"):
        run(ready)
    assert not (ready["root"] / "candidate-selection.json").exists()


def test_signed_wheels_changed_during_install_refuses_result(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ready["checked"]
    counter = 0

    def drift(*args: Any, **kwargs: Any) -> Any:
        nonlocal counter
        counter += 1
        return replace(original, signed_lock_revision=77) if counter == 3 else original

    monkeypatch.setattr(module, "inspect_plan_bound_wheelhouse", drift)
    with pytest.raises(PlanStageInstallError, match="changed during install"):
        run(ready)
    assert not (ready["root"] / "candidate-selection.json").exists()


def test_stage_result_contains_no_launch_or_active_receipt_method(
    ready: dict[str, Any],
) -> None:
    result = run(ready)
    for method in ("activate", "launch", "commit", "rollback", "switch"):
        assert not hasattr(result, method)
