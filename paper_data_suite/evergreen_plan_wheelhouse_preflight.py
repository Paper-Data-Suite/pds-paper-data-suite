"""Issue #49 Slice 66: bind a reviewed PDS plan to a signed closed wheelhouse.

This audit never downloads, installs, executes, selects, or authorizes software.
A witnessed baseline is only a transient observation. Before an eventual apply,
its independent witness and protected installed-state must be rechecked under
an installation transaction, with explicit teacher approval and recovery.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    TrustedKeyring,
    verify_module_document,
    verify_registry_document,
)
from paper_data_suite.evergreen_composition_review_plan import (
    CompositionReviewPlanError,
    plan_authenticated_composition_review,
)
from paper_data_suite.evergreen_dependency_lock import (
    DependencyLockError,
    VerifiedLockedWheelhouse,
    verify_signed_locked_wheelhouse,
)
from paper_data_suite.evergreen_release_artifacts import (
    ReleaseArtifactError,
    VerifiedReleaseWheel,
    verify_signed_release_wheel,
)
from paper_data_suite.evergreen_wheelhouse import InspectedWheel
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)

_REPARSE: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_MAX_MODULES: Final = 32


class PlanWheelhousePreflightError(ValueError):
    """Signed plan and physical wheelhouse cannot be reconciled."""


@dataclass(frozen=True, slots=True)
class PlanWheelhousePreflight:
    """Transient read-only acquisition proof, never a staged/active receipt."""

    baseline_transaction_id: str
    baseline_witness_revision: int
    registry_payload_sha256: str
    signed_lock_payload_sha256: str
    signed_lock_revision: int
    python_minor: str
    platform_tag: str
    pds_wheels: tuple[VerifiedReleaseWheel, ...]
    external_wheels: tuple[tuple[str, str, str], ...]
    status: str = "SIGNED_CLOSED_WHEELHOUSE_OBSERVED_NOT_INSTALLED"
    authority: str = "NO_DOWNLOAD_INSTALL_STAGE_ACTIVATION_RECEIPT_OR_LAUNCH_AUTHORITY"


def _ordinary_wheel(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise PlanWheelhousePreflightError(
            "wheel missing from signed wheelhouse"
        ) from error
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or (getattr(info, "st_file_attributes", 0) & _REPARSE)
    ):
        raise PlanWheelhousePreflightError("nonregular or reparse wheel refused")


def _inspect(
    wheelhouse: Path,
    *,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    now: datetime,
    snapshot: CatalogSnapshot,
    selected: dict[str, tuple[str, str]],
    python_minor: str,
    platform_tag: str,
) -> tuple[
    VerifiedLockedWheelhouse,
    tuple[VerifiedReleaseWheel, ...],
    tuple[tuple[str, str, str], ...],
]:
    """Reverify every source, including external transitive wheels, once."""
    registry = verify_registry_document(
        registry_envelope, trust=trust, now=now, checkpoint=snapshot.registry.checkpoint
    )
    if registry != snapshot.registry:
        raise PlanWheelhousePreflightError("registry differs from pinned signed cache")
    complete = verify_signed_locked_wheelhouse(
        wheelhouse,
        lock_envelope=lock_envelope,
        registry_envelope=registry_envelope,
        trust=trust,
        now=now,
        registry_checkpoint=snapshot.registry.checkpoint,
    )
    if (
        complete.lock.registry_payload_sha256 != registry.payload_sha256
        or complete.lock.python_minor != python_minor
        or complete.lock.platform != platform_tag
    ):
        raise PlanWheelhousePreflightError("signed lock differs from planned runtime")
    if set(complete.lock.roots) != set(selected):
        raise PlanWheelhousePreflightError("signed roots differ from complete plan")
    actual: dict[str, InspectedWheel] = {
        str(canonicalize_name(wheel.distribution)): wheel
        for wheel in complete.inspection.wheels
    }
    if len(actual) != len(complete.inspection.wheels):
        raise PlanWheelhousePreflightError("duplicate normalized wheel distribution")
    registered: dict[str, str] = {
        str(canonicalize_name(module.distribution)): module.component_id
        for module in registry.claims.modules
    }
    if len(registered) != len(registry.claims.modules):
        raise PlanWheelhousePreflightError("registered distributions collide")
    if {name for name in actual if name in registered} != set(selected):
        raise PlanWheelhousePreflightError("missing or extra registered PDS wheel")
    # An unregistered pds-* package must not sneak into the root-authorized lock.
    if any(str(name).startswith("pds-") and name not in registered for name in actual):
        raise PlanWheelhousePreflightError("unknown PDS-named transitive wheel")
    cached = {doc.claims.component_id: doc for doc in snapshot.modules}
    if len(cached) != len(snapshot.modules):
        raise PlanWheelhousePreflightError("duplicate cached publisher")
    if set(module_envelopes) != {
        registered[name] for name in actual if name in registered
    }:
        raise PlanWheelhousePreflightError("missing or extraneous signed publisher")
    verified: list[VerifiedReleaseWheel] = []
    for distribution in sorted(selected):
        component = registered.get(distribution)
        if component is None:
            raise PlanWheelhousePreflightError("planned distribution unregistered")
        cached_doc = cached.get(component)
        if cached_doc is None:
            raise PlanWheelhousePreflightError("planned publisher absent from cache")
        publication = verify_module_document(
            module_envelopes[component],
            registry=registry,
            trust=trust,
            now=now,
            checkpoint=cached_doc.checkpoint,
        )
        if publication != cached_doc:
            raise PlanWheelhousePreflightError("publisher differs from signed cache")
        version, sha256 = selected[distribution]
        locked_wheel = actual[distribution]
        if locked_wheel.version != version or locked_wheel.sha256 != sha256:
            raise PlanWheelhousePreflightError("planned wheel differs from signed lock")
        path = wheelhouse / locked_wheel.filename
        _ordinary_wheel(path)
        signed = verify_signed_release_wheel(
            path,
            registry_envelope=registry_envelope,
            module_envelope=module_envelopes[component],
            trust=trust,
            now=now,
            version=version,
        )
        if (
            signed.component_id != component
            or canonicalize_name(signed.distribution) != distribution
            or signed.version != version
            or signed.sha256 != sha256
            or signed.filename != locked_wheel.filename
            or signed.registry_payload_sha256 != registry.payload_sha256
            or signed.publisher_payload_sha256 != publication.payload_sha256
        ):
            raise PlanWheelhousePreflightError("publisher-approved wheel differs")
        verified.append(signed)
    external = tuple(
        sorted(
            (wheel.distribution, wheel.version, wheel.sha256)
            for name, wheel in actual.items()
            if name not in registered
        )
    )
    return complete, tuple(verified), external


def inspect_plan_bound_wheelhouse(
    snapshot: CatalogSnapshot,
    witnessed: WitnessSelectedStageObservation,
    wheelhouse: Path,
    *,
    requested_targets: dict[str, str | None],
    python_minor: str,
    platform_tag: str,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    now: datetime,
) -> PlanWheelhousePreflight:
    """Match a freshly recomputed exact plan to a complete signed wheelhouse.

    This call deliberately does NOT accept a caller-authored plan as authority.
    The witness observation must originate from the independent Slice-62
    verification path and MUST be reauthenticated during eventual apply.
    """
    if (
        not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(witnessed, WitnessSelectedStageObservation)
        or not isinstance(wheelhouse, Path)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or type(registry_envelope) is not bytes
        or type(lock_envelope) is not bytes
        or type(module_envelopes) is not dict
        or not 1 <= len(module_envelopes) <= _MAX_MODULES
        or any(
            type(k) is not str or type(v) is not bytes
            for k, v in module_envelopes.items()
        )
    ):
        raise PlanWheelhousePreflightError("invalid explicit signed wheelhouse inputs")
    try:
        review = plan_authenticated_composition_review(
            snapshot,
            witnessed,
            requested_targets=requested_targets,
            python_minor=python_minor,
            platform_tag=platform_tag,
        )
        selected: dict[str, tuple[str, str]] = {}
        for row in review.modules:
            if row.to_version is None:
                continue
            if row.to_wheel_sha256 is None:
                raise PlanWheelhousePreflightError(
                    "planned release is missing signed digest"
                )
            selected[str(canonicalize_name(row.distribution))] = (
                row.to_version,
                row.to_wheel_sha256,
            )
        if not 1 <= len(selected) <= _MAX_MODULES:
            raise PlanWheelhousePreflightError("no selected signed PDS wheels")
        first = _inspect(
            wheelhouse,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            module_envelopes=module_envelopes,
            trust=trust,
            now=now,
            snapshot=snapshot,
            selected=selected,
            python_minor=python_minor,
            platform_tag=platform_tag,
        )
        second = _inspect(
            wheelhouse,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            module_envelopes=module_envelopes,
            trust=trust,
            now=now,
            snapshot=snapshot,
            selected=selected,
            python_minor=python_minor,
            platform_tag=platform_tag,
        )
        if first != second:
            raise PlanWheelhousePreflightError("signed wheelhouse changed during audit")
        signed, publishers, external = second
        return PlanWheelhousePreflight(
            review.baseline_transaction_id,
            review.baseline_witness_revision,
            review.registry_payload_sha256,
            signed.lock.payload_sha256,
            signed.lock.revision,
            review.python_minor,
            review.platform_tag,
            publishers,
            external,
        )
    except (
        CatalogVerificationError,
        CompositionReviewPlanError,
        DependencyLockError,
        ReleaseArtifactError,
        OSError,
    ) as error:
        raise PlanWheelhousePreflightError(
            "authenticated plan, signed publisher, or closed "
            "wheelhouse verification refused"
        ) from error


__all__ = (
    "PlanWheelhousePreflight",
    "PlanWheelhousePreflightError",
    "inspect_plan_bound_wheelhouse",
)
