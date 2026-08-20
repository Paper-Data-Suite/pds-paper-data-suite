"""Teacher-facing rendering and deterministic CLI actions for workspace setup."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from paper_data_suite.workspace_setup import (
    WorkspaceObservation,
    WorkspacePartialSuccessError,
    WorkspacePresentationState,
    WorkspaceSelectionResult,
    WorkspaceSetupError,
    initialize_resolved_workspace,
    observe_workspace,
    reset_workspace,
    set_workspace,
    validate_workspace,
)

_SOURCE_LABELS = {
    "explicit": "explicit path",
    "environment": "environment override",
    "saved_config": "saved workspace selection",
    "default": "Core default location",
}
_STATE_LABELS = {
    WorkspacePresentationState.MISSING: "not created yet",
    WorkspacePresentationState.EMPTY_DIRECTORY: "empty directory",
    WorkspacePresentationState.EXISTING_DIRECTORY: "existing non-empty directory",
    WorkspacePresentationState.INVALID: "invalid / unusable",
}

InputReader = Callable[[str], str]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def workspace_source_label(source: str) -> str:
    """Return bounded teacher-facing wording for one Core selection source."""
    return _SOURCE_LABELS.get(source, source)


def render_workspace_observation(
    observation: WorkspaceObservation,
    *,
    title: str = "Paper Data Suite workspace",
) -> str:
    """Render one bounded Core-derived workspace observation."""
    lines = [
        title,
        "",
        "Path:",
        f"  {observation.root}",
        "",
        "Source:",
        f"  {workspace_source_label(observation.source)}",
        "",
        "State:",
        f"  {_STATE_LABELS[observation.state]}",
        "",
        f"Exists: {_yes_no(observation.exists)}",
        f"Directory: {_yes_no(observation.is_dir)}",
        f"Writable: {_yes_no(observation.is_writable)}",
        "",
        f"Core configuration: {observation.config_path}",
        f"Core default workspace: {observation.default_root}",
        "",
        f"Detail: {observation.reason}",
    ]
    if observation.source == "environment":
        lines.extend(
            (
                "",
                "PDS_WORKSPACE_ROOT controls the active workspace for this process.",
            )
        )
    return "\n".join(lines) + "\n"


def _print_failure(error: WorkspaceSetupError) -> None:
    print(f"Workspace command failed: {error}", file=sys.stderr)


def run_workspace_show() -> int:
    """Inspect and render the current Core-resolved workspace."""
    try:
        observation = observe_workspace()
    except WorkspaceSetupError as error:
        _print_failure(error)
        return 1
    print(render_workspace_observation(observation), end="")
    return 0


def run_workspace_validate(path: Path | None) -> int:
    """Validate one existing workspace candidate without creating or saving it."""
    try:
        observation = validate_workspace(path)
    except WorkspaceSetupError as error:
        _print_failure(error)
        return 1
    print(
        render_workspace_observation(
            observation,
            title="Workspace validation passed",
        ),
        end="",
    )
    print("No workspace preference was changed.")
    return 0


def _render_partial_success(error: WorkspacePartialSuccessError) -> None:
    print(
        "Workspace initialization succeeded, but workspace selection did not "
        "complete.",
        file=sys.stderr,
    )
    print(f"Initialized path: {error.initialized_root}", file=sys.stderr)
    print(f"Detail: {error}", file=sys.stderr)
    if error.resolved is not None:
        print(
            "Current resolved workspace: "
            f"{error.resolved.root} ({workspace_source_label(error.resolved.source)})",
            file=sys.stderr,
        )


def run_workspace_set(path: Path) -> int:
    """Initialize and save one explicitly supplied workspace through Core."""
    try:
        result = set_workspace(path)
    except WorkspacePartialSuccessError as error:
        _render_partial_success(error)
        return 1
    except WorkspaceSetupError as error:
        _print_failure(error)
        return 1

    print(
        render_workspace_observation(
            result.observation,
            title="Workspace ready",
        ),
        end="",
    )
    if result.created:
        print("Core created and initialized this workspace.")
    else:
        print("Core validated and initialized the existing directory.")
    print("The workspace selection was saved through Core.")
    print("No previous workspace files were moved, copied, or deleted.")
    return 0


def run_workspace_reset() -> int:
    """Clear only Core's saved workspace preference and show actual resolution."""
    try:
        result = reset_workspace()
    except WorkspaceSetupError as error:
        _print_failure(error)
        return 1

    if result.cleared:
        print("Cleared the saved workspace preference.")
    else:
        print("No saved workspace preference was set.")
    print("No workspace files were deleted.")
    print()
    print(
        render_workspace_observation(
            result.observation,
            title="Current resolved workspace",
        ),
        end="",
    )
    return 0


