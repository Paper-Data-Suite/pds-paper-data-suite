# mypy: disable-error-code="import-not-found, import-untyped"
"""#19G2B: fresh, strictly negative installed Teacher Home acceptance.

Only disposable synthetic cases are permitted. No handler may be authorized by
this script. Core retention occurs exactly once per positive-first-consent case.
No earlier uncertain page is used, retried or inspected.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from tempfile import gettempdir

from issue19_g1_installed_teacher_home_rehearsal import (
    _drive_installed_cli,
    _prepare_synthetic_case,
    _retained_pdfs,
    _selected_workspace,
    _snapshot,
    _transcript,
)

_CASES = (
    "missing_wheelhouse",
    "empty_wheelhouse",
    "invalid_second_consent",
    "unresolved_only",
)


class G2BRefused(Exception):
    """Deliberately no sensitive source content in the public error."""


def _require(condition: bool, category: str) -> None:
    if not condition:
        raise G2BRefused(category)


def _case_steps(root: Path, wheelhouse: Path, scenario: str) -> str:
    """Use the corrected G1 *two-physical-page* selection verbatim."""
    _require(scenario in _CASES, "invalid_scenario")
    lines = _transcript(
        root, decision="dispatch", wheelhouse=wheelhouse,
    ).splitlines()
    _require(lines[:7] == ["9", "2", str(root), "1", "1,2", "P", "R"],
             "wrong_selection")
    _require(lines.count("DISPATCH") == 1, "wrong_consent")
    index = lines.index("DISPATCH")
    if scenario == "invalid_second_consent":
        lines[index] = "APPROVE"  # Invalid fresh second consent.
        lines.insert(index + 2, "B")  # Return through Core review and Home.
    else:
        # Missing/empty wheelhouse and unresolved-only never reach 2nd consent.
        del lines[index]
    _require(lines.count("DISPATCH") == 0, "positive_consent_forbidden")
    _require(lines[-1] == "Q", "home_exit_missing")
    return "\n".join(lines) + "\n"


def _prepare_manual_only(parent: Path, scenario: str) -> tuple[Path, Path]:
    """A real two-page, PDFium-decodable PDF with no QR, no issued producer."""
    from reportlab.pdfgen.canvas import Canvas

    from paper_data_suite.returned_paper_readonly_decode import (
        observe_selected_sources,
    )

    case = parent / scenario
    case.mkdir()
    root = case / "suite18_synthetic_workspace"
    root.mkdir()
    inbox = root / "scans_inbox"
    inbox.mkdir()
    source = inbox / "synthetic_no_qr.pdf"
    canvas = Canvas(str(source), pagesize=(612, 792))
    for number in (1, 2):
        canvas.setFont("Helvetica", 12)
        canvas.drawString(48, 730, f"Synthetic blank response page {number}")
        canvas.drawString(48, 700, "No real student work or QR is present.")
        canvas.showPage()
    canvas.save()
    observations = observe_selected_sources((source,))
    _require(
        len(observations) == 1
        and observations[0].status == "observed"
        and len(observations[0].pages) == 2
        and all(page.status == "missing_qr" for page in observations[0].pages),
        "native_manual_preview",
    )
    return root, source


def _run_case(parent: Path, official: Path, scenario: str) -> None:
    if scenario == "unresolved_only":
        root, source = _prepare_manual_only(parent, scenario)
    else:
        root, source = _prepare_synthetic_case(parent, scenario)
    _require(len(str(root)) < 175, "case_path_too_long")
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    prior = _snapshot(root)
    chosen_wheels = official
    if scenario == "missing_wheelhouse":
        chosen_wheels = root.parent / "no_such_official_wheels"
        _require(not chosen_wheels.exists(), "missing_wheels_exist")
    elif scenario == "empty_wheelhouse":
        chosen_wheels = root.parent / "unverified_official_wheels"
        chosen_wheels.mkdir()
    steps = _case_steps(root, chosen_wheels, scenario)
    with _selected_workspace(root):
        transcript = _drive_installed_cli(steps)
    _require(
        "Status: retained." in transcript
        and "Prepared typed Core requests: 2" not in transcript,
        "unexpected_readonly_rehearsal",
    ) if scenario == "unresolved_only" else _require(
        "Status: retained." in transcript,
        "retention_not_rendered",
    )
    _require(
        original_sha == hashlib.sha256(source.read_bytes()).hexdigest(),
        "original_modified",
    )
    copies = _retained_pdfs(root)
    _require(len(copies) == 1, "retention_cardinality")
    _require(
        copies[0].read_bytes() == source.read_bytes(),
        "retention_bytes_mismatch",
    )
    after = _snapshot(root)
    added = set(after) - set(prior)
    expected = {copies[0].relative_to(root).as_posix()}
    _require(added == expected, "unapproved_extra_files")
    _require(all(after.get(p) == h for p, h in prior.items()),
             "existing_files_mutated")
    _require(
        str(root) not in transcript and str(chosen_wheels) not in transcript
        and "Student Sample" not in transcript
        and "PDS2|" not in transcript and "\x1b" not in transcript,
        "private_terminal_output",
    )
    if scenario in {"missing_wheelhouse", "empty_wheelhouse"}:
        _require(
            "Action status: admission_refused." in transcript
            and "Second Teacher Consent" not in transcript
            and "Core attempted physical pages:" not in transcript
            and "Stage: 2 Core-retained page request(s) prepared" not in transcript,
            "failed_admission_boundary",
        )
    elif scenario == "invalid_second_consent":
        _require(
            "Second consent cancelled" in transcript
            and "Action status: cancelled." in transcript
            and "Core attempted physical pages: 0." in transcript
            and "Stage: 2 Core-retained page request(s) prepared" in transcript
            and "Core run: cancelled." in transcript,
            "invalid_consent_boundary",
        )
    else:
        _require(
            "Action status: no_dispatchable_pages." in transcript
            and "Manual-only follow-up" in transcript
            and "Selected unresolved physical pages: 2." in transcript
            and "No verified Core failure ID is present" in transcript
            and "DEFER is unavailable" in transcript
            and "Second Teacher Consent" not in transcript
            and "Core attempted physical pages:" not in transcript,
            "manual_handoff_boundary",
        )
    _require("No grade publication" in transcript, "grade_claim_disclosure")


def _safe_parent(parent: Path, wheelhouse: Path) -> bool:
    try:
        temp = Path(gettempdir()).resolve(strict=True)
        found = parent.resolve(strict=True)
        return (
            parent.is_absolute() and parent.is_dir() and not parent.is_symlink()
            and re.fullmatch(r"g2b_[0-9a-f]{8}", parent.name) is not None
            and re.fullmatch(
                r"suite19_e3a_synthetic_[0-9a-f]{32}", parent.parent.name
            ) is not None
            and parent.parent.is_dir() and not parent.parent.is_symlink()
            and found.is_relative_to(temp)
            and not any(parent.iterdir())
            and len(str(parent)) <= 125
            and wheelhouse.is_absolute() and wheelhouse.is_dir()
            and not wheelhouse.is_symlink()
        )
    except (OSError, ValueError, RuntimeError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-parent", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args(argv)
    if not _safe_parent(args.synthetic_parent, args.wheelhouse):
        print("SUITE19_G2B_REFUSED=path_guard", file=sys.stderr)
        return 2
    scenario = "preflight"
    try:
        for scenario in _CASES:
            print("SUITE19_G2B_" + scenario.upper() + "_STARTED", flush=True)
            _run_case(args.synthetic_parent, args.wheelhouse, scenario)
            print("SUITE19_G2B_" + scenario.upper() + "_VERIFIED", flush=True)
    except (Exception, KeyboardInterrupt) as exc:
        # Never emit raw paths, PDF content, producer stdout or exception bodies.
        code = (
            str(exc) if isinstance(exc, G2BRefused) and str(exc) in {
                "invalid_scenario", "wrong_selection", "wrong_consent",
                "positive_consent_forbidden", "home_exit_missing",
                "native_manual_preview", "case_path_too_long",
                "missing_wheels_exist", "unexpected_readonly_rehearsal",
                "retention_not_rendered", "original_modified",
                "retention_cardinality", "retention_bytes_mismatch",
                "unapproved_extra_files", "existing_files_mutated",
                "private_terminal_output", "failed_admission_boundary",
                "invalid_consent_boundary", "manual_handoff_boundary",
                "grade_claim_disclosure",
            } else "unexpected_or_home_refused"
        )
        print("SUITE19_G2B_FAILED_SCENARIO=" + scenario, file=sys.stderr)
        print("SUITE19_G2B_REFUSED=" + code, file=sys.stderr)
        return 2
    print("SUITE19_G2B_INSTALLED_NEGATIVE_ACCEPTANCE_PASSED")
    print("SUITE19_G2B_SYNTHETIC_ONLY_NOT_CLASSROOM_CERTIFICATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
