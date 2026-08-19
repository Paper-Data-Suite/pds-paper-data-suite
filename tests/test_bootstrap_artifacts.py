from __future__ import annotations

import configparser
import hashlib
import zipfile
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from paper_data_suite.bootstrap import (
    EnvironmentMarkerIdentity,
    EnvironmentSnapshot,
    InstalledDistribution,
    build_bootstrap_plan,
)
from paper_data_suite.bootstrap_artifacts import (
    BootstrapArtifactError,
    component_release_url,
    pds_constraints_text,
    required_component_artifacts,
    verify_required_artifacts,
    write_pds_constraints,
)
from paper_data_suite.compatibility import (
    ComponentCompatibility,
    EntryPointExpectation,
    load_release_compatibility_manifest,
)

_MANIFEST_SHA256 = "a" * 64


class _CaseSensitiveConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


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


def _write_test_wheel(
    path: Path,
    component: ComponentCompatibility,
) -> str:
    normalized = component.distribution.replace("-", "_").replace(".", "_")
    dist_info = f"{normalized}-{component.version}.dist-info"
    metadata = (
        "Metadata-Version: 2.4\n"
        f"Name: {component.distribution}\n"
        f"Version: {component.version}\n"
        f"Requires-Python: {component.requires_python}\n"
        "\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        if component.entry_points:
            archive.writestr(
                f"{dist_info}/entry_points.txt",
                _entry_point_text(component.entry_points),
            )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan(
    *,
    selected: tuple[str, ...] = (),
    installed: tuple[InstalledDistribution, ...] = (),
):
    manifest = load_release_compatibility_manifest()
    snapshot = EnvironmentSnapshot(
        path=r"C:\Temp\pds-target",
        exists=bool(installed),
        is_virtual_environment=bool(installed),
        python_version="3.11.9",
        marker=(
            None
            if not installed
            else EnvironmentMarkerIdentity(
                suite_version=manifest.suite.version,
                compatibility_manifest_sha256=_MANIFEST_SHA256,
            )
        ),
        installed_distributions=installed,
    )
    return manifest, build_bootstrap_plan(
        manifest,
        compatibility_manifest_sha256=_MANIFEST_SHA256,
        environment=snapshot,
        selected_component_ids=selected,
    )


def test_release_url_is_exact_and_never_latest() -> None:
    manifest = load_release_compatibility_manifest()
    core = next(
        item for item in manifest.components if item.component_id == "core"
    )

    url = component_release_url(core)

    assert url.endswith(
        "/pds-core/releases/download/v0.6.0/"
        "pds_core-0.6.0-py3-none-any.whl"
    )
    assert "/latest/" not in url
    assert "/releases/latest" not in url


def test_required_artifacts_include_only_missing_selected_components() -> None:
    manifest, plan = _plan(selected=("quillan", "vitrine"))

    requirements = required_component_artifacts(manifest, plan)

    assert tuple(item.component_id for item in requirements) == (
        "core",
        "quillan",
        "vitrine",
    )


def test_unselected_optional_artifact_is_not_required() -> None:
    manifest, plan = _plan(selected=("vitrine",))

    requirements = required_component_artifacts(manifest, plan)

    assert "scoreform" not in {
        item.component_id for item in requirements
    }


def test_exact_installed_component_does_not_require_artifact() -> None:
    manifest = load_release_compatibility_manifest()
    vitrine = next(
        item for item in manifest.components if item.component_id == "vitrine"
    )
    manifest, plan = _plan(
        selected=("vitrine",),
        installed=(
            InstalledDistribution(
                distribution=vitrine.distribution,
                version=vitrine.version,
            ),
        ),
    )

    requirements = required_component_artifacts(manifest, plan)

    assert "vitrine" not in {
        item.component_id for item in requirements
    }


def test_blocked_plan_cannot_prepare_artifacts() -> None:
    manifest, plan = _plan(
        installed=(
            InstalledDistribution(
                distribution="pds-core",
                version="9.9.9",
            ),
        )
    )

    with pytest.raises(
        BootstrapArtifactError,
        match="blocked bootstrap plan",
    ):
        required_component_artifacts(manifest, plan)


def test_constraints_cover_only_exact_pds_owned_distributions() -> None:
    manifest = load_release_compatibility_manifest()

    lines = pds_constraints_text(manifest).splitlines()

    assert lines == [
        "paper-data-suite==0.1.0.dev0",
        "pds-concord==0.2.0",
        "pds-core==0.6.0",
        "pds-vitrine==0.2.0",
        "quillan==0.9.0",
        "scoreform==0.10.0",
    ]
    assert all("numpy" not in line.lower() for line in lines)
    assert all("opencv" not in line.lower() for line in lines)
    assert all("pillow" not in line.lower() for line in lines)


def test_write_constraints_is_deterministic(tmp_path: Path) -> None:
    manifest = load_release_compatibility_manifest()
    target = tmp_path / "pds-constraints.txt"

    first = write_pds_constraints(target, manifest)
    first_bytes = target.read_bytes()
    second = write_pds_constraints(target, manifest)

    assert first == second
    assert target.read_bytes() == first_bytes
    assert first_bytes.endswith(b"\n")


def test_verify_required_artifacts_accepts_exact_required_wheels(
    tmp_path: Path,
) -> None:
    manifest, plan = _plan(selected=("vitrine",))
    components = {
        item.component_id: item for item in manifest.components
    }
    replacements: list[ComponentCompatibility] = []
    for requirement in required_component_artifacts(manifest, plan):
        component = components[requirement.component_id]
        wheel = tmp_path / component.release.wheel
        digest = _write_test_wheel(wheel, component)
        replacements.append(
            replace(
                component,
                release=replace(component.release, sha256=digest),
            )
        )
    adjusted = replace(
        manifest,
        components=tuple(
            next(
                (
                    replacement
                    for replacement in replacements
                    if replacement.component_id == component.component_id
                ),
                component,
            )
            for component in manifest.components
        ),
    )

    verified = verify_required_artifacts(adjusted, plan, tmp_path)

    assert tuple(item.component_id for item in verified) == (
        "core",
        "vitrine",
    )


def test_missing_required_artifact_fails(tmp_path: Path) -> None:
    manifest, plan = _plan(selected=("vitrine",))

    with pytest.raises(
        BootstrapArtifactError,
        match="core artifact verification failed",
    ):
        verify_required_artifacts(manifest, plan, tmp_path)


def test_tampered_required_artifact_fails(tmp_path: Path) -> None:
    manifest, plan = _plan()
    core = next(
        item for item in manifest.components if item.component_id == "core"
    )
    wheel = tmp_path / core.release.wheel
    wheel.write_bytes(b"tampered")

    with pytest.raises(
        BootstrapArtifactError,
        match="SHA-256 mismatch",
    ):
        verify_required_artifacts(manifest, plan, tmp_path)
