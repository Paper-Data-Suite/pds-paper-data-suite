"""Explicit Suite #18 wheel/installed-contract probe; never scans teacher data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from paper_data_suite.returned_paper_installed_wheels import (
    WheelQualificationError,
    qualify_installed_profiles,
    verify_official_wheelhouse,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument(
        "--installed", action="store_true",
        help="execute actual Core/producer factories in a disposable test venv",
    )
    arguments = parser.parse_args(argv)
    try:
        verified = verify_official_wheelhouse(arguments.wheelhouse)
        if arguments.installed:
            modules = qualify_installed_profiles()
            if modules != ("quillan", "scoreform"):
                raise WheelQualificationError("unexpected installed profile subset")
        else:
            modules = ()
    except (WheelQualificationError, OSError, ValueError):
        print("SUITE18_WHEEL_QUALIFICATION_REFUSED", file=sys.stderr)
        return 2
    print(json.dumps({
        "contract": "issue18-slice6a-1",
        "wheel_count": len(verified),
        "wheel_hashes_verified": True,
        "installed_profile_factory_check": bool(arguments.installed),
        "installed_module_ids": list(modules),
        "producer_dispatch_qualified": False,
        "teacher_pilot_qualified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