def _read_setup_input(prompt: str, input_fn: InputReader) -> str | None:
    """Read one guided-workflow response with safe terminal cancellation."""
    try:
        return input_fn(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _cancel_workspace_setup() -> int:
    print("Workspace setup cancelled. No workspace selection was changed.")
    return 0


def _print_setup_choices(observation: WorkspaceObservation) -> None:
    print()
    if observation.source == "environment":
        print("PDS_WORKSPACE_ROOT controls the active workspace.")
        print("1. Initialize/use this environment-selected workspace")
        print("2. Validate this workspace without changing it")
        print("Q. Quit")
        return
    print("1. Use this workspace")
    print("2. Choose another folder")
    print("3. Validate this workspace without changing it")
    print("Q. Quit")


def _preview_workspace_effects(observation: WorkspaceObservation) -> None:
    print()
    print("Planned workspace action")
    print()
    if observation.state is WorkspacePresentationState.MISSING:
        print("This folder does not exist yet.")
        print("Core will create and initialize the workspace.")
    elif observation.state is WorkspacePresentationState.EMPTY_DIRECTORY:
        print("This folder exists and is empty.")
        print("An empty directory is not an invalid workspace.")
        print("Core will initialize Paper Data Suite workspace structure here.")
    elif observation.state is WorkspacePresentationState.EXISTING_DIRECTORY:
        print("This folder already contains files or directories.")
        print("Existing contents will not be moved or deleted.")
        print("Core initialization may add Paper Data Suite workspace structure here.")
        print("Confirm only if you intend to adopt this existing directory.")
    else:
        print("This candidate is invalid or unusable and will not be changed.")
        return

    if observation.source == "environment":
        print()
        print(
            "PDS_WORKSPACE_ROOT will remain the active workspace authority for "
            "this process."
        )
    else:
        print("Core will save this location as the workspace selection.")
    print("No previous workspace files will be moved, copied, merged, or deleted.")


def _render_setup_success(result: WorkspaceSelectionResult) -> None:
    print()
    print(
        render_workspace_observation(
            result.observation,
            title="Workspace ready",
        ),
        end="",
    )
    if result.created:
        print("Core created and initialized this workspace.")
    else:
        print("Core validated and initialized the existing directory.")
    if result.observation.source == "environment":
        print("PDS_WORKSPACE_ROOT remains the active workspace authority.")
    else:
        print("The workspace selection was saved through Core.")
    print("No previous workspace files were moved, copied, merged, or deleted.")
    print("No school year or classroom setup was changed.")
    print()
    print("Next: pds doctor")


def run_workspace_setup(input_fn: InputReader = input) -> int:
    """Run the guided review-before-write Core workspace setup workflow."""
    try:
        current = observe_workspace()
    except WorkspaceSetupError as error:
        _print_failure(error)
        return 1

    print(
        render_workspace_observation(
            current,
            title="Paper Data Suite workspace setup",
        ),
        end="",
    )

    candidate: WorkspaceObservation | None = None
    while candidate is None:
        _print_setup_choices(current)
        choice = _read_setup_input("Choose an option: ", input_fn)
        if choice is None or not choice or choice.lower() == "q":
            return _cancel_workspace_setup()

        if current.source == "environment":
            if choice == "1":
                candidate = current
                break
            if choice == "2":
                return run_workspace_validate(None)
            print("Choose 1, 2, or Q.")
            continue

        if choice == "1":
            candidate = current
            break
        if choice == "2":
            raw_path = _read_setup_input("Workspace folder (Q to cancel): ", input_fn)
            if raw_path is None or not raw_path or raw_path.lower() == "q":
                return _cancel_workspace_setup()
            try:
                candidate = observe_workspace(Path(raw_path))
            except WorkspaceSetupError as error:
                _print_failure(error)
                return 1
            break
        if choice == "3":
            return run_workspace_validate(None)
        print("Choose 1, 2, 3, or Q.")

    assert candidate is not None
    print()
    print(
        render_workspace_observation(
            candidate,
            title="Workspace candidate",
        ),
        end="",
    )
    _preview_workspace_effects(candidate)

    if candidate.state is WorkspacePresentationState.INVALID:
        print(
            "Workspace setup cannot continue with this candidate.",
            file=sys.stderr,
        )
        return 1

    confirmation = _read_setup_input(
        "Type USE to continue, or press Enter/Q to cancel: ",
        input_fn,
    )
    if confirmation is None or confirmation.upper() != "USE":
        return _cancel_workspace_setup()

    try:
        if candidate.source == "environment":
            result = initialize_resolved_workspace()
        else:
            result = set_workspace(candidate.root)
    except WorkspacePartialSuccessError as error:
        _render_partial_success(error)
        return 1
    except WorkspaceSetupError as error:
        _print_failure(error)
        return 1

    _render_setup_success(result)
    return 0


__all__ = (
    "render_workspace_observation",
    "run_workspace_reset",
    "run_workspace_setup",
    "run_workspace_set",
    "run_workspace_show",
    "run_workspace_validate",
    "workspace_source_label",
)
