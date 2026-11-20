# mypy: disable-error-code="import-not-found, import-untyped"
"""#19G4: distinct actual installed Teacher Home local-file E2E journeys.

Run only in E3A's newly built, official-wheel-verified Python 3.11 venv.
Sources originate from fresh synthetic cases *outside* Core scans_inbox.
No old uncertain source, real teacher data, mock handler or admission override.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from tempfile import gettempdir

from issue19_g1_installed_teacher_home_rehearsal import (
    _drive_installed_cli,
    _prepare_synthetic_case,
    _retained_pdfs,
    _selected_workspace,
    _snapshot,
)

_SCENARIOS = (
    ("l1", "cancel_first"),
    ("l2", "retain_only"),
    ("l3", "cancel_second"),
    ("l4", "dispatch"),
)


class LocalInstalledRefused(RuntimeError):
    """The public harness prints only fixed failure categories."""


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise LocalInstalledRefused(reason)


def _steps(root: Path, source: Path, wheelhouse: Path, scenario: str) -> str:
    """Choose explicit external source, workspace, BOTH physical pages."""
    _require(scenario in dict(_SCENARIOS).values(), "invalid_scenario")
    lines = ["9", "3", "1", str(source), str(root), "1,2", "P", "R"]
    if scenario == "cancel_first":
        lines.extend(("CANCEL", "B", "Q"))
    elif scenario == "retain_only":
        lines.extend(("RETAIN", "V", "B", "B", "Q"))
    elif scenario == "cancel_second":
        lines.extend(("RETAIN", "D", str(wheelhouse), "CANCEL", "B", "B", "Q"))
    else:
        lines.extend(("RETAIN", "D", str(wheelhouse), "DISPATCH", "B", "Q"))
    return "\n".join(lines) + "\n"


def _run_case(parent: Path, wheelhouse: Path, tag: str, scenario: str) -> None:
    from issue18_native_mixed_pdf_rehearsal import _exact_preview

    from paper_data_suite.returned_paper_readonly_decode import (
        observe_selected_sources,
    )

    root, inbox_source = _prepare_synthetic_case(parent, tag)
    source = root.parent / "outside.pdf"
    _require(not source.exists(), "external_source_collision")
    inbox_source.rename(source)  # Only brand-new synthetic bytes; no second copy.
    _require(not tuple((root / "scans_inbox").iterdir()), "inbox_not_empty")
    _require(_exact_preview(observe_selected_sources((source,))), "external_qr")
    _require(len(str(root)) <= 145, "local_path_too_long")
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    before = _snapshot(root)
    with _selected_workspace(root):
        text = _drive_installed_cli(_steps(root, source, wheelhouse, scenario))
    _require(hashlib.sha256(source.read_bytes()).hexdigest() == original,
             "original_modified")
    _require(
        str(root) not in text and str(source) not in text
        and "PDS2|" not in text and "Student Sample" not in text,
        "privacy_violation",
    )
    _require(
        "Selected 2 physical pages from 1 local source(s)" in text
        and "Whole-file custody would include 2 physical pages" in text,
        "two_page_local_plan_missing",
    )
    retained = _retained_pdfs(root)
    if scenario == "cancel_first":
        _require(_snapshot(root) == before and not retained,
                 "cancel_first_wrote")
        _require("Status: cancelled" in text, "cancel_first_status")
        return
    _require(len(retained) == 1, "retention_count")
    _require(hashlib.sha256(retained[0].read_bytes()).hexdigest() == original,
             "retained_bytes_mismatch")
    _require("Status: retained" in text, "retention_status")
    if scenario == "retain_only":
        _require("Prepared typed Core requests: 2" in text,
                 "read_only_requests_missing")
        _require("Core attempted physical pages: 2" not in text,
                 "unexpected_dispatch")
    elif scenario == "cancel_second":
        _require(
            "Stage: 2 Core-retained page request(s) prepared" in text
            and "Second consent cancelled" in text
            and "Core attempted physical pages: 0" in text,
            "second_cancel_failed",
        )
    else:
        _require(
            "Stage: 2 Core-retained page request(s) prepared" in text
            and "Core attempted physical pages: 2" in text
            and "Core run: completed" in text
            and "handler_returned: 2" in text
            and "scoreform" in text and "quillan" in text
            and "No grade publication" in text,
            "two_producer_dispatch_failed",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-parent", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args(argv)
    scenario = "setup"
    try:
        parent = args.synthetic_parent
        temp = Path(gettempdir()).resolve(strict=True)
        _require(
            parent.is_absolute() and parent.is_dir()
            and not parent.is_symlink()
            and parent.resolve(strict=True).is_relative_to(temp)
            and parent.name.startswith("suite19_e3a_synthetic_")
            and args.wheelhouse.is_absolute()
            and args.wheelhouse.is_dir()
            and not args.wheelhouse.is_symlink(),
            "path_refused",
        )
        for tag, scenario in _SCENARIOS:
            print("SUITE19_G4_LOCAL_" + scenario.upper() + "_STARTED", flush=True)
            _run_case(parent, args.wheelhouse, tag, scenario)
            print("SUITE19_G4_LOCAL_" + scenario.upper() + "_VERIFIED", flush=True)
    except (Exception, KeyboardInterrupt) as error:
        allowed = {
            "path_refused", "invalid_scenario", "external_source_collision",
            "inbox_not_empty", "external_qr", "local_path_too_long",
            "original_modified", "privacy_violation", "two_page_local_plan_missing",
            "cancel_first_wrote", "cancel_first_status", "retention_count",
            "retained_bytes_mismatch", "retention_status",
            "read_only_requests_missing", "unexpected_dispatch",
            "second_cancel_failed", "two_producer_dispatch_failed",
        }
        code = (
            str(error) if isinstance(error, LocalInstalledRefused)
            and str(error) in allowed else "unclassified"
        )
        print("SUITE19_G4_FAILED_SCENARIO=" + scenario, file=sys.stderr)
        print("SUITE19_G4_FAILURE_CODE=" + code, file=sys.stderr)
        return 2
    print("SUITE19_G4_INSTALLED_LOCAL_FILE_ACCEPTANCE_PASSED")
    print("SUITE19_G4_SYNTHETIC_ONLY_NOT_CLASSROOM_CERTIFICATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
