# mypy: disable-error-code="import-not-found, import-untyped"
"""Explicit real installed Suite Teacher Home native synthetic journey (#19G1).

Invoke only from the verified E3A isolated Windows 3.11 installation. No
injected Core, producer, admission, consent, or dispatch callback is used.
A new, distinct disposable workspace is created for every consent scenario.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import gettempdir
from typing import Iterator


class HomeAcceptanceRefused(RuntimeError):
    """A synthetic installed Home observation was missing or contradicted."""


# Only predefined harness messages become public diagnostic categories. Never
# emit exception bodies, user paths, producer output or the scripted transcript.
_FAILURE_CODES: dict[str, str] = {
    "unsupported scripted consent scenario": "invalid_scenario",
    "Core workspace did not select temp root": "workspace_selection",
    "installed Suite Home returned nonzero": "cli_nonzero",
    "installed interactive Home not completed": "home_exit",
    "Home printed private QR or ANSI despite NO_COLOR": "unsafe_output",
    "synthetic workspace is not a fresh temp root": "workspace_not_fresh",
    "native two-page QR preview did not qualify": "native_qr_preview",
    "synthetic inbox original was modified": "original_modified",
    "teacher Home exposed a private path or person": "privacy_violation",
    "pre-retention cancel wrote to workspace": "cancel_first_wrote",
    "pre-retention cancel retained source": "cancel_first_retained",
    "first consent cancellation absent": "cancel_first_unreported",
    "Core must retain exactly one whole source": "retention_count",
    "Core retained bytes do not match original": "retention_mismatch",
    "first Core custody result absent": "retention_result_missing",
    "read-only retained preparation did not qualify": "preparation_missing",
    "read-only preparation claimed execution": "readonly_claimed_execution",
    "second teacher cancellation was not rendered": "cancel_second_unreported",
    "cancelled dispatch attempted a handler": "cancel_second_attempted",
    "approved Core run did not attempt two pages": "attempt_count",
    "approved Core run did not complete": "core_incomplete",
    "two separate producer handler returns absent": "handler_count",
    "Core-parsed producer groups absent": "producer_groups",
    "Suite must not claim published grades": "grade_claim",
    "non-dispatch scenario produced ScoreForm debug evidence": "unexpected_scoring",
    "non-disposable path refused": "path_refused",
}


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _transcript(root: Path, *, decision: str, wheelhouse: Path) -> str:
    """Select both explicit physical pages; never use blank/default-all."""
    if decision not in {"cancel_first", "retain_only", "cancel_second", "dispatch"}:
        raise HomeAcceptanceRefused("unsupported scripted consent scenario")
    steps = ["9", "2", str(root), "1", "1", "1,2", "P", "R"]
    if decision == "cancel_first":
        # First-consent cancellation returns to papers, not Teacher Home.
        steps.extend(("CANCEL", "B", "Q"))
    else:
        steps.append("RETAIN")
        if decision == "retain_only":
            # One B closes the retained view; another closes papers.
            steps.extend(("V", "B", "B", "Q"))
        else:
            steps.extend(("D", str(wheelhouse)))
            if decision == "cancel_second":
                # First B leaves Core review; second returns to Teacher Home.
                steps.extend(("CANCEL", "B", "B", "Q"))
            else:
                steps.extend(("DISPATCH", "B", "Q"))
    return "\n".join(steps) + "\n"


@contextmanager
def _selected_workspace(root: Path) -> Iterator[None]:
    """Scope Core environment selection to a single disposable subprocess."""
    previous = os.environ.get("PDS_WORKSPACE_ROOT")
    no_color = os.environ.get("NO_COLOR")
    try:
        os.environ["PDS_WORKSPACE_ROOT"] = str(root)
        os.environ["NO_COLOR"] = "1"
        from paper_data_suite.workspace_setup import (
            WorkspacePresentationState,
            observe_workspace,
        )

        observed = observe_workspace()
        if (
            observed.root != root
            or observed.state is not WorkspacePresentationState.EXISTING_DIRECTORY
            or not observed.is_writable
        ):
            raise HomeAcceptanceRefused("Core workspace did not select temp root")
        yield
    finally:
        if previous is None:
            os.environ.pop("PDS_WORKSPACE_ROOT", None)
        else:
            os.environ["PDS_WORKSPACE_ROOT"] = previous
        if no_color is None:
            os.environ.pop("NO_COLOR", None)
        else:
            os.environ["NO_COLOR"] = no_color


def _drive_installed_cli(commands: str) -> str:
    """Use actual installed CLI no-argument interactive dispatch, not mocks."""
    from paper_data_suite import cli

    input_stream = _Terminal(commands)
    output = _Terminal()
    previous = sys.stdin, sys.stdout
    try:
        sys.stdin, sys.stdout = input_stream, output
        result = cli.main(())
    finally:
        sys.stdin, sys.stdout = previous
    if result != 0:
        raise HomeAcceptanceRefused("installed Suite Home returned nonzero")
    rendered = output.getvalue()
    if (
        "Teacher Home" not in rendered
        or "Process Returned Papers" not in rendered
        or "Leaving Paper Data Suite" not in rendered
    ):
        raise HomeAcceptanceRefused("installed interactive Home not completed")
    if "PDS2|" in rendered or "\x1b" in rendered:
        raise HomeAcceptanceRefused("Home printed private QR or ANSI despite NO_COLOR")
    return rendered


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def _prepare_synthetic_case(parent: Path, scenario: str) -> tuple[Path, Path]:
    # The existing #18 fixture helpers write genuine synthetic issued records.
    # No script copies real teacher PDF files or reads outside the temp parent.
    from issue18_native_mixed_pdf_rehearsal import (
        _create_mixed_pdf,
        _draw_marked_sheet,
        _exact_preview,
        _make_quillan_route,
        _make_scoreform_route,
        _safe_empty_workspace,
    )

    from paper_data_suite.returned_paper_readonly_decode import (
        observe_selected_sources,
    )

    case = parent / scenario
    case.mkdir()
    root = case / "suite18_synthetic_workspace"
    root.mkdir()
    if not _safe_empty_workspace(root):
        raise HomeAcceptanceRefused("synthetic workspace is not a fresh temp root")
    scoreform_route = _make_scoreform_route(root)
    quillan_route = _make_quillan_route(root)
    image = root / "omr_synthetic.png"
    _draw_marked_sheet(image)
    inbox = root / "scans_inbox"
    inbox.mkdir()
    source = inbox / "synthetic_mixed_pds2.pdf"
    _create_mixed_pdf(source, image, (scoreform_route, quillan_route))
    if not _exact_preview(observe_selected_sources((source,))):
        raise HomeAcceptanceRefused("native two-page QR preview did not qualify")
    return root, source


def _retained_pdfs(root: Path) -> tuple[Path, ...]:
    return tuple((root / "scans" / "source").rglob("*.pdf"))


def _require(test: bool, category: str) -> None:
    if not test:
        raise HomeAcceptanceRefused(category)


def _run_case(parent: Path, wheelhouse: Path, scenario: str) -> None:
    root, source = _prepare_synthetic_case(parent, scenario)
    original_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    before = _snapshot(root)
    with _selected_workspace(root):
        display = _drive_installed_cli(
            _transcript(root, decision=scenario, wheelhouse=wheelhouse)
        )
    _require(
        hashlib.sha256(source.read_bytes()).hexdigest() == original_digest,
        "synthetic inbox original was modified",
    )
    _require(str(root) not in display and "Student Sample" not in display,
             "teacher Home exposed a private path or person")
    if scenario == "cancel_first":
        _require(_snapshot(root) == before, "pre-retention cancel wrote to workspace")
        _require(not _retained_pdfs(root), "pre-retention cancel retained source")
        _require("Status: cancelled" in display, "first consent cancellation absent")
        return

    retained = _retained_pdfs(root)
    _require(len(retained) == 1, "Core must retain exactly one whole source")
    _require(hashlib.sha256(retained[0].read_bytes()).hexdigest() == original_digest,
             "Core retained bytes do not match original")
    _require("Status: retained" in display, "first Core custody result absent")
    if scenario == "retain_only":
        _require("Preparation status: ready" in display,
                 "read-only retained preparation did not qualify")
        _require("Core action: completed" not in display,
                 "read-only preparation claimed execution")
    elif scenario == "cancel_second":
        _require("Second consent cancelled" in display,
                 "second teacher cancellation was not rendered")
        _require("Core attempted physical pages: 0" in display,
                 "cancelled dispatch attempted a handler")
    else:
        _require("Core attempted physical pages: 2" in display,
                 "approved Core run did not attempt two pages")
        _require("Core run: completed" in display,
                 "approved Core run did not complete")
        _require("handler_returned: 2" in display,
                 "two separate producer handler returns absent")
        _require("scoreform" in display and "quillan" in display,
                 "Core-parsed producer groups absent")
        _require("No grade publication" in display,
                 "Suite must not claim published grades")
    if scenario != "dispatch":
        after = _snapshot(root)
        _require(
            not any("/debug/" in name and "scoreform" in name
                    for name in set(after).difference(before)),
            "non-dispatch scenario produced ScoreForm debug evidence",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-parent", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args(argv)
    current_scenario = "setup"
    try:
        parent = args.synthetic_parent
        temp = Path(gettempdir()).resolve(strict=True)
        if (
            not parent.is_absolute()
            or not parent.is_dir()
            or parent.is_symlink()
            or not parent.resolve(strict=True).is_relative_to(temp)
            or not args.wheelhouse.is_absolute()
            or not args.wheelhouse.is_dir()
            or args.wheelhouse.is_symlink()
        ):
            raise HomeAcceptanceRefused("non-disposable path refused")
        for scenario in (
            "cancel_first", "retain_only", "cancel_second", "dispatch"
        ):
            current_scenario = scenario
            print("SUITE19_G1_HOME_" + scenario.upper() + "_STARTED", flush=True)
            _run_case(parent, args.wheelhouse, scenario)
            print("SUITE19_G1_HOME_" + scenario.upper() + "_VERIFIED")
    except (Exception, KeyboardInterrupt) as error:
        reason = (
            _FAILURE_CODES.get(str(error), "unclassified")
            if isinstance(error, HomeAcceptanceRefused) else "unexpected"
        )
        print("SUITE19_G1_HOME_REFUSED:" + type(error).__name__, file=sys.stderr)
        print("SUITE19_G1_HOME_FAILED_SCENARIO=" + current_scenario,
              file=sys.stderr)
        print("SUITE19_G1_HOME_FAILURE_CODE=" + reason, file=sys.stderr)
        return 2
    print("SUITE19_G1_INSTALLED_TEACHER_HOME_ACCEPTANCE_PASSED")
    print("SUITE19_G1_SYNTHETIC_ONLY_NOT_CLASSROOM_CERTIFICATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
