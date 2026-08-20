from __future__ import annotations

from pathlib import Path

import pytest

from scripts import smoke_test_workspace_wheel


def test_main_invokes_workspace_smoke_with_cli_paths(
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
        smoke_test_workspace_wheel,
        "smoke_test_workspace_wheel",
        fake_smoke,
    )

    assert smoke_test_workspace_wheel.main((str(suite), str(core))) == 0
    assert observed == [(suite, core)]
    assert capsys.readouterr().out.strip() == "Workspace wheel smoke test passed."


def test_main_returns_failure_when_workspace_smoke_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"

    def fail_smoke(suite_wheel: Path, core_wheel: Path) -> None:
        del suite_wheel, core_wheel
        raise smoke_test_workspace_wheel.WorkspaceSmokeTestError("synthetic failure")

    monkeypatch.setattr(
        smoke_test_workspace_wheel,
        "smoke_test_workspace_wheel",
        fail_smoke,
    )

    assert smoke_test_workspace_wheel.main((str(suite), str(core))) == 1
    assert "synthetic failure" in capsys.readouterr().err


def test_isolated_command_env_removes_workspace_and_pythonpath_variants(
    tmp_path: Path,
) -> None:
    result = smoke_test_workspace_wheel._isolated_command_env(
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
    assert result["APPDATA"] == str(tmp_path / "user" / "AppData" / "Roaming")
    assert result["XDG_CONFIG_HOME"] == str(tmp_path / "user" / ".config")


def test_show_output_assertion_requires_path_and_source(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    output = "\n".join(
        (
            "Paper Data Suite workspace",
            str(root),
            "saved workspace selection",
            "Core configuration:",
            "Core default workspace:",
        )
    )

    smoke_test_workspace_wheel._assert_show_output(
        output,
        root=root,
        source_label="saved workspace selection",
    )


def test_show_output_assertion_rejects_wrong_source(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with pytest.raises(
        smoke_test_workspace_wheel.WorkspaceSmokeTestError,
        match="missing expected content",
    ):
        smoke_test_workspace_wheel._assert_show_output(
            f"Paper Data Suite workspace\n{root}\nCore configuration:\n"
            "Core default workspace:\n",
            root=root,
            source_label="saved workspace selection",
        )


def test_workspace_initialized_assertion_requires_core_directories(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    for relative in (
        ".pds",
        "classes",
        "scans_inbox",
        "scans",
        "scans/source",
        "scans/review",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    smoke_test_workspace_wheel._assert_workspace_initialized(root)


def test_workspace_initialized_assertion_rejects_incomplete_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(
        smoke_test_workspace_wheel.WorkspaceSmokeTestError,
        match="missing expected directories",
    ):
        smoke_test_workspace_wheel._assert_workspace_initialized(root)
