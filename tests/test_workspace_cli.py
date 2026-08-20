from __future__ import annotations

from pathlib import Path

import pytest

from paper_data_suite.workspace_cli import (
    render_workspace_observation,
    run_workspace_reset,
    run_workspace_set,
    run_workspace_show,
    run_workspace_validate,
)
from paper_data_suite.workspace_setup import (
    WorkspaceMutationError,
    WorkspaceObservation,
    WorkspacePartialSuccessError,
    WorkspacePresentationState,
    WorkspaceResetResult,
    WorkspaceSelectionResult,
    WorkspaceValidationError,
)


def _observation(
    tmp_path: Path,
    *,
    source: str = "saved_config",
    state: WorkspacePresentationState = WorkspacePresentationState.EMPTY_DIRECTORY,
) -> WorkspaceObservation:
    root = tmp_path / "workspace"
    return WorkspaceObservation(
        root=root,
        source=source,
        exists=state is not WorkspacePresentationState.MISSING,
        is_dir=state in {
            WorkspacePresentationState.EMPTY_DIRECTORY,
            WorkspacePresentationState.EXISTING_DIRECTORY,
        },
        is_writable=state is not WorkspacePresentationState.INVALID,
        config_path=tmp_path / "config.json",
        default_root=tmp_path / "default",
        state=state,
        reason="synthetic workspace state",
    )


def test_renderer_prominently_reports_path_source_and_state(tmp_path: Path) -> None:
    observation = _observation(tmp_path)

    output = render_workspace_observation(observation)

    assert "Paper Data Suite workspace" in output
    assert f"  {observation.root}" in output
    assert "saved workspace selection" in output
    assert "empty directory" in output
    assert "Exists: yes" in output
    assert f"Core configuration: {observation.config_path}" in output


def test_renderer_explains_environment_override(tmp_path: Path) -> None:
    output = render_workspace_observation(
        _observation(tmp_path, source="environment")
    )

    assert "environment override" in output
    assert "PDS_WORKSPACE_ROOT controls the active workspace" in output


def test_show_returns_zero_for_missing_informational_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    observation = _observation(
        tmp_path,
        source="default",
        state=WorkspacePresentationState.MISSING,
    )
    monkeypatch.setattr(workspace_cli, "observe_workspace", lambda: observation)

    assert run_workspace_show() == 0
    output = capsys.readouterr().out
    assert "not created yet" in output
    assert "Core default location" in output


def test_show_bounded_failure_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    def fail() -> WorkspaceObservation:
        raise WorkspaceMutationError("Core unavailable")

    monkeypatch.setattr(workspace_cli, "observe_workspace", fail)

    assert run_workspace_show() == 1
    assert "Workspace command failed: Core unavailable" in capsys.readouterr().err


def test_validate_passes_optional_path_and_reports_no_saved_change(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    observation = _observation(tmp_path)
    observed: list[Path | None] = []

    def validate(path: Path | None) -> WorkspaceObservation:
        observed.append(path)
        return observation

    monkeypatch.setattr(workspace_cli, "validate_workspace", validate)
    candidate = tmp_path / "candidate"

    assert run_workspace_validate(candidate) == 0
    assert observed == [candidate]
    output = capsys.readouterr().out
    assert "Workspace validation passed" in output
    assert "No workspace preference was changed." in output


def test_validate_failure_is_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    def fail(path: Path | None) -> WorkspaceObservation:
        raise WorkspaceValidationError("candidate does not exist")

    monkeypatch.setattr(workspace_cli, "validate_workspace", fail)

    assert run_workspace_validate(None) == 1
    assert "candidate does not exist" in capsys.readouterr().err


def test_set_success_reports_created_selection_without_move_claim(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    observation = _observation(tmp_path)
    monkeypatch.setattr(
        workspace_cli,
        "set_workspace",
        lambda path: WorkspaceSelectionResult(
            observation=observation,
            created=True,
            saved=True,
        ),
    )

    assert run_workspace_set(tmp_path / "candidate") == 0
    output = capsys.readouterr().out
    assert "Workspace ready" in output
    assert "Core created and initialized this workspace." in output
    assert "No previous workspace files were moved, copied, or deleted." in output


def test_set_partial_success_is_explicitly_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    resolved = _observation(tmp_path, source="default")

    def fail(path: Path) -> WorkspaceSelectionResult:
        raise WorkspacePartialSuccessError(
            "saved preference failed",
            initialized_root=tmp_path / "initialized",
            resolved=resolved,
        )

    monkeypatch.setattr(workspace_cli, "set_workspace", fail)

    assert run_workspace_set(tmp_path / "candidate") == 1
    error = capsys.readouterr().err
    assert "initialization succeeded" in error
    assert f"Initialized path: {tmp_path / 'initialized'}" in error
    assert "Current resolved workspace" in error


def test_reset_reports_idempotent_clear_and_current_resolution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    observation = _observation(tmp_path, source="environment")
    monkeypatch.setattr(
        workspace_cli,
        "reset_workspace",
        lambda: WorkspaceResetResult(cleared=False, observation=observation),
    )

    assert run_workspace_reset() == 0
    output = capsys.readouterr().out
    assert "No saved workspace preference was set." in output
    assert "No workspace files were deleted." in output
    assert "environment override" in output
