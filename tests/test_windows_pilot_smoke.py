from __future__ import annotations

from pathlib import Path

import scripts.run_windows_pilot_smoke as smoke


def test_workflow_plan_covers_release_critical_teacher_surfaces(tmp_path: Path) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"
    artifacts = tmp_path / "artifacts"
    release_tool = tmp_path / "pip.whl"

    steps = smoke._workflow_steps(
        suite,
        core,
        artifacts,
        release_tool,
    )
    labels = tuple(step.label for step in steps)
    scripts = tuple(step.script for step in steps)

    assert labels == (
        "base installed wheel",
        "workspace workflow",
        "shared classroom setup",
        "workspace backup",
        "workspace restore",
        "suite settings",
        "application inventory and launch",
        "combined installed suite",
    )
    assert scripts == (
        "smoke_test_wheel.py",
        "smoke_test_workspace_wheel.py",
        "smoke_test_classroom_setup_wheel.py",
        "smoke_test_workspace_backup_wheel.py",
        "smoke_test_workspace_restore_wheel.py",
        "smoke_test_settings_wheels.py",
        "smoke_test_application_wheels.py",
        "smoke_test_combined_suite_wheels.py",
    )


def test_isolated_env_removes_workspace_and_pythonpath(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "unsafe-source")
    monkeypatch.setenv("PDS_WORKSPACE_ROOT", "real-workspace")
    monkeypatch.setenv("PATH", "system-path")

    env = smoke._isolated_env(tmp_path)

    assert "PYTHONPATH" not in env
    assert "PDS_WORKSPACE_ROOT" not in env
    assert env["PATH"] == "system-path"
    assert env["HOME"] == str(tmp_path)
    assert env["LOCALAPPDATA"] == str(tmp_path / "AppData" / "Local")


def test_candidate_version_remains_development_identity() -> None:
    assert smoke.EXPECTED_CANDIDATE_VERSION == "0.1.0.dev0"


def test_release_artifact_downloader_uses_bundled_contracts() -> None:
    source = Path(smoke.__file__).read_text(encoding="utf-8")

    assert "load_release_compatibility_manifest" in source
    assert "load_release_tooling_contract" in source
    assert "release.sha256" in source
    assert "tool.sha256" in source
    assert "urlretrieve" in source


def test_managed_smoke_requires_real_host_pdftoppm() -> None:
    source = Path(smoke.__file__).read_text(encoding="utf-8")

    assert 'shutil.which("pdftoppm")' in source
    assert '"pdftoppm", "-v"' not in source
    assert "Host Windows PATH does not expose pdftoppm" in source


def test_pilot_runner_never_sets_real_workspace_override() -> None:
    source = Path(smoke.__file__).read_text(encoding="utf-8")

    assert 'env.pop(key, None)' in source
    assert '"PDS_WORKSPACE_ROOT"' in source
    assert "TemporaryDirectory" in source

def test_pilot_supplies_release_tooling_to_doctor_smokes(tmp_path: Path) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"
    artifacts = tmp_path / "artifacts"
    release_tool = tmp_path / "pip.whl"

    steps = smoke._workflow_steps(
        suite,
        core,
        artifacts,
        release_tool,
    )
    by_label = {step.label: step for step in steps}

    assert by_label["base installed wheel"].args[-1] == str(release_tool)
    assert "--release-tool-wheel" in by_label["combined installed suite"].args
    assert str(release_tool) in by_label["combined installed suite"].args
