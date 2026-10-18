"""Issue #49 Slice 18: exact-code inventory and opt-in public import checks."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from test_issue49_slice11_update_journal import Scene

from paper_data_suite.evergreen_public_contract_acceptance import (
    PublicContractAcceptanceError,
    accept_verified_candidate_public_contracts,
)


def _scene(tmp_path: Path) -> Scene:
    return Scene(tmp_path, layout="windows" if os.name == "nt" else "posix")


def _site(scene: Scene) -> Path:
    if os.name == "nt":
        return scene.stage / "Lib/site-packages"
    python = os.sys.version_info
    return scene.stage / (f"lib/python{python.major}.{python.minor}/site-packages")


def _kwargs(scene: Scene) -> dict[str, Any]:
    return dict(
        software_root=scene.manager,
        transaction_id=scene.tx,
        expected_revision=1,
        **scene.inputs(),
    )


def _success(args: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
    assert kw["stdin"] == subprocess.DEVNULL
    assert kw["stdout"] == subprocess.DEVNULL
    assert kw["stderr"] == subprocess.DEVNULL
    assert kw["check"] is False
    assert kw["timeout"] == 30
    return subprocess.CompletedProcess(args, 0)


def test_public_imports_are_opt_in_no_launch_permission(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    calls: list[tuple[str, ...]] = []

    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        env = kw["env"]
        assert env["PDS_EXPECTED_OWNER"] == "demo-app"
        assert env["PDS_EXPECTED_CONSOLE"] == "demo"
        assert env["PDS_EXPECTED_TARGET"] == "demo_app.cli:main"
        assert Path(env["PDS_EXPECTED_SITE_PACKAGES"]).is_dir()
        assert Path(env["HOME"]) == Path(kw["cwd"])
        assert env["PIP_NO_INDEX"] == "1"
        assert "PYTHONPATH" not in env
        assert args[1:5] == ["-I", "-B", "-c", args[4]]
        assert "entry_points" in args[4]
        assert "callable" in args[4]
        assert Path(kw["cwd"]).parent == scene.manager
        calls.append(tuple(args))
        return _success(args, **kw)

    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run", run):
        result = accept_verified_candidate_public_contracts(**_kwargs(scene))
    assert len(calls) == 1
    assert result.transaction_id == scene.tx
    assert result.journal_revision == 1
    assert result.console_targets == (("demo-app", "demo", "demo_app.cli:main"),)
    assert len(result.site_inventory_sha256) == 64
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "active_receipt")
    assert scene.load().revision == 1
    assert not list(scene.manager.glob(".pds-public-contract-*"))
    assert not (scene.manager / "candidate-selection.lock").exists()


def test_edit_installed_package_before_import_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    source = _site(scene) / "demo_app/__init__.py"
    source.write_bytes(source.read_bytes() + b"# changed")
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(PublicContractAcceptanceError, match="source bytes"):
            accept_verified_candidate_public_contracts(**_kwargs(scene))
    process.assert_not_called()


def test_unexpected_staged_python_file_never_imported(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    folder = _site(scene)
    (folder / "unowned.py").write_text("import evil\n")
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(PublicContractAcceptanceError, match="inventory"):
            accept_verified_candidate_public_contracts(**_kwargs(scene))
    process.assert_not_called()


def test_installed_record_modified_without_wheel_change_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    folder = _site(scene)
    record = folder / "demo_app-1.0.0.dist-info/RECORD"
    record.write_bytes(record.read_bytes().replace(b"sha256=", b"sha256=z", 1))
    with pytest.raises(PublicContractAcceptanceError, match="preflight"):
        accept_verified_candidate_public_contracts(**_kwargs(scene))


def test_changed_native_binary_never_imported(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    python = scene.stage / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.write_bytes(b"wrong")
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(PublicContractAcceptanceError, match="preflight"):
            accept_verified_candidate_public_contracts(**_kwargs(scene))
    process.assert_not_called()


def test_changed_source_during_import_is_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    folder = _site(scene)
    source = folder / "demo_core/__init__.py"

    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        source.write_bytes(source.read_bytes() + b"changed")
        return _success(args, **kw)

    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run", run):
        with pytest.raises(PublicContractAcceptanceError, match="source bytes"):
            accept_verified_candidate_public_contracts(**_kwargs(scene))


def test_modified_journal_during_import_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()

    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        record = json.loads(scene.journal.read_bytes())
        record["revision"] = 99
        scene.journal.write_text(json.dumps(record))
        return _success(args, **kw)

    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run", run):
        with pytest.raises(PublicContractAcceptanceError, match="preflight|journal"):
            accept_verified_candidate_public_contracts(**_kwargs(scene))


def test_pending_recovery_refuses_execution(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    (scene.manager / "pending-slot-recovery.json").write_text("pending")
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(PublicContractAcceptanceError, match="pending recovery"):
            accept_verified_candidate_public_contracts(**_kwargs(scene))
    process.assert_not_called()


def test_armed_candidate_refuses_public_import(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    scene.arm()
    with pytest.raises(PublicContractAcceptanceError, match="unarmed"):
        accept_verified_candidate_public_contracts(**_kwargs(scene))


def test_journal_evidence_tamper_refuses_execution(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    args = _kwargs(scene)
    args["lock_envelope"] += b" "
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(PublicContractAcceptanceError, match="journal bytes"):
            accept_verified_candidate_public_contracts(**args)
    process.assert_not_called()


def test_import_failure_refuses_candidate(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
        return_value=subprocess.CompletedProcess([], 75),
    ):
        with pytest.raises(PublicContractAcceptanceError, match="import failed"):
            accept_verified_candidate_public_contracts(**_kwargs(scene))
    assert scene.load().revision == 1


def test_import_timeout_refuses_candidate(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["python"], 30),
    ):
        with pytest.raises(PublicContractAcceptanceError, match="import failed"):
            accept_verified_candidate_public_contracts(**_kwargs(scene))


def test_runtime_spawn_failure_refuses_candidate(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
        side_effect=OSError("cannot start"),
    ):
        with pytest.raises(PublicContractAcceptanceError, match="import failed"):
            accept_verified_candidate_public_contracts(**_kwargs(scene))


def test_busy_journal_lock_blocks_import(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    scene.journal.with_suffix(".lock").write_text("busy")
    with pytest.raises(PublicContractAcceptanceError, match="journal unavailable"):
        accept_verified_candidate_public_contracts(**_kwargs(scene))


def test_busy_selection_lock_blocks_import(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    (scene.manager / "candidate-selection.lock").write_text("busy")
    with pytest.raises(PublicContractAcceptanceError, match="selection locked"):
        accept_verified_candidate_public_contracts(**_kwargs(scene))


@pytest.mark.parametrize("seconds", [0, 61, True, "5"])
def test_invalid_timeout_refuses_import(tmp_path: Path, seconds: object) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    args = _kwargs(scene)
    args["timeout_seconds"] = seconds
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run"
    ) as process:
        with pytest.raises(PublicContractAcceptanceError, match="invalid"):
            accept_verified_candidate_public_contracts(**args)
    process.assert_not_called()


def test_wrong_host_layout_refuses_import(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    args = _kwargs(scene)
    args["layout"] = "posix" if os.name == "nt" else "windows"
    with pytest.raises(PublicContractAcceptanceError, match="invalid"):
        accept_verified_candidate_public_contracts(**args)


def test_missing_journal_refuses_import(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    with pytest.raises(PublicContractAcceptanceError, match="unarmed"):
        accept_verified_candidate_public_contracts(**_kwargs(scene))


def test_rejects_non_bytes_evidence(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    args = _kwargs(scene)
    args["registry_envelope"] = "not-bytes"
    with pytest.raises(PublicContractAcceptanceError, match="invalid"):
        accept_verified_candidate_public_contracts(**args)


def test_no_changes_to_existing_installation_on_success(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    scene.begin()
    before = {
        p.relative_to(scene.stage): p.read_bytes()
        for p in scene.stage.rglob("*")
        if p.is_file()
    }
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
        side_effect=_success,
    ):
        accept_verified_candidate_public_contracts(**_kwargs(scene))
    assert before == {
        p.relative_to(scene.stage): p.read_bytes()
        for p in scene.stage.rglob("*")
        if p.is_file()
    }
    assert not (scene.manager / "candidate-selection.json").exists()
    assert not (scene.manager / "active.json").exists()
