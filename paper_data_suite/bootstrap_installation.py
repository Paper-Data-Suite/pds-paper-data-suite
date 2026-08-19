"""Installed-composition verification for verified suite bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paper_data_suite.bootstrap import (
    BootstrapPlanningError,
    EnvironmentSnapshot,
    normalize_distribution_name,
    python_minor_from_version,
)
from paper_data_suite.compatibility import ReleaseCompatibilityManifest


class BootstrapInstallationError(RuntimeError):
    """Raised when an applied target disagrees with the exact suite composition."""


@dataclass(frozen=True, slots=True)
class InstalledPdsPackage:
    """One exact PDS-owned distribution verified in a target environment."""

    component_id: str
    distribution: str
    version: str


def _selected_optional_ids(
    manifest: ReleaseCompatibilityManifest,
    selected_component_ids: tuple[str, ...],
) -> frozenset[str]:
    if len(selected_component_ids) != len(set(selected_component_ids)):
        raise BootstrapInstallationError(
            "selected optional component IDs must not contain duplicates"
        )
    optional_ids = frozenset(
        item.component_id for item in manifest.components if not item.required
    )
    for component_id in selected_component_ids:
        if component_id not in optional_ids:
            raise BootstrapInstallationError(
                f"unsupported optional component ID: {component_id!r}"
            )
    return frozenset(selected_component_ids)


def verify_installed_composition(
    manifest: ReleaseCompatibilityManifest,
    snapshot: EnvironmentSnapshot,
    *,
    selected_component_ids: tuple[str, ...] = (),
) -> tuple[InstalledPdsPackage, ...]:
    """Verify exact installed PDS identities without importing target packages."""
    if not snapshot.exists or not snapshot.is_virtual_environment:
        raise BootstrapInstallationError(
            "target must be an existing validated virtual environment"
        )

    try:
        python_minor = python_minor_from_version(snapshot.python_version)
    except BootstrapPlanningError as error:
        raise BootstrapInstallationError(str(error)) from error
    if python_minor not in manifest.python.tested_minors:
        raise BootstrapInstallationError(
            f"target Python {python_minor} is not suite-qualified"
        )

    selected = _selected_optional_ids(manifest, selected_component_ids)
    installed: dict[str, tuple[str, str]] = {}
    for item in snapshot.installed_distributions:
        normalized = normalize_distribution_name(item.distribution)
        if normalized in installed:
            raise BootstrapInstallationError(
                f"duplicate installed distribution identity: {item.distribution!r}"
            )
        installed[normalized] = (item.distribution, item.version)

    expected: list[tuple[str, str, str, bool]] = [
        (
            "suite",
            manifest.suite.distribution,
            manifest.suite.version,
            True,
        )
    ]
    for component in manifest.components:
        expected.append(
            (
                component.component_id,
                component.distribution,
                component.version,
                component.required or component.component_id in selected,
            )
        )

    verified: list[InstalledPdsPackage] = []
    for component_id, distribution, version, required_now in expected:
        observed = installed.get(normalize_distribution_name(distribution))
        if observed is None:
            if required_now:
                raise BootstrapInstallationError(
                    "required installed distribution is missing: "
                    f"{distribution} {version}"
                )
            continue

        observed_item = next(
            item
            for item in snapshot.installed_distributions
            if normalize_distribution_name(item.distribution)
            == normalize_distribution_name(distribution)
        )
        if observed_item.editable:
            raise BootstrapInstallationError(
                f"{distribution} {observed_item.version} is installed editable or "
                "source-linked; exact released-wheel installation is required"
            )

        _, installed_version = observed
        if installed_version != version:
            raise BootstrapInstallationError(
                f"{distribution} {installed_version} is installed but exact "
                f"suite-qualified version is {version}"
            )
        verified.append(
            InstalledPdsPackage(
                component_id=component_id,
                distribution=distribution,
                version=version,
            )
        )

    return tuple(verified)


def verify_installed_import_layout(
    manifest: ReleaseCompatibilityManifest,
    snapshot: EnvironmentSnapshot,
    *,
    selected_component_ids: tuple[str, ...] = (),
) -> None:
    """Prove installed PDS import roots resolve inside target site-packages."""
    if not snapshot.exists or not snapshot.is_virtual_environment:
        raise BootstrapInstallationError(
            "target must be an existing validated virtual environment"
        )

    selected = _selected_optional_ids(manifest, selected_component_ids)
    site_packages = Path(snapshot.path).resolve() / "Lib" / "site-packages"
    if not site_packages.is_dir():
        raise BootstrapInstallationError(
            f"target site-packages is missing: {site_packages}"
        )
    site_root = site_packages.resolve()

    known_imports = {
        normalize_distribution_name(manifest.suite.distribution): "paper_data_suite"
    }
    required_now = {normalize_distribution_name(manifest.suite.distribution)}
    for component in manifest.components:
        normalized = normalize_distribution_name(component.distribution)
        known_imports[normalized] = component.import_name
        if component.required or component.component_id in selected:
            required_now.add(normalized)

    installed_names = {
        normalize_distribution_name(item.distribution)
        for item in snapshot.installed_distributions
    }
    for distribution in sorted(required_now | (installed_names & known_imports.keys())):
        import_name = known_imports[distribution]
        relative = Path(*import_name.split("."))
        package_candidate = site_root / relative
        module_candidate = (site_root / relative).with_suffix(".py")
        candidates = tuple(
            candidate
            for candidate in (package_candidate, module_candidate)
            if candidate.exists()
        )
        if len(candidates) != 1:
            raise BootstrapInstallationError(
                f"installed import root for {distribution} is missing or ambiguous: "
                f"{import_name}"
            )
        resolved = candidates[0].resolve()
        try:
            resolved.relative_to(site_root)
        except ValueError as error:
            raise BootstrapInstallationError(
                f"installed import root for {distribution} resolves outside "
                "target site-packages"
            ) from error
