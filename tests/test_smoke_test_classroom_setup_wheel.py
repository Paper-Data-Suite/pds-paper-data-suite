from __future__ import annotations

from pathlib import Path

import pytest

from scripts import smoke_test_classroom_setup_wheel


def test_main_invokes_classroom_smoke_with_cli_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"
    observed: list[tuple[Path, Path]] = []

    def fake_smoke(suite_wheel: Path, core_wheel: Path) -> None:
        observed.append((suite_wheel, core_wheel))

    monkeypatch.setattr(
        smoke_test_classroom_setup_wheel,
        "smoke_test_classroom_setup_wheel",
        fake_smoke,
    )

    assert smoke_test_classroom_setup_wheel.main((str(suite), str(core))) == 0
    assert observed == [(suite, core)]
    assert capsys.readouterr().out.strip() == (
        "Classroom setup wheel smoke test passed."
    )


def test_main_returns_failure_when_classroom_smoke_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"

    def fail_smoke(suite_wheel: Path, core_wheel: Path) -> None:
        del suite_wheel, core_wheel
        raise smoke_test_classroom_setup_wheel.ClassroomSetupSmokeTestError(
            "synthetic failure"
        )

    monkeypatch.setattr(
        smoke_test_classroom_setup_wheel,
        "smoke_test_classroom_setup_wheel",
        fail_smoke,
    )

    assert smoke_test_classroom_setup_wheel.main((str(suite), str(core))) == 1
    assert "synthetic failure" in capsys.readouterr().err


def test_isolated_command_env_removes_workspace_and_pythonpath_variants(
    tmp_path: Path,
) -> None:
    result = smoke_test_classroom_setup_wheel._isolated_command_env(
        {
            "PATH": "synthetic",
            "PYTHONPATH": "source-a",
            "PythonPath": "source-b",
            "PDS_WORKSPACE_ROOT": "real-workspace",
        },
        user_home=tmp_path / "user",
    )

    assert result["PATH"] == "synthetic"
    assert all(key.upper() != "PYTHONPATH" for key in result)
    assert all(key.upper() != "PDS_WORKSPACE_ROOT" for key in result)
    assert result["PYTHONNOUSERSITE"] == "1"
    assert result["HOME"] == str(tmp_path / "user")
    assert result["USERPROFILE"] == str(tmp_path / "user")


def test_state_assertion_accepts_minimal_cancelled_setup(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    payload = {
        "root": str(root.resolve()),
        "active_school_year": None,
        "class_count": 0,
        "standards_count": 0,
        "profile_count": 0,
        "calendar_revision": None,
    }

    smoke_test_classroom_setup_wheel._assert_state(
        payload,
        root=root,
        active_school_year=None,
    )


def test_setup_plan_artifact_assertion_rejects_persisted_plan(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "suite-setup-plan.json").write_text("{}", encoding="utf-8")

    with pytest.raises(
        smoke_test_classroom_setup_wheel.ClassroomSetupSmokeTestError,
        match="setup-plan artifact",
    ):
        smoke_test_classroom_setup_wheel._assert_no_setup_plan_artifacts(root)
