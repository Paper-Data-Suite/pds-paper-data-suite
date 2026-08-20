"""Validate the built Paper Data Suite wheel foundation."""

from __future__ import annotations

import argparse
import configparser
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

EXPECTED_DISTRIBUTION = "paper-data-suite"
EXPECTED_VERSION = "0.1.0.dev0"
EXPECTED_REQUIRES_PYTHON = ">=3.11"
EXPECTED_CORE_RANGE = SpecifierSet(">=0.6,<0.7")
EXPECTED_CONSOLE_TARGET = "paper_data_suite.cli:main"

REQUIRED_PACKAGE_FILES = frozenset(
    {
        "paper_data_suite/__init__.py",
        "paper_data_suite/__main__.py",
        "paper_data_suite/_version.py",
        "paper_data_suite/application_launching.py",
        "paper_data_suite/applications.py",
        "paper_data_suite/artifact_verification.py",
        "paper_data_suite/bootstrap.py",
        "paper_data_suite/bootstrap_artifacts.py",
        "paper_data_suite/bootstrap_cli.py",
        "paper_data_suite/bootstrap_installation.py",
        "paper_data_suite/cli.py",
        "paper_data_suite/compatibility.py",
        "paper_data_suite/component_inspection.py",
        "paper_data_suite/environment_inspection.py",
        "paper_data_suite/workspace_setup.py",
        "paper_data_suite/workspace_cli.py",
        "paper_data_suite/data/__init__.py",
        "paper_data_suite/data/release_compatibility_v1.json",
        "paper_data_suite/py.typed",
    }
)
FORBIDDEN_WHEEL_PREFIXES = (
    "tests/",
    "scripts/",
    "docs/",
    ".github/",
)
FORBIDDEN_PDS_DISTRIBUTIONS = frozenset(
    {
        "scoreform",
        "quillan",
        "pds-concord",
        "pds-meridian",
        "pds-vitrine",
        "pds-portia",
    }
)


class PackageValidationError(RuntimeError):
    """Raised when a built wheel violates the package foundation contract."""


def _single_member(names: tuple[str, ...], suffix: str) -> str:
    matches = tuple(name for name in names if name.endswith(suffix))
    if len(matches) != 1:
        raise PackageValidationError(
            f"Expected exactly one wheel member ending with {suffix!r}; "
            f"found {len(matches)}."
        )
    return matches[0]


