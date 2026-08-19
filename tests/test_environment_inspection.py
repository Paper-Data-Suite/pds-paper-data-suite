from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_data_suite.environment_inspection import (
    ENVIRONMENT_MARKER_FILENAME,
    EnvironmentInspectionError,
    environment_marker_text,
    inspect_windows_environment,
    parse_environment_marker,
    write_environment_marker,
)

_DIGEST = "a" * 64


def _marker(**changes: object) -> str:
    payload: dict[str, object] = {
        "record_type": "paper_data_suite_environment",
        "contract_version": "1",
        "suite_version": "0.1.0.dev0",
        "compatibility_manifest_sha256": _DIGEST,
    }
    payload.update(changes)
    return json.dumps(payload)


def _write_dist_info(
    site_packages: Path,
    name: str,
    version: str,
    *,
    editable: bool = False,
) -> None:
    normalized = name.replace("-", "_")
    dist_info = site_packages / f"{normalized}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.4\n"
        f"Name: {name}\n"
        f"Version: {version}\n\n",
        encoding="utf-8",
    )
    if editable:
        (dist_info / "direct_url.json").write_text(
            json.dumps(
                {
                    "url": "file:///C:/Dev/source",
                    "dir_info": {"editable": True},
                }
            ),
            encoding="utf-8",
        )


def _write_windows_venv(root: Path, *, version: str = "3.11.9") -> None:
    (root / "Scripts").mkdir(parents=True)
    (root / "Scripts" / "python.exe").write_bytes(b"synthetic")
    (root / "Lib" / "site-packages").mkdir(parents=True)
    (root / "pyvenv.cfg").write_text(
        "home = C:\\Python311\n"
        "include-system-site-packages = false\n"
        f"version = {version}\n",
        encoding="utf-8",
    )


def test_parse_environment_marker_normalizes_digest() -> None:
    marker = parse_environment_marker(
        _marker(compatibility_manifest_sha256=_DIGEST.upper())
    )

    assert marker.suite_version == "0.1.0.dev0"
    assert marker.compatibility_manifest_sha256 == _DIGEST


def test_parse_environment_marker_rejects_unknown_fields() -> None:
    with pytest.raises(EnvironmentInspectionError, match="unknown"):
        parse_environment_marker(_marker(extra="nope"))


def test_missing_environment_uses_seed_python_without_side_effects(
    tmp_path: Path,
) -> None:
    target = tmp_path / "missing"

    snapshot = inspect_windows_environment(
        target,
        seed_python_version="3.12.4",
    )

    assert not snapshot.exists
    assert not snapshot.is_virtual_environment
    assert snapshot.python_version == "3.12.4"
    assert snapshot.installed_distributions == ()
    assert not target.exists()


def test_existing_windows_venv_is_inspected_as_filesystem_metadata(
    tmp_path: Path,
) -> None:
    target = tmp_path / "env"
    _write_windows_venv(target, version="3.13.7")
    (target / ENVIRONMENT_MARKER_FILENAME).write_text(
        _marker(),
        encoding="utf-8",
    )
    site_packages = target / "Lib" / "site-packages"
    _write_dist_info(site_packages, "paper-data-suite", "0.1.0.dev0")
    _write_dist_info(site_packages, "pds-core", "0.6.0")

    snapshot = inspect_windows_environment(
        target,
        seed_python_version="3.11.9",
    )

    assert snapshot.exists
    assert snapshot.is_virtual_environment
    assert snapshot.python_version == "3.13.7"
    assert snapshot.marker is not None
    assert snapshot.marker_error is None
    assert tuple(
        (item.distribution, item.version)
        for item in snapshot.installed_distributions
    ) == (
        ("paper-data-suite", "0.1.0.dev0"),
        ("pds-core", "0.6.0"),
    )




