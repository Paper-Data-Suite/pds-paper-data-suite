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
EXPECTED_VERSION = "0.1.0"
EXPECTED_RELEASE_STATUS = "release"
EXPECTED_REQUIRES_PYTHON = ">=3.11"
EXPECTED_CORE_RANGE = SpecifierSet(">=0.6.3,<0.7")
EXPECTED_CONSOLE_TARGET = "paper_data_suite.cli:main"
EXPECTED_LICENSE_EXPRESSION = "MIT"
EXPECTED_RELEASE_TOOLING = {
    "tool_id": "pip",
    "distribution": "pip",
    "version": "26.2.1",
    "requires_python": ">=3.10",
    "requires_dist": [],
    "wheel": "pip-26.2.1-py3-none-any.whl",
    "sha256": (
        "71138adf1f4ca900cdb7d289c21b7494"
        "329f2332b6d85f0e1c42108c0384ed3e"
    ),
}

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
        "paper_data_suite/classroom_apply.py",
        "paper_data_suite/classroom_planning.py",
        "paper_data_suite/classroom_setup.py",
        "paper_data_suite/classroom_setup_cli.py",
        "paper_data_suite/cli.py",
        "paper_data_suite/compatibility.py",
        "paper_data_suite/component_inspection.py",
        "paper_data_suite/doctor.py",
        "paper_data_suite/environment_inspection.py",
        "paper_data_suite/release_tooling.py",
        "paper_data_suite/settings.py",
        "paper_data_suite/settings_cli.py",
        "paper_data_suite/workspace_backup.py",
        "paper_data_suite/workspace_backup_cli.py",
        "paper_data_suite/workspace_backup_verification.py",
        "paper_data_suite/workspace_restore.py",
        "paper_data_suite/workspace_setup.py",
        "paper_data_suite/workspace_cli.py",
        "paper_data_suite/data/__init__.py",
        "paper_data_suite/data/release_compatibility_v1.json",
        "paper_data_suite/data/release_tooling_v1.json",
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
        if _one_field(fields, "License-Expression") != EXPECTED_LICENSE_EXPRESSION:
            raise PackageValidationError("Unexpected wheel license expression.")
        if _one_field(fields, "License-File") != "LICENSE":
            raise PackageValidationError("Unexpected wheel license-file metadata.")

        license_member = _single_member(names, ".dist-info/licenses/LICENSE")
        source_license = (
            Path(__file__).resolve().parents[1] / "LICENSE"
        ).read_bytes()
        if wheel.read(license_member) != source_license:
            raise PackageValidationError(
                "Wheel license bytes do not match repository LICENSE."
            )

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
        if suite.get("release_status") != EXPECTED_RELEASE_STATUS:
            raise PackageValidationError(
                "Wheel compatibility manifest release status disagrees."
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

        tooling_member = "paper_data_suite/data/release_tooling_v1.json"
        try:
            tooling = json.loads(wheel.read(tooling_member).decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PackageValidationError(
                "Wheel release-tooling contract is missing or invalid."
            ) from error

        if not isinstance(tooling, dict):
            raise PackageValidationError(
                "Wheel release-tooling contract must be a JSON object."
            )
        if tooling.get("record_type") != "paper_data_suite_release_tooling":
            raise PackageValidationError(
                "Unexpected wheel release-tooling record type."
            )
        if tooling.get("contract_version") != "1":
            raise PackageValidationError(
                "Unexpected wheel release-tooling contract version."
            )
        tools = tooling.get("tools")
        if not isinstance(tools, list) or len(tools) != 1:
            raise PackageValidationError(
                "Wheel release-tooling contract must declare exactly one tool."
            )
        observed_tool = tools[0]
        if not isinstance(observed_tool, dict):
            raise PackageValidationError(
                "Wheel release-tooling entry must be a JSON object."
            )
        for key, expected in EXPECTED_RELEASE_TOOLING.items():
            if observed_tool.get(key) != expected:
                raise PackageValidationError(
                    f"Wheel release-tooling {key!r} identity changed."
                )
        url = observed_tool.get("url")
        if (
            not isinstance(url, str)
            or not url.startswith("https://files.pythonhosted.org/")
            or not url.endswith("/pip-26.2.1-py3-none-any.whl")
        ):
            raise PackageValidationError(
                "Wheel release-tooling URL is not the qualified pip artifact."
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
