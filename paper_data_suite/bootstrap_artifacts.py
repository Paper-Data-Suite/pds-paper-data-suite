"""Artifact planning and verification for verified suite bootstrap."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from paper_data_suite.artifact_verification import (
    ArtifactVerificationError,
    sha256_file,
    verify_component_wheel,
)
from paper_data_suite.bootstrap import (
    BootstrapPlan,
    normalize_distribution_name,
)
from paper_data_suite.compatibility import (
    ComponentCompatibility,
    ReleaseCompatibilityManifest,
)


class BootstrapArtifactError(RuntimeError):
    """Raised when bootstrap artifacts cannot be prepared safely."""


@dataclass(frozen=True, slots=True)
class ArtifactRequirement:
    """One exact component wheel required by the current bootstrap plan."""

    component_id: str
    display_name: str
    distribution: str
    version: str
    repository: str
    tag: str
    wheel: str
    sha256: str
    url: str


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    """One exact component wheel authenticated for later installation."""

    component_id: str
    distribution: str
    version: str
    path: str
    sha256: str


def component_release_url(component: ComponentCompatibility) -> str:
    """Build the one official GitHub Release URL declared by the manifest."""
    return (
        f"https://github.com/{component.repository}"
        f"/releases/download/{component.release.tag}/{component.release.wheel}"
    )


def required_component_artifacts(
    manifest: ReleaseCompatibilityManifest,
    plan: BootstrapPlan,
) -> tuple[ArtifactRequirement, ...]:
    """Return exact component wheels needed by this safe, actionable plan."""
    if not plan.can_apply:
        raise BootstrapArtifactError(
            "cannot prepare release artifacts for a blocked bootstrap plan"
        )

    components = {
        item.component_id: item for item in manifest.components
    }
    requirements: list[ArtifactRequirement] = []
    for package_plan in plan.packages:
        if package_plan.action != "install_missing":
            continue
        if package_plan.component_id == "suite":
            continue

        component = components.get(package_plan.component_id)
        if component is None:
            raise BootstrapArtifactError(
                "bootstrap plan references an unknown component: "
                f"{package_plan.component_id!r}"
            )
        if (
            package_plan.distribution != component.distribution
            or package_plan.desired_version != component.version
        ):
            raise BootstrapArtifactError(
                "bootstrap plan component identity disagrees with manifest: "
                f"{package_plan.component_id!r}"
            )

        requirements.append(
            ArtifactRequirement(
                component_id=component.component_id,
                display_name=component.display_name,
                distribution=component.distribution,
                version=component.version,
                repository=component.repository,
                tag=component.release.tag,
                wheel=component.release.wheel,
                sha256=component.release.sha256,
                url=component_release_url(component),
            )
        )
    return tuple(requirements)


def verify_required_artifacts(
    manifest: ReleaseCompatibilityManifest,
    plan: BootstrapPlan,
    artifact_directory: Path,
) -> tuple[VerifiedArtifact, ...]:
    """Authenticate only component wheels required by the current plan."""
    directory = artifact_directory.expanduser().resolve()
    if not directory.is_dir():
        raise BootstrapArtifactError(
            f"artifact directory does not exist: {directory}"
        )

    components = {
        item.component_id: item for item in manifest.components
    }
    verified: list[VerifiedArtifact] = []
    for requirement in required_component_artifacts(manifest, plan):
        component = components[requirement.component_id]
        path = directory / requirement.wheel
        try:
            verify_component_wheel(component, path)
            digest = sha256_file(path)
        except ArtifactVerificationError as error:
            raise BootstrapArtifactError(
                f"{requirement.component_id} artifact verification failed: {error}"
            ) from error

        verified.append(
            VerifiedArtifact(
                component_id=requirement.component_id,
                distribution=requirement.distribution,
                version=requirement.version,
                path=str(path.resolve()),
                sha256=digest,
            )
        )
    return tuple(verified)


def pds_constraints_text(
    manifest: ReleaseCompatibilityManifest,
) -> str:
    """Return deterministic exact-version constraints for PDS-owned packages."""
    versions = {
        normalize_distribution_name(manifest.suite.distribution): (
            manifest.suite.distribution,
            manifest.suite.version,
        )
    }
    for component in manifest.components:
        normalized = normalize_distribution_name(component.distribution)
        if normalized in versions:
            raise BootstrapArtifactError(
                "duplicate normalized PDS distribution in compatibility manifest: "
                f"{component.distribution!r}"
            )
        versions[normalized] = (
            component.distribution,
            component.version,
        )

    return "".join(
        f"{distribution}=={version}\n"
        for _, (distribution, version) in sorted(versions.items())
    )


def write_pds_constraints(
    path: Path,
    manifest: ReleaseCompatibilityManifest,
) -> str:
    """Atomically write transient PDS-only exact-version constraints."""
    target = path.expanduser().resolve()
    if not target.parent.is_dir():
        raise BootstrapArtifactError(
            f"constraints parent directory does not exist: {target.parent}"
        )

    text = pds_constraints_text(manifest)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(text)
            temporary_path = Path(temporary.name)
        if temporary_path is None:
            raise BootstrapArtifactError(
                f"could not create transient constraints: {target}"
            )
        temporary_path.replace(target)
    except OSError as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise BootstrapArtifactError(
            f"could not write transient constraints: {target}"
        ) from error
    return text
