"""Validate the bundled release-compatibility manifest against suite metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path

from paper_data_suite import __version__
from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    load_release_compatibility_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PROJECT_NAME = "paper-data-suite"
EXPECTED_PROJECT_PYTHON = ">=3.11"
EXPECTED_CORE_REQUIREMENT = "pds-core>=0.6,<0.7"
EXPECTED_COMPONENT_IDS = (
    "concord",
    "core",
    "quillan",
    "scoreform",
    "vitrine",
)


class ManifestValidationError(RuntimeError):
    """Raised when repository metadata drifts from the manifest contract."""


def validate_repository_manifest() -> None:
    """Validate the active manifest and its repository-level package anchors."""
    manifest = load_release_compatibility_manifest()

    project_data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = project_data.get("project")
    if not isinstance(project, dict):
        raise ManifestValidationError("pyproject.toml has no [project] table")

    if project.get("name") != EXPECTED_PROJECT_NAME:
        raise ManifestValidationError(
            f"project name must remain {EXPECTED_PROJECT_NAME!r}"
        )
    if project.get("requires-python") != EXPECTED_PROJECT_PYTHON:
        raise ManifestValidationError(
            f"project Requires-Python must remain {EXPECTED_PROJECT_PYTHON!r}"
        )
    if manifest.suite.version != __version__:
        raise ManifestValidationError(
            "manifest suite version disagrees with package version"
        )

    raw_dependencies = project.get("dependencies")
    if not isinstance(raw_dependencies, list) or not all(
        isinstance(item, str) for item in raw_dependencies
    ):
        raise ManifestValidationError("project dependencies must be a string list")
    core_requirements = [
        item.replace(" ", "")
        for item in raw_dependencies
        if item.lower().replace("_", "-").startswith("pds-core")
    ]
    if core_requirements != [EXPECTED_CORE_REQUIREMENT]:
        raise ManifestValidationError(
            "suite package must require exactly pds-core>=0.6,<0.7"
        )

    component_ids = tuple(item.component_id for item in manifest.components)
    if component_ids != EXPECTED_COMPONENT_IDS:
        raise ManifestValidationError(
            "active development manifest component set changed without audit: "
            + ", ".join(component_ids)
        )

    core = next(item for item in manifest.components if item.component_id == "core")
    if not core.required:
        raise ManifestValidationError("Core must remain required")
    if any(
        item.required for item in manifest.components if item.component_id != "core"
    ):
        raise ManifestValidationError("sibling applications must remain optional")


def main() -> int:
    try:
        validate_repository_manifest()
    except (
        OSError,
        tomllib.TOMLDecodeError,
        CompatibilityManifestError,
        ManifestValidationError,
    ) as error:
        print(f"Compatibility manifest validation failed: {error}")
        return 1

    print(
        "Compatibility manifest passed: contract v1; suite 0.1.0.dev0; "
        "Python >=3.11,<3.15; five exact published PDS component releases."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
