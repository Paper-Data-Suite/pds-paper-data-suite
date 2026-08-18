from __future__ import annotations

import configparser
import hashlib
import zipfile
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from paper_data_suite.compatibility import (
    ComponentCompatibility,
    EntryPointExpectation,
    load_release_compatibility_manifest,
)
from scripts.verify_compatibility_artifacts import (
    ArtifactVerificationError,
    verify_component_wheel,
)


class _CaseSensitiveConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _component(component_id: str) -> ComponentCompatibility:
    manifest = load_release_compatibility_manifest()
    return next(
        item for item in manifest.components if item.component_id == component_id
    )


def _entry_point_text(expectations: tuple[EntryPointExpectation, ...]) -> str:
    groups: dict[str, dict[str, str]] = {}
    for item in expectations:
        groups.setdefault(item.group, {})[item.name] = item.target

    parser = _CaseSensitiveConfigParser(interpolation=None)
    for group, values in groups.items():
        if values:
            parser[group] = values

    output = StringIO()
    parser.write(output)
    return output.getvalue()


def _write_wheel(
    path: Path,
    component: ComponentCompatibility,
    *,
    version: str | None = None,
    entry_points: tuple[EntryPointExpectation, ...] | None = None,
) -> str:
    normalized = component.distribution.replace("-", "_").replace(".", "_")
    dist_info = f"{normalized}-{component.version}.dist-info"
    metadata = (
        "Metadata-Version: 2.4\n"
        f"Name: {component.distribution}\n"
        f"Version: {version or component.version}\n"
        f"Requires-Python: {component.requires_python}\n"
        "\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        selected = component.entry_points if entry_points is None else entry_points
        if selected:
            archive.writestr(
                f"{dist_info}/entry_points.txt",
                _entry_point_text(selected),
            )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _with_test_digest(
    component: ComponentCompatibility,
    digest: str,
) -> ComponentCompatibility:
    release = replace(component.release, sha256=digest)
    return replace(component, release=release)


def test_exact_component_wheel_passes(tmp_path: Path) -> None:
    component = _component("scoreform")
    wheel = tmp_path / component.release.wheel
    digest = _write_wheel(wheel, component)

    verify_component_wheel(_with_test_digest(component, digest), wheel)


def test_digest_mismatch_fails_before_metadata_trust(tmp_path: Path) -> None:
    component = _component("core")
    wheel = tmp_path / component.release.wheel
    _write_wheel(wheel, component)

    with pytest.raises(
        ArtifactVerificationError,
        match="SHA-256 mismatch",
    ):
        verify_component_wheel(component, wheel)


def test_version_mismatch_fails(tmp_path: Path) -> None:
    component = _component("vitrine")
    wheel = tmp_path / component.release.wheel
    digest = _write_wheel(wheel, component, version="9.9.9")

    with pytest.raises(
        ArtifactVerificationError,
        match="version identity mismatch",
    ):
        verify_component_wheel(_with_test_digest(component, digest), wheel)


def test_entry_point_target_mismatch_fails(tmp_path: Path) -> None:
    component = _component("quillan")
    wheel = tmp_path / component.release.wheel
    altered = tuple(
        replace(item, target="quillan.cli:other")
        if item.group == "console_scripts" and item.name == "quillan"
        else item
        for item in component.entry_points
    )
    digest = _write_wheel(wheel, component, entry_points=altered)

    with pytest.raises(
        ArtifactVerificationError,
        match="entry-point metadata",
    ):
        verify_component_wheel(_with_test_digest(component, digest), wheel)


def test_filename_mismatch_fails(tmp_path: Path) -> None:
    component = _component("concord")
    wheel = tmp_path / "wrong.whl"
    digest = _write_wheel(wheel, component)

    with pytest.raises(
        ArtifactVerificationError,
        match="filename mismatch",
    ):
        verify_component_wheel(_with_test_digest(component, digest), wheel)
