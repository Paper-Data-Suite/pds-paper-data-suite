from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

from paper_data_suite import __version__

EXPECTED_VERSION = "0.1.0.dev0"


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_public_version_is_development_version() -> None:
    assert __version__ == EXPECTED_VERSION


def test_installed_distribution_version_matches_package() -> None:
    assert importlib.metadata.version("paper-data-suite") == __version__


def test_pyproject_uses_package_version_as_dynamic_source() -> None:
    pyproject = (_repository_root() / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert 'dynamic = ["version"]' in pyproject
    assert (
        'version = { attr = "paper_data_suite._version.__version__" }'
        in pyproject
    )


def test_production_version_literal_has_one_authoritative_source() -> None:
    package_root = _repository_root() / "paper_data_suite"
    matches: list[Path] = []

    for path in package_root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r'["\']0\.1\.0\.dev0["\']', text):
            matches.append(path)

    assert matches == [package_root / "_version.py"]
