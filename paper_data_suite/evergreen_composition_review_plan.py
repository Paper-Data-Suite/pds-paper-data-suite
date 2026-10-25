"""Issue #49 Slice 64: deterministic, read-only authenticated composition planning.

The installed baseline is a *transient* Slice-62 witness/byte observation, not
protected active state. Signed release claims are not verified wheel downloads.
A plan cannot authorize download, installation, activation, receipt creation,
or launch. All external wheels require an independently signed full lock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from paper_data_suite.evergreen_catalog_contracts import ReleaseClaim
from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)

_ID: Final = re.compile(r"[a-z][a-z0-9_-]{1,47}\Z")
_MINOR: Final = re.compile(r"3\.(?:1[1-9]|[2-9][0-9])\Z")
_PLATFORM: Final = re.compile(r"[a-z][a-z0-9_.-]{1,95}\Z")
_MAX_MODULES: Final = 32
_MAX_ROUNDS: Final = 64


class CompositionReviewPlanError(ValueError):
    """Requested releases cannot form a supported, inspectable signed plan."""


class PlannedAction(str, Enum):
    ADD = "ADD"
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"
    REMOVE = "REMOVE"
    UNCHANGED = "UNCHANGED"


class ChangeOrigin(str, Enum):
    REQUESTED = "requested"
    DEPENDENCY_CLOSURE = "dependency_closure"
    RETAINED = "retained"


class FeatureDelta(str, Enum):
    GAINED = "GAINED_EXACT_CLAIM"
    LOST = "LOST_EXACT_CLAIM"
    RETAINED = "RETAINED_EXACT_CLAIM"
    UNQUALIFIED = "NO_MATCHING_EXACT_CLAIM"


@dataclass(frozen=True, slots=True)
class PlannedModuleChange:
    component_id: str
    distribution: str
    action: PlannedAction
    origin: ChangeOrigin
    from_version: str | None
    to_version: str | None
    from_wheel_sha256: str | None
    to_wheel_sha256: str | None


@dataclass(frozen=True, slots=True)
class PlannedFeatureImpact:
    feature_id: str
    delta: FeatureDelta
    signed_result: str


@dataclass(frozen=True, slots=True)
class CompositionReviewPlan:
    """Unprivileged plan data; never an installation or execution credential."""

    baseline_transaction_id: str
    baseline_witness_revision: int
    registry_payload_sha256: str
    python_minor: str
    platform_tag: str
    modules: tuple[PlannedModuleChange, ...]
    features: tuple[PlannedFeatureImpact, ...]
    external_requirements: tuple[str, ...]
    status: str = "READ_ONLY_PREVIEW_FULL_SIGNED_LOCK_STILL_REQUIRED"
    authority: str = "NO_DOWNLOAD_INSTALL_ACTIVATION_RECEIPT_OR_LAUNCH_AUTHORITY"


def _version(value: str) -> Version:
    try:
        return Version(value)
    except (InvalidVersion, TypeError) as error:
        raise CompositionReviewPlanError(
            "invalid authenticated release version"
        ) from error


def _releases(
    snapshot: CatalogSnapshot,
) -> dict[str, tuple[ReleaseClaim, ...]]:
    by_registry = {item.component_id: item for item in snapshot.registry.claims.modules}
    if len(by_registry) != len(snapshot.registry.claims.modules):
        raise CompositionReviewPlanError("duplicate registered PDS component")
    docs: dict[str, tuple[ReleaseClaim, ...]] = {}
    for document in snapshot.modules:
        component = document.claims.component_id
        registration = by_registry.get(component)
        if (
            registration is None
            or component in docs
            or document.registry_payload_sha256 != snapshot.registry.payload_sha256
            or document.claims.distribution != registration.distribution
        ):
            raise CompositionReviewPlanError("signed publisher identity inconsistent")
        docs[component] = document.claims.releases
    return docs


def _python_ok(release: ReleaseClaim, minor: str) -> bool:
    try:
        return SpecifierSet(release.requires_python).contains(
            Version(f"{minor}.0"), prereleases=False
        )
    except (InvalidSpecifier, InvalidVersion, TypeError) as error:
        raise CompositionReviewPlanError(
            "invalid release Python requirement"
        ) from error


def _choose(
    releases: tuple[ReleaseClaim, ...],
    constraints: tuple[SpecifierSet, ...],
    minor: str,
    current_version: str | None,
) -> ReleaseClaim | None:
    choices = [
        release
        for release in releases
        if not release.revoked
        and _python_ok(release, minor)
        and all(spec.contains(_version(release.version)) for spec in constraints)
    ]
    if current_version is not None:
        matching = [x for x in choices if x.version == current_version]
        if matching:
            return matching[0]
    return max(choices, key=lambda item: _version(item.version)) if choices else None


def _requirements(
    releases: dict[str, ReleaseClaim],
    distributions: dict[str, str],
    minor: str,
    platform: str,
) -> tuple[dict[str, tuple[SpecifierSet, ...]], tuple[str, ...]]:
    constraints: dict[str, list[SpecifierSet]] = {}
    external: set[str] = set()
    environment: dict[str, str] = {
        key: str(value) for key, value in default_environment().items()
    }
    environment["python_version"] = minor
    environment["python_full_version"] = f"{minor}.0"
    environment["sys_platform"] = (
        "win32"
        if platform.startswith("win_")
        else "linux"
        if platform.startswith("linux_")
        else "darwin"
        if platform.startswith("macosx_")
        else "unknown"
    )
    environment["extra"] = ""
    for release in releases.values():
        for raw in release.requires_dist:
            try:
                requirement = Requirement(raw)
                if requirement.marker is not None and not requirement.marker.evaluate(
                    environment=environment
                ):
                    continue
            except (InvalidRequirement, ValueError, KeyError, TypeError) as error:
                raise CompositionReviewPlanError(
                    "invalid release dependency requirement"
                ) from error
            if requirement.extras or requirement.url is not None:
                raise CompositionReviewPlanError(
                    "extras and direct-URL dependency inputs require separate review"
                )
            name = canonicalize_name(requirement.name)
            component = distributions.get(name)
            if component is None:
                external.add(str(requirement))
            else:
                constraints.setdefault(component, []).append(requirement.specifier)
    return (
        {key: tuple(value) for key, value in constraints.items()},
        tuple(sorted(external)),
    )


def _feature_match(
    document: object,
    selections: dict[str, ReleaseClaim],
    minor: str,
    platform: str,
) -> bool:
    # Only actually covered signed artifacts count; unrelated package changes
    # do not invalidate a narrowly scoped, exact per-feature claim.
    from paper_data_suite.evergreen_catalog_verification import (
        VerifiedIntegrationDocument,
    )

    if not isinstance(document, VerifiedIntegrationDocument):
        raise CompositionReviewPlanError("unsigned integration assertion")
    claim = document.claims
    return (
        claim.result == "passed"
        and minor in claim.python_minors
        and platform in claim.platforms
        and bool(claim.artifacts)
        and all(
            item.component_id in selections
            and selections[item.component_id].sha256 == item.wheel_sha256
            for item in claim.artifacts
        )
    )


def plan_authenticated_composition_review(
    snapshot: CatalogSnapshot,
    observed: WitnessSelectedStageObservation,
    *,
    requested_targets: dict[str, str | None],
    python_minor: str,
    platform_tag: str,
) -> CompositionReviewPlan:
    """Preview explicit version changes and required signed-PDS dependency closure.

    ``requested_targets`` maps registered component IDs to exact signed
    versions, or ``None`` for a deliberate removal. All observed modules are
    retained unless explicitly removed. Compatible dependencies are added or
    upgraded using signed catalog choices, preferring already observed versions.
    Conflicting requested changes and unresolved graphs refuse rather than
    guessing, downgrading trust, or executing a dependency resolver. This does
    NOT establish active state, safe wheel tags, or external dependency closure.
    """
    if (
        not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(observed, WitnessSelectedStageObservation)
        or type(requested_targets) is not dict
        or not 1 <= len(requested_targets) <= _MAX_MODULES
        or not isinstance(python_minor, str)
        or _MINOR.fullmatch(python_minor) is None
        or not isinstance(platform_tag, str)
        or _PLATFORM.fullmatch(platform_tag) is None
        or any(
            type(key) is not str
            or _ID.fullmatch(key) is None
            or (value is not None and (type(value) is not str or not value))
            for key, value in requested_targets.items()
        )
    ):
        raise CompositionReviewPlanError("invalid signed composition plan inputs")
    registrations = {
        item.component_id: item for item in snapshot.registry.claims.modules
    }
    distributions: dict[str, str] = {
        str(canonicalize_name(item.distribution)): item.component_id
        for item in snapshot.registry.claims.modules
    }
    if (
        len(distributions) != len(registrations)
        or not set(requested_targets) <= registrations.keys()
    ):
        raise CompositionReviewPlanError(
            "unregistered target or distribution collision"
        )
    documents = _releases(snapshot)
    before: dict[str, ReleaseClaim] = {}
    previous_hashes: dict[str, str] = {}
    for item in observed.modules:
        registration = registrations.get(item.component_id)
        releases = documents.get(item.component_id, ())
        matched = [
            claim
            for claim in releases
            if claim.version == item.version and claim.sha256 == item.wheel_sha256
        ]
        doc = next(
            (
                entry
                for entry in snapshot.modules
                if entry.claims.component_id == item.component_id
            ),
            None,
        )
        if (
            item.component_id in before
            or registration is None
            or canonicalize_name(registration.distribution)
            != canonicalize_name(item.distribution)
            or doc is None
            or doc.payload_sha256 != item.publisher_payload_sha256
            or len(matched) != 1
        ):
            raise CompositionReviewPlanError(
                "observed baseline does not match signed catalog"
            )
        before[item.component_id] = matched[0]
        previous_hashes[item.component_id] = item.wheel_sha256
    if not before:
        raise CompositionReviewPlanError("empty witness-selected baseline")

    selected = dict(before)
    explicitly_removed: set[str] = set()
    for component, version in sorted(requested_targets.items()):
        if version is None:
            if component not in selected:
                raise CompositionReviewPlanError("cannot remove absent PDS component")
            del selected[component]
            explicitly_removed.add(component)
            continue
        release = next(
            (x for x in documents.get(component, ()) if x.version == version),
            None,
        )
        if release is None or release.revoked or not _python_ok(release, python_minor):
            raise CompositionReviewPlanError(
                "requested target unsigned, revoked or Python-incompatible"
            )
        selected[component] = release

    if not selected:
        raise CompositionReviewPlanError("cannot propose an empty managed composition")
    origins = {key: ChangeOrigin.RETAINED for key in selected}
    origins.update(
        {key: ChangeOrigin.REQUESTED for key in requested_targets if key in selected}
    )
    seen: set[tuple[tuple[str, str], ...]] = set()
    external: tuple[str, ...] = ()
    for _ in range(_MAX_ROUNDS):
        state = tuple(sorted((key, value.version) for key, value in selected.items()))
        if state in seen:
            raise CompositionReviewPlanError("dependency closure did not converge")
        seen.add(state)
        requirements, external = _requirements(
            selected, distributions, python_minor, platform_tag
        )
        changes = False
        for component in sorted(requirements):
            if component in explicitly_removed:
                raise CompositionReviewPlanError(
                    "dependency requires a requested removal"
                )
            specs = requirements[component]
            present = selected.get(component)
            if present is not None and all(
                constraint.contains(_version(present.version)) for constraint in specs
            ):
                continue
            if component in requested_targets:
                raise CompositionReviewPlanError(
                    "explicit target conflicts with PDS dependency"
                )
            replacement = _choose(
                documents.get(component, ()),
                specs,
                python_minor,
                before[component].version if component in before else None,
            )
            if replacement is None:
                raise CompositionReviewPlanError(
                    "no approved release satisfies dependency closure"
                )
            selected[component] = replacement
            origins[component] = ChangeOrigin.DEPENDENCY_CLOSURE
            changes = True
        if not changes:
            break
    else:
        raise CompositionReviewPlanError("dependency closure exceeded bounded rounds")
    # Check the final graph anew. An earlier dependency may have become stale
    # after a later component changed its own declared requirements.
    requirements, external = _requirements(
        selected, distributions, python_minor, platform_tag
    )
    for component, specs in requirements.items():
        if component not in selected or not all(
            spec.contains(_version(selected[component].version)) for spec in specs
        ):
            raise CompositionReviewPlanError("unresolved signed dependency graph")
    if any(
        not _python_ok(item, python_minor) or item.revoked for item in selected.values()
    ):
        raise CompositionReviewPlanError(
            "final plan contains revoked or incompatible release"
        )
    changes_rows: list[PlannedModuleChange] = []
    for component in sorted(before.keys() | selected.keys()):
        prior, upcoming = before.get(component), selected.get(component)
        if prior is None:
            action = PlannedAction.ADD
        elif upcoming is None:
            action = PlannedAction.REMOVE
        elif prior.version == upcoming.version and prior.sha256 == upcoming.sha256:
            action = PlannedAction.UNCHANGED
        elif _version(upcoming.version) > _version(prior.version):
            action = PlannedAction.UPGRADE
        else:
            action = PlannedAction.DOWNGRADE
        changes_rows.append(
            PlannedModuleChange(
                component,
                registrations[component].distribution,
                action,
                ChangeOrigin.REQUESTED
                if component in requested_targets
                else origins.get(component, ChangeOrigin.RETAINED),
                prior.version if prior else None,
                upcoming.version if upcoming else None,
                previous_hashes.get(component),
                upcoming.sha256 if upcoming else None,
            )
        )
    impacts: list[PlannedFeatureImpact] = []
    for attestation in sorted(snapshot.integrations, key=lambda x: x.claims.feature_id):
        before_exact = _feature_match(attestation, before, python_minor, platform_tag)
        after_exact = _feature_match(attestation, selected, python_minor, platform_tag)
        delta = (
            FeatureDelta.RETAINED
            if before_exact and after_exact
            else FeatureDelta.LOST
            if before_exact
            else FeatureDelta.GAINED
            if after_exact
            else FeatureDelta.UNQUALIFIED
        )
        impacts.append(
            PlannedFeatureImpact(
                attestation.claims.feature_id, delta, attestation.claims.result
            )
        )
    return CompositionReviewPlan(
        observed.transaction_id,
        observed.witness_revision,
        snapshot.registry.payload_sha256,
        python_minor,
        platform_tag,
        tuple(changes_rows),
        tuple(impacts),
        external,
    )


__all__ = (
    "ChangeOrigin",
    "CompositionReviewPlan",
    "CompositionReviewPlanError",
    "FeatureDelta",
    "PlannedAction",
    "PlannedFeatureImpact",
    "PlannedModuleChange",
    "plan_authenticated_composition_review",
)
