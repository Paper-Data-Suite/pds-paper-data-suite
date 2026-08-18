"""Minimal command-line foundation for Paper Data Suite."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from paper_data_suite._version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the package-foundation command-line parser."""
    parser = argparse.ArgumentParser(
        prog="pds",
        description=(
            "Paper Data Suite suite shell. Operational commands are added by "
            "later v0.1.0 development issues."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the minimal Paper Data Suite command-line interface."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