def test_tracked_editable_pds_distribution_is_detected(tmp_path: Path) -> None:
    target = tmp_path / "env"
    _write_windows_venv(target)
    site_packages = target / "Lib" / "site-packages"
    _write_dist_info(
        site_packages,
        "scoreform",
        "0.10.0",
        editable=True,
    )

    snapshot = inspect_windows_environment(
        target,
        seed_python_version="3.11.9",
        tracked_distributions=frozenset({"scoreform"}),
    )

    assert len(snapshot.installed_distributions) == 1
    assert snapshot.installed_distributions[0].editable is True




def test_tracked_editable_pds_distribution_with_utf8_bom_is_detected(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "env"
    _write_windows_venv(environment)
    site_packages = environment / "Lib" / "site-packages"
    _write_dist_info(
        site_packages,
        "scoreform",
        "0.10.0",
        editable=True,
    )
    direct_url = next(site_packages.glob("scoreform-0.10.0.dist-info")) / (
        "direct_url.json"
    )
    direct_url.write_bytes(b"\xef\xbb\xbf" + direct_url.read_bytes())

    snapshot = inspect_windows_environment(
        environment,
        seed_python_version="3.11.9",
        tracked_distributions=frozenset({"scoreform"}),
    )

    assert snapshot.installed_distributions[0].editable is True

def test_untracked_malformed_direct_url_does_not_block_inspection(
    tmp_path: Path,
) -> None:
    target = tmp_path / "env"
    _write_windows_venv(target)
    site_packages = target / "Lib" / "site-packages"
    _write_dist_info(site_packages, "third-party", "1.0")
    direct_url = next(site_packages.glob("third_party-1.0.dist-info")) / (
        "direct_url.json"
    )
    direct_url.write_text("{bad", encoding="utf-8")

    snapshot = inspect_windows_environment(
        target,
        seed_python_version="3.11.9",
        tracked_distributions=frozenset({"scoreform"}),
    )

    assert snapshot.installed_distributions[0].editable is False

def test_malformed_marker_is_reported_without_execution(tmp_path: Path) -> None:
    target = tmp_path / "env"
    _write_windows_venv(target)
    (target / ENVIRONMENT_MARKER_FILENAME).write_text("{bad", encoding="utf-8")

    snapshot = inspect_windows_environment(
        target,
        seed_python_version="3.11.9",
    )

    assert snapshot.is_virtual_environment
    assert snapshot.marker is None
    assert snapshot.marker_error is not None
    assert "invalid JSON" in snapshot.marker_error


def test_directory_that_only_looks_like_venv_is_not_valid(tmp_path: Path) -> None:
    target = tmp_path / "env"
    (target / "Scripts").mkdir(parents=True)
    (target / "Scripts" / "python.exe").write_bytes(b"synthetic")

    snapshot = inspect_windows_environment(
        target,
        seed_python_version="3.11.9",
    )

    assert snapshot.exists
    assert not snapshot.is_virtual_environment


def test_environment_marker_text_is_deterministic() -> None:
    identity = parse_environment_marker(_marker())

    first = environment_marker_text(identity)
    second = environment_marker_text(identity)

    assert first == second
    assert first.endswith("\n")
    assert json.loads(first)["compatibility_manifest_sha256"] == _DIGEST


def test_write_environment_marker_is_atomic_and_parseable(
    tmp_path: Path,
) -> None:
    target = tmp_path / "env"
    _write_windows_venv(target)
    identity = parse_environment_marker(_marker())

    marker_path = write_environment_marker(target, identity)

    assert marker_path == target / ENVIRONMENT_MARKER_FILENAME
    assert parse_environment_marker(
        marker_path.read_text(encoding="utf-8")
    ) == identity
    assert not tuple(target.glob(".pds-suite-environment.json.*.tmp"))


def test_write_environment_marker_rejects_non_venv(tmp_path: Path) -> None:
    target = tmp_path / "ordinary"
    target.mkdir()
    identity = parse_environment_marker(_marker())

    with pytest.raises(
        EnvironmentInspectionError,
        match="outside an existing Windows virtual environment",
    ):
        write_environment_marker(target, identity)
