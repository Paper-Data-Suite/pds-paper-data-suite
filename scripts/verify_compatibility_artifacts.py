"""Authenticate exact published component wheels declared by the suite manifest."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from paper_data_suite.artifact_verification import (
    ArtifactVerificationError,
    verify_artifact_directory,
    verify_component_wheel,
    verify_release_tool_wheel,
)
from paper_data_suite.compatibility import CompatibilityManifestError
from paper_data_suite.release_tooling import (
    ReleaseToolingError,
    load_release_tooling_contract,
)

__all__ = (
    "ArtifactVerificationError",
    "verify_artifact_directory",
    "verify_component_wheel",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        verify_artifact_directory(args.artifact_dir)
        tooling = load_release_tooling_contract()
        for tool in tooling.tools:
            verify_release_tool_wheel(
                tool,
                args.artifact_dir / tool.wheel,
            )
    except (
        OSError,
        CompatibilityManifestError,
        ReleaseToolingError,
        ArtifactVerificationError,
    ) as error:
        print(f"Release artifact verification failed: {error}")
        return 1

    print(
        "Release artifacts passed: exact component/tool filenames, SHA-256 "
        "digests, wheel metadata, Python requirements, and declared public "
        "entry points verified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
