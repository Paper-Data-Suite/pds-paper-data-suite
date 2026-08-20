from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from paper_data_suite.workspace_cli import run_workspace_setup
from paper_data_suite.workspace_setup import (
    WorkspaceMutationError,
    WorkspaceObservation,
    WorkspacePartialSuccessError,
    WorkspacePresentationState,
    WorkspaceSelectionResult,
)


def _observation(
    tmp_path: Path,
    *,
    root: Path | None = None,
    source: str = "default",
    state: WorkspacePresentationState = WorkspacePresentationState.MISSING,
) -> WorkspaceObservation:
    actual_root = root or (tmp_path / "workspace")
    exists = state is not WorkspacePresentationState.MISSING
    is_dir = state in {
        WorkspacePresentationState.EMPTY_DIRECTORY,
        WorkspacePresentationState.EXISTING_DIRECTORY,
    }
    return WorkspaceObservation(
        root=actual_root,
        source=source,
        exists=exists,
        is_dir=is_dir,
        is_writable=state is not WorkspacePresentationState.INVALID,
        config_path=tmp_path / "config.json",
        default_root=tmp_path / "default",
        state=state,
        reason="synthetic workspace state",
    )


def _reader(*responses: str) -> Callable[[str], str]:
    items: Iterator[str] = iter(responses)

    def read(_prompt: str) -> str:
        return next(items)

    return read


def test_setup_uses_missing_current_path_only_after_use_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    current = _observation(tmp_path)
    ready = _observation(
        tmp_path,
        root=current.root,
        source="saved_config",
        state=WorkspacePresentationState.EMPTY_DIRECTORY,
    )
    selected: list[Path] = []
    monkeypatch.setattr(workspace_cli, "observe_workspace", lambda path=None: current)

    def set_candidate(path: Path) -> WorkspaceSelectionResult:
        selected.append(path)
        return WorkspaceSelectionResult(
            observation=ready,
            created=True,
            saved=True,
        )

    monkeypatch.setattr(workspace_cli, "set_workspace", set_candidate)

    assert run_workspace_setup(_reader("1", "USE")) == 0
    assert selected == [current.root]
    output = capsys.readouterr().out
    assert "This folder does not exist yet." in output
    assert "Core will create and initialize the workspace." in output
    assert "No school year or classroom setup was changed." in output
    assert "Next: pds doctor" in output


def test_setup_custom_empty_folder_is_previewed_before_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    current = _observation(tmp_path)
    candidate_root = tmp_path / "chosen"
    candidate = _observation(
        tmp_path,
        root=candidate_root,
        source="explicit",
        state=WorkspacePresentationState.EMPTY_DIRECTORY,
    )
    ready = _observation(
        tmp_path,
        root=candidate_root,
        source="saved_config",
        state=WorkspacePresentationState.EMPTY_DIRECTORY,
    )
    selected: list[Path] = []

    def observe(path: Path | None = None) -> WorkspaceObservation:
        return current if path is None else candidate

    def set_candidate(path: Path) -> WorkspaceSelectionResult:
        selected.append(path)
        return WorkspaceSelectionResult(ready, created=False, saved=True)

    monkeypatch.setattr(workspace_cli, "observe_workspace", observe)
    monkeypatch.setattr(workspace_cli, "set_workspace", set_candidate)

    assert run_workspace_setup(
        _reader("2", str(candidate_root), "USE")
    ) == 0
    assert selected == [candidate_root]
    output = capsys.readouterr().out
    assert "This folder exists and is empty." in output
    assert "An empty directory is not an invalid workspace." in output


