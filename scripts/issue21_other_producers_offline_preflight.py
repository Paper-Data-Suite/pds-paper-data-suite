"""Suite #21 C0/D0: offline Quillan/Concord Core wheel+metadata probe.

Reuses the B1.0 ScoreForm contract and #16 wheel byte/hash inspector.
No provider import, code execution, workspace access or publication action.

Explicit invocation:
    python -m scripts.issue21_other_producers_offline_preflight
        --owner quillan --wheelhouse PATH
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.issue21_scoreform_offline_preflight import (
    inspect_named_producer_offline_release,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--owner", required=True, choices=("quillan", "concord")
    )
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args(argv)
    result = inspect_named_producer_offline_release(
        args.wheelhouse, owner_id=args.owner
    )
    print(f"PDS21_C0D0_OFFLINE_{args.owner.upper()} {result.code}")
    # A zero status reports matching offline observations, NEVER admission.
    return 0 if result.metadata_consistent else 1


if __name__ == "__main__":
    raise SystemExit(main())
