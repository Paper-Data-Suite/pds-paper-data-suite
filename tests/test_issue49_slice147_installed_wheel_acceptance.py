"""Slice 147: offline, pip-installed synthetic wheel metadata acceptance.

The wheels in this test are TEST FIXTURES, not official releases. They are
installed only under pytest's temporary directory with --no-index and --no-deps.
No module code is imported, launched, downloaded, or installed in the active env.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from importlib import metadata
from pathlib import Path
from typing import Callable

import pytest

from paper_data_suite.evergreen_local_compatibility import (
    LocalCompatibilityReport,
    Readiness,
    inspect_local_compatibility,
)
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS

_VERSIONS = {
    "core": "0.6.6",
    "scoreform": "0.13.0",
    "quillan": "0.10.6",
    "concord": "0.3.4",
    "meridian": "0.4.2",
    "vitrine": "0.4.0",
    "portia": "0.2.0",
}


def _wheel(
    wheelhouse: Path,
    component_id: str,
    *,
    version: str | None = None,
    requirement: str | None = None,
    target_override: str | None = None,
    shadow_script: str | None = None,
    distribution_override: str | None = None,
) -> Path:
    """Build a minimal valid PEP 427 fixture wheel, never an official wheel."""
    definition = next(
        item for item in APPROVED_COMPONENTS if item.component_id == component_id
    )
    name = distribution_override or definition.distribution
    version = version or _VERSIONS[component_id]
    safe_name = name.replace("-", "_")
    dist_info = f"{safe_name}-{version}.dist-info"
    module = (
        safe_name if distribution_override else
        definition.console_scripts[0].target.split(":")[0].split(".")[0]
    )
    wheel = wheelhouse / f"{safe_name}-{version}-py3-none-any.whl"
    requirement = (
        requirement if requirement is not None
        else ("" if component_id == "core" else "pds-core>=0.6.5,<0.7")
    )
    metadata_text = (
        "Metadata-Version: 2.1\n"
        f"Name: {name}\nVersion: {version}\n"
        "Requires-Python: >=3.11,<3.15\n"
        + (f"Requires-Dist: {requirement}\n" if requirement else "")
    )
    entries = ["[console_scripts]"]
    if shadow_script is not None:
        entries.append(f"{shadow_script} = fixture.cli:main")
    else:
        for index, expected in enumerate(definition.console_scripts):
            target = (
                target_override if target_override and index == 0
                else expected.target
            )
            entries.append(f"{expected.name} = {target}")
    files = {
        f"{module}/__init__.py": (
            "raise AssertionError('wheel fixture module code was imported')\n"
        ).encode(),
        f"{dist_info}/METADATA": metadata_text.encode(),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: suite-147-test-only\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n"
        ).encode(),
        f"{dist_info}/entry_points.txt": ("\n".join(entries) + "\n").encode(),
    }
    record_name = f"{dist_info}/RECORD"
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for path, blob in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(blob).digest()).rstrip(b"=")
        writer.writerow((path, "sha256=" + digest.decode("ascii"), str(len(blob))))
    writer.writerow((record_name, "", ""))
    files[record_name] = record.getvalue().encode()
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path, blob in sorted(files.items()):
            output.writestr(path, blob)
    return wheel


def _install(target: Path, wheel_files: tuple[Path, ...]) -> None:
    """Install ONLY into a fresh pytest temp directory, with networking off."""
    assert not target.exists()
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--isolated",
            "--disable-pip-version-check", "--no-index", "--no-deps",
            "--target", str(target), *(str(item) for item in wheel_files),
        ],
        cwd=target.parent,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, (
        "Offline installation of synthetic test wheels failed: "
        + result.stderr[-1200:]
    )


def _inspect(
    monkeypatch: pytest.MonkeyPatch,
    target: Path,
) -> LocalCompatibilityReport:
    """Observe pip-installed dist-info, not manually invented package objects."""
    original = metadata.distributions
    monkeypatch.setattr(
        metadata,
        "distributions",
        lambda: original(path=[str(target)]),
    )
    monkeypatch.setattr(sys, "prefix", str(target))
    return inspect_local_compatibility()


@pytest.fixture(scope="module")
def wheelhouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    home = tmp_path_factory.mktemp("suite147-synthetic-wheelhouse")
    for component in APPROVED_COMPONENTS:
        _wheel(home, component.component_id)
    return home


@pytest.fixture
def installed(
    wheelhouse: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., LocalCompatibilityReport]:
    def setup(*ids: str) -> LocalCompatibilityReport:
        wheel_files = tuple(
            next(wheelhouse.glob(
                definition.distribution.replace("-", "_")
                + "-" + _VERSIONS[component_id] + "-*.whl"
            ))
            for component_id in ids
            for definition in APPROVED_COMPONENTS
            if definition.component_id == component_id
        )
        assert len(wheel_files) == len(ids)
        target = tmp_path / "temporary-wheel-target"
        _install(target, wheel_files)
        return _inspect(monkeypatch, target)

    return setup


def test_all_seven_real_installed_fixture_wheels_have_expected_metadata(
    installed: Callable[..., LocalCompatibilityReport],
) -> None:
    report = installed(*_VERSIONS)
    assert len(report.components) == 7
    for component_id, version in _VERSIONS.items():
        row = report.for_component(component_id)
        assert row is not None
        assert row.installed_version == version
        assert row.readiness is Readiness.COMPATIBLE, (component_id, row.reason_codes)
        assert row.provenance.value == "PROVENANCE_UNVERIFIED"
    assert report.for_component("meridian").historical_evidence.value == (
        "NOT_PREVIOUSLY_INTEGRATION_TESTED"
    )


def test_newer_quillan_real_installed_fixture_wheel_is_locally_compatible(
    installed: Callable[..., LocalCompatibilityReport],
) -> None:
    report = installed("core", "quillan")
    quillan = report.for_component("quillan")
    assert quillan is not None
    assert quillan.readiness is Readiness.COMPATIBLE
    assert quillan.installed_version == "0.10.6"
    assert quillan.historical_evidence.value == "NOT_PREVIOUSLY_INTEGRATION_TESTED"


def test_real_wheel_metadata_missing_core_blocks_quillan(
    installed: Callable[..., LocalCompatibilityReport],
) -> None:
    report = installed("quillan")
    row = report.for_component("quillan")
    assert row is not None
    assert row.readiness is Readiness.INCOMPATIBLE
    assert "core_not_compatible" in row.reason_codes


def test_real_wheel_metadata_core_0_7_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    items = (
        _wheel(wheelhouse, "core", version="0.7.0"),
        _wheel(wheelhouse, "quillan"),
    )
    target = tmp_path / "installed"
    _install(target, items)
    report = _inspect(monkeypatch, target)
    core = report.for_component("core")
    quillan = report.for_component("quillan")
    assert core is not None and core.readiness is Readiness.INCOMPATIBLE
    assert quillan is not None and "core_not_compatible" in quillan.reason_codes


def test_real_wheel_wrong_console_target_is_rejected_without_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    target = tmp_path / "installed"
    _install(target, (
        _wheel(wheelhouse, "core"),
        _wheel(wheelhouse, "quillan", target_override="unknown.cli:main"),
    ))
    report = _inspect(monkeypatch, target)
    row = report.for_component("quillan")
    assert row is not None
    assert row.readiness is Readiness.INCOMPATIBLE
    assert "console_script_target_mismatch" in row.reason_codes


def test_real_wheel_unmet_dependency_blocks_scoreform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    target = tmp_path / "installed"
    _install(target, (
        _wheel(wheelhouse, "core"),
        _wheel(wheelhouse, "scoreform", requirement="absent-pds-lib>=4"),
    ))
    report = _inspect(monkeypatch, target)
    row = report.for_component("scoreform")
    assert row is not None
    assert row.readiness is Readiness.INCOMPATIBLE
    assert "dependency_missing" in row.reason_codes


def test_real_wheel_duplicate_console_ownership_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    target = tmp_path / "installed"
    _install(target, (
        _wheel(wheelhouse, "core"),
        _wheel(wheelhouse, "quillan"),
        _wheel(
            wheelhouse, "quillan", version="1.0",
            distribution_override="foreign-script-owner",
            shadow_script="quillan",
        ),
    ))
    report = _inspect(monkeypatch, target)
    row = report.for_component("quillan")
    assert row is not None
    assert row.readiness is Readiness.INCOMPATIBLE
    assert "console_script_ambiguous" in row.reason_codes


def test_real_wheel_editable_marker_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    target = tmp_path / "installed"
    _install(target, (
        _wheel(wheelhouse, "core"),
        _wheel(wheelhouse, "portia"),
    ))
    # pip writes direct_url.json itself for local wheel installs. Set the
    # installed metadata to represent an editable deployment explicitly.
    direct = target / "pds_portia-0.2.0.dist-info" / "direct_url.json"
    direct.write_text(
        json.dumps({"url": "file:///fixture", "dir_info": {"editable": True}}),
        encoding="utf-8",
    )
    report = _inspect(monkeypatch, target)
    row = report.for_component("portia")
    assert row is not None
    assert row.readiness is Readiness.INCOMPATIBLE
    assert "editable_pds_install" in row.reason_codes


def test_actual_wheel_metadata_is_read_without_module_imports(
    wheelhouse: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "installed"
    _install(target, (
        wheelhouse / "pds_core-0.6.6-py3-none-any.whl",
        wheelhouse / "quillan-0.10.6-py3-none-any.whl",
    ))
    before = {
        name for name in sys.modules
        if name in {"quillan", "pds_core"}
        or name.startswith(("quillan.", "pds_core."))
    }
    report = _inspect(monkeypatch, target)
    quillan = report.for_component("quillan")
    assert quillan is not None and quillan.readiness is Readiness.COMPATIBLE
    after = {
        name for name in sys.modules
        if name in {"quillan", "pds_core"}
        or name.startswith(("quillan.", "pds_core."))
    }
    assert after == before