def _parse_metadata(text: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    current_key: str | None = None

    for raw_line in text.splitlines():
        if raw_line.startswith((" ", "\t")) and current_key is not None:
            fields[current_key][-1] += raw_line.strip()
            continue
        if ":" not in raw_line:
            current_key = None
            continue

        key, value = raw_line.split(":", 1)
        current_key = key
        fields.setdefault(key, []).append(value.strip())

    return fields


def _one_field(fields: dict[str, list[str]], key: str) -> str:
    values = fields.get(key, [])
    if len(values) != 1:
        raise PackageValidationError(
            f"Expected exactly one {key!r} metadata field; found {len(values)}."
        )
    return values[0]


def _validate_runtime_requirements(fields: dict[str, list[str]]) -> None:
    requirements = tuple(
        Requirement(value) for value in fields.get("Requires-Dist", [])
    )

    core_requirements = tuple(
        requirement
        for requirement in requirements
        if canonicalize_name(requirement.name) == "pds-core"
        and requirement.marker is None
    )
    if len(core_requirements) != 1:
        raise PackageValidationError(
            "Expected exactly one unconditional pds-core runtime requirement."
        )

    core_requirement = core_requirements[0]
    if core_requirement.specifier != EXPECTED_CORE_RANGE:
        raise PackageValidationError(
            "Unexpected Core runtime range: "
            f"{core_requirement.specifier!s}; expected {EXPECTED_CORE_RANGE!s}."
        )

    forbidden = sorted(
        requirement.name
        for requirement in requirements
        if canonicalize_name(requirement.name) in FORBIDDEN_PDS_DISTRIBUTIONS
    )
    if forbidden:
        raise PackageValidationError(
            "Sibling PDS distributions must not be dependencies: "
            + ", ".join(forbidden)
        )


def _validate_entry_points(text: str) -> None:
    parser = configparser.ConfigParser()
    parser.read_string(text)

    if not parser.has_section("console_scripts"):
        raise PackageValidationError("Wheel has no console_scripts entry points.")

    scripts = dict(parser.items("console_scripts"))
    if scripts != {"pds": EXPECTED_CONSOLE_TARGET}:
        raise PackageValidationError(
            f"Unexpected console scripts: {scripts!r}."
        )


def validate_wheel(path: Path) -> None:
    """Validate one built wheel."""
    if not path.is_file() or path.suffix != ".whl":
        raise PackageValidationError(f"Wheel does not exist: {path}")

    with zipfile.ZipFile(path) as wheel:
        names = tuple(wheel.namelist())
        name_set = frozenset(names)

        missing = sorted(REQUIRED_PACKAGE_FILES - name_set)
        if missing:
            raise PackageValidationError(
                "Wheel is missing required package files: " + ", ".join(missing)
            )

        forbidden = sorted(
            name
            for name in names
            if name.startswith(FORBIDDEN_WHEEL_PREFIXES)
            or "__pycache__/" in name
            or name.endswith((".pyc", ".pyo"))
            or ".egg-info/" in name
        )
        if forbidden:
            raise PackageValidationError(
                "Repository-only artifacts leaked into wheel: "
                + ", ".join(forbidden)
            )

        metadata_member = _single_member(names, ".dist-info/METADATA")
        fields = _parse_metadata(
            wheel.read(metadata_member).decode("utf-8")
        )

        if canonicalize_name(_one_field(fields, "Name")) != EXPECTED_DISTRIBUTION:
            raise PackageValidationError("Unexpected distribution name.")
        if _one_field(fields, "Version") != EXPECTED_VERSION:
            raise PackageValidationError("Unexpected distribution version.")
        if _one_field(fields, "Requires-Python") != EXPECTED_REQUIRES_PYTHON:
            raise PackageValidationError("Unexpected Requires-Python value.")

        _validate_runtime_requirements(fields)

        entry_points_member = _single_member(
            names, ".dist-info/entry_points.txt"
        )
        _validate_entry_points(
            wheel.read(entry_points_member).decode("utf-8")
        )

        manifest_member = (
            "paper_data_suite/data/release_compatibility_v1.json"
        )
        try:
            manifest = json.loads(
                wheel.read(manifest_member).decode("utf-8")
            )
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PackageValidationError(
                "Wheel compatibility manifest is missing or invalid."
            ) from error

        if not isinstance(manifest, dict):
            raise PackageValidationError(
                "Wheel compatibility manifest must be a JSON object."
            )
        if manifest.get("record_type") != (
            "paper_data_suite_release_compatibility_manifest"
        ):
            raise PackageValidationError(
                "Unexpected wheel compatibility manifest record type."
            )
        if manifest.get("contract_version") != "1":
            raise PackageValidationError(
                "Unexpected wheel compatibility manifest contract version."
            )
        suite = manifest.get("suite")
        if not isinstance(suite, dict):
            raise PackageValidationError(
                "Wheel compatibility manifest has no suite object."
            )
        if suite.get("distribution") != EXPECTED_DISTRIBUTION:
            raise PackageValidationError(
                "Wheel compatibility manifest distribution disagrees."
            )
        if suite.get("version") != EXPECTED_VERSION:
            raise PackageValidationError(
                "Wheel compatibility manifest suite version disagrees."
            )
        components = manifest.get("components")
        if not isinstance(components, list):
            raise PackageValidationError(
                "Wheel compatibility manifest components must be an array."
            )
        component_ids = [
            item.get("component_id")
            for item in components
            if isinstance(item, dict)
        ]
        if component_ids != [
            "concord",
            "core",
            "quillan",
            "scoreform",
            "vitrine",
        ]:
            raise PackageValidationError(
                "Wheel compatibility manifest component set changed."
            )


def build_parser() -> argparse.ArgumentParser:
    """Build the wheel-validation parser."""
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the requested wheel and return a process status."""
    args = build_parser().parse_args(argv)
    wheel = Path(cast(str, args.wheel)).resolve()
    validate_wheel(wheel)
    print(f"Validated package wheel: {wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
