"""Issue #49 Slice 17: explicit isolated-runtime smoke, never launch authority."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from test_issue49_slice11_update_journal import Scene

from paper_data_suite.evergreen_candidate_acceptance import (
    CandidateAcceptanceError,
    accept_verified_candidate_runtime,
)


def _scene(tmp_path: Path) -> Scene:
    layout = "windows" if os.name == "nt" else "posix"
    return Scene(tmp_path, layout=layout)


def _args(scene: Scene) -> dict[str, Any]:
    return dict(
        software_root=scene.manager,
        transaction_id=scene.tx,
        expected_revision=1,
        **scene.inputs(),
    )


def _run_success(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
    assert kwargs["check"] is False
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert Path(kwargs["cwd"]).is_dir()
    assert kwargs["timeout"] == 30
    return subprocess.CompletedProcess(args, 0)


def test_explicit_smoke_checks_two_isolated_commands(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    commands: list[list[str]] = []

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        commands.append(args)
        environment = kwargs["env"]
        assert "PYTHONPATH" not in environment
        assert "PIP_INDEX_URL" not in environment
        assert environment["PIP_NO_INDEX"] == "1"
        assert environment["PDS_EXPECTED_VENV_ROOT"] == str(scene.stage)
        assert environment["HOME"] == str(kwargs["cwd"])
        assert Path(kwargs["cwd"]).parent == scene.manager
        return _run_success(args, **kwargs)

    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run", run):
        observed = accept_verified_candidate_runtime(**_args(scene))
    assert observed.transaction_id == scene.tx
    assert observed.journal_revision == 1
    assert observed.checks == ("isolated_python_identity", "offline_pip_check")
    assert commands[0][1:3] == ["-I", "-c"]
    assert commands[1][1:] == ["-I", "-m", "pip", "check"]
    assert all(command[0].startswith(str(scene.stage)) for command in commands)
    assert not hasattr(observed, "can_launch")
    assert not hasattr(observed, "activated")
    assert scene.load().revision == 1
    assert not list(scene.manager.glob(".pds-candidate-acceptance-*"))
    assert not (scene.manager / "candidate-selection.lock").exists()
    assert not scene.journal.with_suffix(".lock").exists()


def test_candidate_with_tampered_interpreter_never_executes(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    interpreter_name = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    interpreter = scene.stage / interpreter_name
    interpreter.write_bytes(b"replaced binary")
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="byte verification"):
            accept_verified_candidate_runtime(**_args(scene))
    process.assert_not_called()


def test_journal_digest_changed_refuses_execution(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    data = json.loads(scene.journal.read_text())
    data["native_envelope_sha256"] = "0" * 64
    scene.journal.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="evidence mismatch"):
            accept_verified_candidate_runtime(**_args(scene))
    process.assert_not_called()


def test_armed_journal_cannot_run_pre_arming_smoke(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    scene.arm()
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="unarmed"):
            accept_verified_candidate_runtime(**_args(scene))
    process.assert_not_called()


def test_nonzero_runtime_identity_blocks_pip_check(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
        return_value=subprocess.CompletedProcess([], 72),
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="smoke check failed"):
            accept_verified_candidate_runtime(**_args(scene))
    assert process.call_count == 1
    assert scene.load().revision == 1


def test_failed_pip_check_rejects_candidate(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
        side_effect=[
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 1),
        ],
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="smoke check failed"):
            accept_verified_candidate_runtime(**_args(scene))
    assert process.call_count == 2
    assert not list(scene.manager.glob(".pds-candidate-acceptance-*"))


def test_timeout_is_not_accepted(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["candidate"], 30),
    ):
        with pytest.raises(CandidateAcceptanceError, match="timed out"):
            accept_verified_candidate_runtime(**_args(scene))
    assert not list(scene.manager.glob(".pds-candidate-acceptance-*"))


def test_cannot_start_candidate_process(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
        side_effect=OSError("missing"),
    ):
        with pytest.raises(CandidateAcceptanceError, match="could not run"):
            accept_verified_candidate_runtime(**_args(scene))


def test_mutation_during_probe_is_rejected(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    interpreter_name = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    interpreter = scene.stage / interpreter_name

    def mutate(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        interpreter.write_bytes(b"changed while running")
        return _run_success(args, **kwargs)

    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run", mutate
    ):
        with pytest.raises(CandidateAcceptanceError, match="byte verification"):
            accept_verified_candidate_runtime(**_args(scene))


def test_pending_recovery_blocks_runtime_probe(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    (scene.manager / "pending-slot-recovery.json").write_bytes(b"pending")
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="pending recovery"):
            accept_verified_candidate_runtime(**_args(scene))
    process.assert_not_called()


def test_busy_selection_lock_refuses_probe(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    (scene.manager / "candidate-selection.lock").write_text("busy")
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="selection locked"):
            accept_verified_candidate_runtime(**_args(scene))
    process.assert_not_called()


def test_busy_journal_lock_refuses_probe(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    journal_lock = scene.journal.with_suffix(".lock")
    journal_lock.write_text("busy")
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="journal locked"):
            accept_verified_candidate_runtime(**_args(scene))
    process.assert_not_called()
    assert not (scene.manager / "candidate-selection.lock").exists()


@pytest.mark.parametrize("seconds", [0, 61, True, "10"])
def test_invalid_timeout_never_starts_subprocess(
    tmp_path: Path, seconds: object
) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    kwargs = _args(scene)
    kwargs["timeout_seconds"] = seconds
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="invalid"):
            accept_verified_candidate_runtime(**kwargs)
    process.assert_not_called()


def test_rejects_forced_opposite_host_layout(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    opposite = "posix" if os.name == "nt" else "windows"
    args = _args(scene)
    args["layout"] = opposite
    with pytest.raises(CandidateAcceptanceError, match="host layout"):
        accept_verified_candidate_runtime(**args)


def test_missing_candidate_journal_refuses_execution(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="unarmed"):
            accept_verified_candidate_runtime(**_args(scene))
    process.assert_not_called()


def test_byte_hash_binding_refuses_modified_envelope(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    args = _args(scene)
    args["registry_envelope"] += b" "
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(CandidateAcceptanceError, match="evidence mismatch"):
            accept_verified_candidate_runtime(**args)
    process.assert_not_called()
