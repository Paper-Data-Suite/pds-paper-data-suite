"""Command-line interface for the Paper Data Suite shell."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from paper_data_suite._version import __version__
from paper_data_suite.doctor import collect_doctor_diagnostics, render_doctor_report


def build_parser() -> argparse.ArgumentParser:
    """Build the Paper Data Suite command-line parser."""
    parser = argparse.ArgumentParser(
        prog="pds",
        description=(
            "Paper Data Suite suite shell. Operational commands provide bounded, "
            "teacher-facing suite workflows."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    doctor = subparsers.add_parser(
        "doctor",
        help="diagnose the installed suite environment without modifying it",
        description=(
            "Diagnose Paper Data Suite runtime, packages, dependencies, public "
            "integration contracts, workspace access, and Core registry health."
        ),
    )
    doctor.add_argument(
        "--workspace",
        type=Path,
        help=(
            "inspect this workspace for this invocation only; do not save or "
            "initialize it"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Paper Data Suite command-line interface."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "doctor":
        report = collect_doctor_diagnostics(workspace=arguments.workspace)
        print(render_doctor_report(report), end="")
        return report.exit_code
    parser.print_help()
    return 0
