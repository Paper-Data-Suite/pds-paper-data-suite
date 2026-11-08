"""Suite #52: privacy-minimal synthetic interactive Teacher Home journey.

This acceptance intentionally does not inspect installed producers, Core Notes,
workspace contents, or real teacher settings. It drives the production home
controller through injected terminal streams and approved local observations.
The result is D1 source evidence, NOT a real terminal or published-wheel gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from io import StringIO
from pathlib import Path

from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
    ApplicationObservation,
)
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.teacher_experience_contracts import (
    CoreTeacherContractObservation,
)
from paper_data_suite.teacher_home import run_teacher_home

PARENT_SUITE_SHA = "6d4b19f0104794a65ed0bebae4bf49534192eca5"
PINNED_CORE_SHA = "a0d5e1a50580bbe025f0cad23c7e8524203a52ec"
OFFICIAL_CORE_066_SHA256 = (
    "d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301"
)
DEVELOPER_CORE_SHA256 = (
    "62a62f4f3da06e6926832ec22d2b071449f5424aa58566ee1f1ca32120bef2ef"
)


class SyntheticTerminal(StringIO):
    """Deterministic injected TTY, not evidence of real console VT support."""

    def isatty(self) -> bool:
        return True


def _synthetic_inventory() -> ApplicationInventory:
    observations: list[ApplicationObservation] = []
    for component in APPROVED_COMPONENTS:
        if not component.launchable:
            continue
        available = component.component_id in {"scoreform", "concord", "portia"}
        console = component.console_scripts[0]
        observations.append(
            ApplicationObservation(
                component_id=component.component_id,
                display_name=component.display_name,
                purpose="Approved synthetic application; no producer accessed",
                distribution=component.distribution,
                qualified_version="historical only",
                installed_version="synthetic" if available else None,
                console_script_name=console.name,
                console_script_target=console.target,
                status=(
                    ApplicationLaunchStatus.AVAILABLE
                    if available
                    else ApplicationLaunchStatus.NOT_INSTALLED
                ),
                reason="synthetic metadata; provenance not established",
                launcher_path=(
                    Path("/synthetic/launcher") if available else None
                ),
            )
        )
    return ApplicationInventory(tuple(observations))


def _require(test: bool, message: str) -> None:
    if not test:
        raise ValueError("Teacher Home source acceptance failed: " + message)


def source_journey() -> dict[str, object]:
    """Exercise real home controller; all external actions are injected fakes."""
    inventory = _synthetic_inventory()
    calls: list[str] = []
    doctor_calls: list[str] = []
    help_calls: list[str] = []
    recent_calls: list[str] = []
    output = SyntheticTerminal()
    choices = SyntheticTerminal(
        "h\nb\n7\nb\n8\nm\n9\nb\n10\nb\n2\n1\n11\n1\n12\n1\n12\n2\nq\n"
    )

    def launcher(component_id: str) -> int:
        calls.append(component_id)
        # Nonzero child exit is reported but must not end the Suite session.
        return 1 if len(calls) == 1 else 0

    def doctor() -> int:
        doctor_calls.append("doctor")
        return 1

    def help_text() -> None:
        help_calls.append("help")
        output.write("usage: pds [options] {commands}\n")

    def recent() -> tuple[str, ...]:
        recent_calls.append("read-only")
        return ("scoreform", "quillan")

    code = run_teacher_home(
        input_stream=choices,
        output=output,
        collect_inventory=lambda: inventory,
        launch=launcher,
        doctor=doctor,
        show_help=help_text,
        recent=recent,
        observe_contract=lambda: CoreTeacherContractObservation(
            contract_present=False,
            advertised_capabilities=frozenset(),
            header_available=False,
            notes_recognizer_available=False,
        ),
    )
    rendered = output.getvalue()
    approved_names = [
        item.display_name for item in APPROVED_COMPONENTS if item.launchable
    ]
    _require(len(approved_names) == 6, "registry did not contain exactly six apps")
    _require(code == 0, "Suite session did not quit cleanly")
    _require(calls == ["scoreform", "scoreform"], "launch routing/order changed")
    _require(doctor_calls == ["doctor"], "doctor not explicitly gated")
    _require(help_calls == ["help"], "help dispatch not invoked once")
    _require(recent_calls == ["read-only"], "recent list read count changed")
    _require(
        rendered.count("Paper Data Suite\nTeacher Home\n") >= 10,
        "home did not redraw",
    )
    for name in approved_names:
        _require(name in rendered, f"approved application missing: {name}")
    for title in (
        "Workspace & Classroom Management",
        "Notes & Tasks",
        "Process Returned Papers",
        "Attention Needed",
        "Recent Applications",
        "Help & Diagnostics",
    ):
        _require(title in rendered, f"teacher workflow missing: {title}")
    _require("did not complete successfully" in rendered,
             "child failure did not return to home")
    _require("Returned from ScoreForm" in rendered,
             "successful child return not reported")
    _require("Quillan cannot be launched" in rendered,
             "unavailable application did not explain refusal")
    _require("Doctor completed (status 1)" in rendered,
             "diagnostic nonzero exit not preserved")
    _require("usage: pds" in rendered, "CLI help not available")
    _require("Leaving Paper Data Suite." in rendered, "clean Q missing")
    _require("\x1b" not in rendered, "pre-contract fallback emitted ANSI")
    _require(":notes is not a Notes service" in rendered,
             "unsupported Notes command description missing")
    return {
        "name": "source_synthetic_teacher_home",
        "status": "passed",
        "approved_application_count": len(approved_names),
        "synthetic_launch_count": len(calls),
        "doctor_invocation_count": len(doctor_calls),
        "recent_read_count": len(recent_calls),
        "notes_writes": 0,
        "actual_producer_launches": 0,
        "real_terminal_vt_qualified": False,
    }


def _verified_source_revision(repo: Path) -> str:
    """Allow re-running after commit, but require the accepted base ancestor."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", PARENT_SUITE_SHA, "HEAD"],
        cwd=repo, capture_output=True, check=False,
    )
    if head.returncode or ancestor.returncode:
        raise ValueError("Source acceptance requires Slice 3 as an ancestor")
    revision = head.stdout.strip()
    if len(revision) != 40 or not all(
        character in "0123456789abcdef" for character in revision
    ):
        raise ValueError("Source acceptance could not identify a Git commit")
    return revision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root: Path = args.suite_root.resolve()
    suite_revision = _verified_source_revision(root)
    outcome = source_journey()
    record = {
        "ticket": "pds-paper-data-suite#52",
        "stage": "Slice 4 / D1 source synthetic",
        "suite_parent_commit": PARENT_SUITE_SHA,
        "suite_tested_git_revision": suite_revision,
        "core_development_source_commit": PINNED_CORE_SHA,
        "developer_core_wheel_sha256_prior_slice3_evidence": DEVELOPER_CORE_SHA256,
        "published_core_0_6_6_sha256_prior_slice3_evidence": OFFICIAL_CORE_066_SHA256,
        "official_core_v1_header_d2_d3": "PENDING",
        "real_windows_teacher_terminal": "NOT TESTED BY THIS SCRIPT",
        "scenario": outcome,
    }
    destination: Path = args.output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("SUITE52_S4_SOURCE_TEACHER_JOURNEY_PASSED", flush=True)
    print("SUITE52_S4_OFFICIAL_CORE_V1_RELEASE_PENDING", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