def test_setup_existing_nonempty_folder_gets_strong_adoption_warning(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    candidate_root = tmp_path / "existing"
    current = _observation(tmp_path)
    candidate = _observation(
        tmp_path,
        root=candidate_root,
        source="explicit",
        state=WorkspacePresentationState.EXISTING_DIRECTORY,
    )
    ready = _observation(
        tmp_path,
        root=candidate_root,
        source="saved_config",
        state=WorkspacePresentationState.EXISTING_DIRECTORY,
    )
    selected: list[Path] = []
    monkeypatch.setattr(
        workspace_cli,
        "observe_workspace",
        lambda path=None: current if path is None else candidate,
    )
    monkeypatch.setattr(
        workspace_cli,
        "set_workspace",
        lambda path: (
            selected.append(path)
            or WorkspaceSelectionResult(ready, created=False, saved=True)
        ),
    )

    assert run_workspace_setup(
        _reader("2", str(candidate_root), "USE")
    ) == 0
    assert selected == [candidate_root]
    output = capsys.readouterr().out
    assert "already contains files or directories" in output
    assert "Existing contents will not be moved or deleted." in output
    assert "Confirm only if you intend to adopt this existing directory." in output


@pytest.mark.parametrize("response", ["", "q", "Q"])
def test_setup_initial_menu_cancellation_is_zero_and_does_not_select(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    response: str,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    current = _observation(tmp_path)
    selected: list[Path] = []
    monkeypatch.setattr(workspace_cli, "observe_workspace", lambda path=None: current)
    monkeypatch.setattr(
        workspace_cli,
        "set_workspace",
        lambda path: selected.append(path),  # type: ignore[func-returns-value]
    )

    assert run_workspace_setup(_reader(response)) == 0
    assert selected == []
    assert "Workspace setup cancelled." in capsys.readouterr().out


@pytest.mark.parametrize("exception_type", [EOFError, KeyboardInterrupt])
def test_setup_terminal_cancellation_is_zero_and_does_not_select(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    exception_type: type[BaseException],
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    current = _observation(tmp_path)
    selected: list[Path] = []
    monkeypatch.setattr(workspace_cli, "observe_workspace", lambda path=None: current)
    monkeypatch.setattr(
        workspace_cli,
        "set_workspace",
        lambda path: selected.append(path),  # type: ignore[func-returns-value]
    )

    def cancel(_prompt: str) -> str:
        raise exception_type()

    assert run_workspace_setup(cancel) == 0
    assert selected == []
    assert "Workspace setup cancelled." in capsys.readouterr().out


def test_setup_rejects_confirmation_other_than_use_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    current = _observation(
        tmp_path,
        state=WorkspacePresentationState.EMPTY_DIRECTORY,
    )
    selected: list[Path] = []
    monkeypatch.setattr(workspace_cli, "observe_workspace", lambda path=None: current)
    monkeypatch.setattr(
        workspace_cli,
        "set_workspace",
        lambda path: selected.append(path),  # type: ignore[func-returns-value]
    )

    assert run_workspace_setup(_reader("1", "NO")) == 0
    assert selected == []
    assert "Workspace setup cancelled." in capsys.readouterr().out


def test_setup_invalid_custom_candidate_fails_before_confirmation_or_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    current = _observation(tmp_path)
    invalid = _observation(
        tmp_path,
        root=tmp_path / "not-a-directory",
        source="explicit",
        state=WorkspacePresentationState.INVALID,
    )
    selected: list[Path] = []
    monkeypatch.setattr(
        workspace_cli,
        "observe_workspace",
        lambda path=None: current if path is None else invalid,
    )
    monkeypatch.setattr(
        workspace_cli,
        "set_workspace",
        lambda path: selected.append(path),  # type: ignore[func-returns-value]
    )

    assert run_workspace_setup(
        _reader("2", str(invalid.root))
    ) == 1
    assert selected == []
    captured = capsys.readouterr()
    assert "invalid or unusable" in captured.out
    assert "cannot continue" in captured.err


def test_setup_environment_override_offers_validation_without_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    current = _observation(
        tmp_path,
        source="environment",
        state=WorkspacePresentationState.EMPTY_DIRECTORY,
    )
    validated: list[Path | None] = []
    selected: list[Path] = []
    monkeypatch.setattr(workspace_cli, "observe_workspace", lambda path=None: current)
    monkeypatch.setattr(
        workspace_cli,
        "run_workspace_validate",
        lambda path: validated.append(path) or 0,
    )
    monkeypatch.setattr(
        workspace_cli,
        "set_workspace",
        lambda path: selected.append(path),  # type: ignore[func-returns-value]
    )

    assert run_workspace_setup(_reader("2")) == 0
    assert validated == [None]
    assert selected == []
    output = capsys.readouterr().out
    assert "PDS_WORKSPACE_ROOT controls the active workspace." in output
    assert "Choose another folder" not in output


def test_setup_environment_override_initializes_without_saving_preference(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    current = _observation(
        tmp_path,
        source="environment",
        state=WorkspacePresentationState.EMPTY_DIRECTORY,
    )
    initialized = 0

    monkeypatch.setattr(workspace_cli, "observe_workspace", lambda path=None: current)

    def initialize() -> WorkspaceSelectionResult:
        nonlocal initialized
        initialized += 1
        return WorkspaceSelectionResult(current, created=False, saved=False)

    monkeypatch.setattr(workspace_cli, "initialize_resolved_workspace", initialize)
    monkeypatch.setattr(
        workspace_cli,
        "set_workspace",
        lambda path: pytest.fail(f"unexpected saved selection for {path}"),
    )

    assert run_workspace_setup(_reader("1", "USE")) == 0
    assert initialized == 1
    output = capsys.readouterr().out
    assert "PDS_WORKSPACE_ROOT will remain the active workspace authority" in output
    assert "PDS_WORKSPACE_ROOT remains the active workspace authority." in output
    assert "selection was saved" not in output


def test_setup_observation_failure_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    def fail(path: Path | None = None) -> WorkspaceObservation:
        raise WorkspaceMutationError("Core inspection failed")

    monkeypatch.setattr(workspace_cli, "observe_workspace", fail)

    assert run_workspace_setup(_reader("1")) == 1
    assert "Core inspection failed" in capsys.readouterr().err


def test_setup_partial_success_returns_nonzero_and_reports_initialized_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import paper_data_suite.workspace_cli as workspace_cli

    current = _observation(
        tmp_path,
        state=WorkspacePresentationState.EMPTY_DIRECTORY,
    )
    monkeypatch.setattr(workspace_cli, "observe_workspace", lambda path=None: current)

    def fail(path: Path) -> WorkspaceSelectionResult:
        raise WorkspacePartialSuccessError(
            "saved selection failed",
            initialized_root=path,
            resolved=current,
        )

    monkeypatch.setattr(workspace_cli, "set_workspace", fail)

    assert run_workspace_setup(_reader("1", "USE")) == 1
    error = capsys.readouterr().err
    assert "initialization succeeded" in error
    assert f"Initialized path: {current.root}" in error
