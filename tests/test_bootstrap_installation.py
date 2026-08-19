from __future__ import annotations

from pathlib import Path

import pytest

from paper_data_suite.bootstrap import (
    EnvironmentSnapshot,
    InstalledDistribution,
)
from paper_data_suite.bootstrap_installation import (
    BootstrapInstallationError,
    verify_installed_composition,
    verify_installed_import_layout,
)
from paper_data_suite.compatibility import load_release_compatibility_manifest


def _snapshot(
    installed: tuple[InstalledDistribution, ...],
    *,
    python_version: str = "3.11.9",
) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        path=r"C:\Temp\pds-target",
        exists=True,
        is_virtual_environment=True,
        python_version=python_version,
        marker=None,
        installed_distributions=installed,
    )


def _exact_install(
    *optional_component_ids: str,
) -> tuple[InstalledDistribution, ...]:
    manifest = load_release_compatibility_manifest()
    selected = set(optional_component_ids)
    result = [
        InstalledDistribution(
            distribution=manifest.suite.distribution,
            version=manifest.suite.version,
        )
    ]
    for component in manifest.components:
        if component.required or component.component_id in selected:
            result.append(
                InstalledDistribution(
                    distribution=component.distribution,
                    version=component.version,
                )
            )
    return tuple(result)


def test_exact_required_installation_passes_without_marker() -> None:
    manifest = load_release_compatibility_manifest()

    verified = verify_installed_composition(
        manifest,
        _snapshot(_exact_install()),
    )

    assert tuple(item.component_id for item in verified) == (
        "suite",
        "core",
    )


def test_selected_optional_components_are_required() -> None:
    manifest = load_release_compatibility_manifest()

    verified = verify_installed_composition(
        manifest,
        _snapshot(_exact_install("quillan", "vitrine")),
        selected_component_ids=("quillan", "vitrine"),
    )

    assert tuple(item.component_id for item in verified) == (
        "suite",
        "core",
        "quillan",
        "vitrine",
    )


def test_missing_selected_optional_fails() -> None:
    manifest = load_release_compatibility_manifest()

    with pytest.raises(
        BootstrapInstallationError,
        match="required installed distribution is missing: quillan",
    ):
        verify_installed_composition(
            manifest,
            _snapshot(_exact_install()),
            selected_component_ids=("quillan",),
        )


def test_mismatched_unselected_known_pds_distribution_fails() -> None:
    manifest = load_release_compatibility_manifest()
    installed = _exact_install() + (
        InstalledDistribution(distribution="scoreform", version="0.11.0"),
    )

    with pytest.raises(
        BootstrapInstallationError,
        match="exact suite-qualified version is 0.10.0",
    ):
        verify_installed_composition(
            manifest,
            _snapshot(installed),
        )


def test_wrong_suite_version_fails() -> None:
    manifest = load_release_compatibility_manifest()
    installed = tuple(
        InstalledDistribution(
            distribution=item.distribution,
            version=(
                "9.9.9"
                if item.distribution == manifest.suite.distribution
                else item.version
            ),
        )
        for item in _exact_install()
    )

    with pytest.raises(
        BootstrapInstallationError,
        match="paper-data-suite 9.9.9",
    ):
        verify_installed_composition(manifest, _snapshot(installed))


def test_unsupported_python_fails() -> None:
    manifest = load_release_compatibility_manifest()

    with pytest.raises(
        BootstrapInstallationError,
        match="Python 3.15 is not suite-qualified",
    ):
        verify_installed_composition(
            manifest,
            _snapshot(_exact_install(), python_version="3.15.0"),
        )


def test_non_venv_fails() -> None:
    manifest = load_release_compatibility_manifest()
    snapshot = EnvironmentSnapshot(
        path=str(Path("not-a-venv")),
        exists=True,
        is_virtual_environment=False,
        python_version="3.11.9",
        marker=None,
    )

    with pytest.raises(
        BootstrapInstallationError,
        match="validated virtual environment",
    ):
        verify_installed_composition(manifest, snapshot)

def test_editable_exact_distribution_fails_final_verification() -> None:
    manifest = load_release_compatibility_manifest()
    installed = tuple(
        InstalledDistribution(
            distribution=item.distribution,
            version=item.version,
            editable=item.distribution == manifest.suite.distribution,
        )
        for item in _exact_install()
    )

    with pytest.raises(
        BootstrapInstallationError,
        match="installed editable or source-linked",
    ):
        verify_installed_composition(manifest, _snapshot(installed))


def _write_import_layout(
    root: Path,
    *,
    optional_component_ids: tuple[str, ...] = (),
) -> None:
    manifest = load_release_compatibility_manifest()
    site_packages = root / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    (site_packages / "paper_data_suite").mkdir(exist_ok=True)
    selected = set(optional_component_ids)
    for component in manifest.components:
        if component.required or component.component_id in selected:
            (
                site_packages
                / Path(*component.import_name.split("."))
            ).mkdir(parents=True, exist_ok=True)


def test_installed_import_layout_requires_target_local_packages(
    tmp_path: Path,
) -> None:
    manifest = load_release_compatibility_manifest()
    target = tmp_path / "env"
    _write_import_layout(target)
    snapshot = EnvironmentSnapshot(
        path=str(target),
        exists=True,
        is_virtual_environment=True,
        python_version="3.11.9",
        marker=None,
        installed_distributions=_exact_install(),
    )

    verify_installed_import_layout(manifest, snapshot)


def test_installed_import_layout_rejects_missing_import_root(
    tmp_path: Path,
) -> None:
    manifest = load_release_compatibility_manifest()
    target = tmp_path / "env"
    site_packages = target / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "paper_data_suite").mkdir()
    snapshot = EnvironmentSnapshot(
        path=str(target),
        exists=True,
        is_virtual_environment=True,
        python_version="3.11.9",
        marker=None,
        installed_distributions=_exact_install(),
    )

    with pytest.raises(
        BootstrapInstallationError,
        match="installed import root for pds-core is missing",
    ):
        verify_installed_import_layout(manifest, snapshot)


def test_installed_import_layout_rejects_symlink_outside_target(
    tmp_path: Path,
) -> None:
    manifest = load_release_compatibility_manifest()
    target = tmp_path / "env"
    _write_import_layout(target)
    site_packages = target / "Lib" / "site-packages"
    core_path = site_packages / "pds_core"
    core_path.rmdir()
    outside = tmp_path / "outside-core"
    outside.mkdir()
    try:
        core_path.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable")
    snapshot = EnvironmentSnapshot(
        path=str(target),
        exists=True,
        is_virtual_environment=True,
        python_version="3.11.9",
        marker=None,
        installed_distributions=_exact_install(),
    )

    with pytest.raises(
        BootstrapInstallationError,
        match="resolves outside target site-packages",
    ):
        verify_installed_import_layout(manifest, snapshot)
