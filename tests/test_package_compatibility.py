from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.check_package import PackageValidationError, validate_wheel

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT / "paper_data_suite" / "data" / "release_compatibility_v1.json"
)

_PACKAGE_FILES = (
    "paper_data_suite/__init__.py",
    "paper_data_suite/__main__.py",
    "paper_data_suite/_version.py",
    "paper_data_suite/cli.py",
    "paper_data_suite/compatibility.py",
    "paper_data_suite/data/__init__.py",
    "paper_data_suite/py.typed",
)


def _build_wheel(
    path: Path,
    *,
    include_manifest: bool = True,
    manifest_version: str | None = None,
) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest_version is not None:
        manifest["suite"]["version"] = manifest_version

    metadata = "\n".join(
        (
            "Metadata-Version: 2.4",
            "Name: paper-data-suite",
            "Version: 0.1.0.dev0",
            "Requires-Python: >=3.11",
            "Requires-Dist: pds-core<0.7,>=0.6",
            "",
        )
    )
    entry_points = "\n".join(
        (
            "[console_scripts]",
            "pds = paper_data_suite.cli:main",
            "",
        )
    )

    with zipfile.ZipFile(path, "w") as wheel:
        for member in _PACKAGE_FILES:
            wheel.writestr(member, "")
        if include_manifest:
            wheel.writestr(
                "paper_data_suite/data/release_compatibility_v1.json",
                json.dumps(manifest, sort_keys=True),
            )
        wheel.writestr(
            "paper_data_suite-0.1.0.dev0.dist-info/METADATA",
            metadata,
        )
        wheel.writestr(
            "paper_data_suite-0.1.0.dev0.dist-info/entry_points.txt",
            entry_points,
        )


def test_package_validator_accepts_manifest_bearing_wheel(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "paper_data_suite-0.1.0.dev0-py3-none-any.whl"
    _build_wheel(wheel)

    validate_wheel(wheel)


def test_package_validator_rejects_missing_manifest(tmp_path: Path) -> None:
    wheel = tmp_path / "paper_data_suite-0.1.0.dev0-py3-none-any.whl"
    _build_wheel(wheel, include_manifest=False)

    with pytest.raises(
        PackageValidationError,
        match="missing required package files",
    ):
        validate_wheel(wheel)


def test_package_validator_rejects_manifest_version_drift(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "paper_data_suite-0.1.0.dev0-py3-none-any.whl"
    _build_wheel(wheel, manifest_version="0.1.0")

    with pytest.raises(
        PackageValidationError,
        match="manifest suite version",
    ):
        validate_wheel(wheel)
