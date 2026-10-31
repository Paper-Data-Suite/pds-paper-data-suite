"""Issue #49 Slice 102: explicit opt-in signed LAB path through ``pds launch``.

The historical production launcher is deliberately unchanged. The only new
execution mode is a named disposable Quillan 0.10.6 venv and ``--help`` only.
Delegates every evidence check to Slice 101; no application menu or arbitrary
arguments are accepted. This module does NOT grant production launch authority.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path


def add_signed_lab_arguments(parser: argparse.ArgumentParser) -> None:
    """Append optional, mutually exclusive laboratory modes to ``pds launch``."""
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--signed-lab-check",
        action="store_true",
        help="read-only signed installed Quillan lab inspection (not production)",
    )
    modes.add_argument(
        "--signed-lab-help",
        action="store_true",
        help="run only Quillan --help after signed disposable-lab inspection",
    )
    modes.add_argument(
        "--signed-lab-native-help",
        action="store_true",
        help="run Quillan --help only after separate root-signed native byte check",
    )
    parser.add_argument(
        "--native-envelope",
        type=Path,
        help="required only for --signed-lab-native-help",
    )
    for name, type_value in (
        ("lab-venv", Path),
        ("wheel", Path),
        ("trust-policy", Path),
        ("trust-sha256", str),
        ("registry", Path),
        ("module", Path),
    ):
        modes_help = "required when selecting either signed lab mode"
        parser.add_argument(f"--{name}", type=type_value, help=modes_help)


def dispatch_launch(
    arguments: argparse.Namespace,
    *,
    historical_launch: Callable[[str], int],
) -> int:
    """Never fall back to historical launch after opt-in or partial evidence.

    Without any laboratory flags, delegate the original component unchanged.
    The explicit lab path never passes arbitrary child arguments or executes
    the teacher menu; all trust, installation, and wrapper checks are repeated
    in Slice 101, which itself refuses non-Windows and non-lab environments.
    """
    names = (
        "lab_venv",
        "wheel",
        "trust_policy",
        "trust_sha256",
        "registry",
        "module",
    )
    flags: dict[str, object] = {name: getattr(arguments, name) for name in names}
    check = arguments.signed_lab_check is True
    help_only = arguments.signed_lab_help is True
    native_help = arguments.signed_lab_native_help is True
    if not check and not help_only and not native_help:
        if arguments.native_envelope is not None or any(
            value is not None for value in flags.values()
        ):
            print(
                "REFUSED: signed lab evidence requires --signed-lab-check or "
                "--signed-lab-help; production launch was not attempted.",
                file=sys.stderr,
            )
            return 2
        return historical_launch(arguments.component_id)
    if sum((check, help_only, native_help)) != 1:
        print("REFUSED: conflicting laboratory modes.", file=sys.stderr)
        return 2
    if native_help != (arguments.native_envelope is not None):
        print("REFUSED: native evidence requires native help mode.", file=sys.stderr)
        return 2
    if arguments.component_id != "quillan":
        print("REFUSED: signed laboratory mode supports Quillan only.", file=sys.stderr)
        return 2
    if any(value is None or value == "" for value in flags.values()):
        print(
            "REFUSED: all six signed laboratory evidence fields are required.",
            file=sys.stderr,
        )
        return 2
    # Deliberate late import: the ordinary suite launch does not import the lab.
    from paper_data_suite.evergreen_signed_lab_launch import main as lab_main

    cli = [
        "--lab-venv",
        str(flags["lab_venv"]),
        "--wheel",
        str(flags["wheel"]),
        "--trust-policy",
        str(flags["trust_policy"]),
        "--trust-sha256",
        str(flags["trust_sha256"]),
        "--registry",
        str(flags["registry"]),
        "--module",
        str(flags["module"]),
    ]
    if help_only:
        cli.append("--execute-help")
    if native_help:
        cli.extend(
            (
                "--native-envelope",
                str(arguments.native_envelope),
                "--native-execute-help",
            )
        )
    return lab_main(cli)


__all__ = ("add_signed_lab_arguments", "dispatch_launch")
