"""Issue #49: delegated-publisher and real-pip installed-file preflight.

This is read-only evidence about one isolated staged installation. It does not
run candidate code, authenticate interpreter/native executable origin, inspect
an update journal, confirm historical active state or grant launch authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    parse_unverified_prepared_record,
)
from paper_data_suite.evergreen_pip_layout_audit import (
    PipLayoutError,
    audit_staged_pip_layout,
)
from paper_data_suite.evergreen_publisher_composition import (
    PublisherCompositionError,
    VerifiedPublisherComposition,
    verify_publisher_bound_composition,
)
from paper_data_suite.evergreen_staged_runtime import (
    StagedRuntimeError,
    inspect_staged_virtualenv,
)

_MAX_ENVELOPES: Final = 32
_MAX_ENVELOPE_BYTES: Final = 128 * 1024


class PublisherPipPreflightError(ValueError):
    """An exact installed candidate lacks publisher and pip-file evidence."""


@dataclass(frozen=True, slots=True)
class ObservedPublisherPipCandidate:
    """Ephemeral verified file inventory; NEVER a launch/activation receipt."""

    transaction_id: str
    stage_root: Path
    wheelhouse: Path
    registry_payload_sha256: str
    lock_payload_sha256: str
    pip_inventory_sha256: str
    publisher_digests: tuple[tuple[str, str], ...]
    root_console_targets: tuple[tuple[str, str, str], ...]
    external_distributions: tuple[str, ...]
    installed_launcher_paths: tuple[str, ...]


def _root_consoles(
    publisher: VerifiedPublisherComposition,
    *,
    prepared_record: bytes,
    actual: tuple[tuple[str, str, str], ...],
) -> tuple[tuple[str, str, str], ...]:
    try:
        roots = parse_unverified_prepared_record(prepared_record).roots
    except PreparedRecordError as error:
        raise PublisherPipPreflightError("invalid prepared candidate roots") from error
    by_name = {
        canonicalize_name(module.distribution): module
        for module in publisher.authorized_modules
    }
    expected: set[tuple[str, str, str]] = set()
    for root in roots:
        module = by_name.get(canonicalize_name(root))
        if module is None:
            raise PublisherPipPreflightError("selected root lacks publisher identity")
        expected.add(
            (
                canonicalize_name(module.distribution),
                module.console_script,
                module.console_target,
            )
        )
    normalized = {
        (canonicalize_name(owner), name, target) for owner, name, target in actual
    }
    if not expected or len(normalized) != len(actual) or normalized != expected:
        raise PublisherPipPreflightError("root launcher disagrees with signed release")
    return tuple(sorted(expected))


def audit_publisher_bound_pip_candidate(
    stage_root: Path,
    wheelhouse: Path,
    *,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    now: datetime,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> ObservedPublisherPipCandidate:
    """Cross-check signed PDS publishers against an entire real-pip file stage.

    Every owned console must be present in installed RECORD, including its
    exact hash/size. All registered PDS wheels require delegated signatures.
    This observation never launches a module and cannot authorize a switch.
    """
    if (
        not isinstance(stage_root, Path)
        or not isinstance(wheelhouse, Path)
        or type(module_envelopes) is not dict
        or not 1 <= len(module_envelopes) <= _MAX_ENVELOPES
        or any(
            type(component) is not str
            or type(envelope) is not bytes
            or not 1 <= len(envelope) <= _MAX_ENVELOPE_BYTES
            for component, envelope in module_envelopes.items()
        )
    ):
        raise PublisherPipPreflightError("invalid publisher-pip preflight inputs")

    def authenticate_publishers() -> VerifiedPublisherComposition:
        try:
            return verify_publisher_bound_composition(
                wheelhouse,
                prepared_record=prepared_record,
                registry_envelope=registry_envelope,
                lock_envelope=lock_envelope,
                module_envelopes=module_envelopes,
                trust=trust,
                now=now,
                registry_checkpoint=registry_checkpoint,
                lock_checkpoint=lock_checkpoint,
            )
        except (PublisherCompositionError, OSError, ValueError) as error:
            raise PublisherPipPreflightError(
                "candidate publisher evidence is invalid"
            ) from error

    before = authenticate_publishers()
    try:
        pip_stage = audit_staged_pip_layout(
            stage_root,
            wheelhouse,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            trust=trust,
            now=now,
            checkpoint=lock_checkpoint,
            layout=layout,
            require_launcher_records=True,
        )
        runtime = inspect_staged_virtualenv(
            stage_root,
            wheelhouse,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            trust=trust,
            now=now,
            checkpoint=lock_checkpoint,
            layout=layout,
        )
    except (PipLayoutError, StagedRuntimeError, ValueError, OSError) as error:
        raise PublisherPipPreflightError(
            "candidate pip installation audit failed"
        ) from error
    if (
        pip_stage.transaction_id != before.transaction_id
        or runtime.transaction_id != before.transaction_id
        or pip_stage.site_packages != runtime.site_packages
        or runtime.stage_root != stage_root
    ):
        raise PublisherPipPreflightError("candidate installation identity mismatch")
    selected = {
        canonicalize_name(name)
        for name in parse_unverified_prepared_record(prepared_record).roots
    }
    roots = _root_consoles(
        before,
        prepared_record=prepared_record,
        actual=tuple(
            (launcher.owner, launcher.name, launcher.target)
            for launcher in runtime.console_launchers
            if canonicalize_name(launcher.owner) in selected
        ),
    )
    expected_scripts = {
        launcher.path.relative_to(runtime.stage_root).as_posix()
        for launcher in runtime.console_launchers
    }
    # pip RECORD script path is relative to site-packages, not the venv root.
    actual_scripts = {
        (runtime.site_packages / item.relative_path).resolve()
        for item in pip_stage.launcher_records
    }
    expected_paths = {entry.path.resolve() for entry in runtime.console_launchers}
    if actual_scripts != expected_paths or len(expected_scripts) != len(actual_scripts):
        raise PublisherPipPreflightError("owned console RECORD inventory differs")
    after = authenticate_publishers()
    if before != after:
        raise PublisherPipPreflightError("publisher evidence changed during pip audit")
    return ObservedPublisherPipCandidate(
        transaction_id=before.transaction_id,
        stage_root=runtime.stage_root,
        wheelhouse=wheelhouse,
        registry_payload_sha256=before.registry_payload_sha256,
        lock_payload_sha256=before.lock_payload_sha256,
        pip_inventory_sha256=pip_stage.inventory_sha256,
        publisher_digests=tuple(
            sorted(
                (module.component_id, module.publisher_payload_sha256)
                for module in after.authorized_modules
            )
        ),
        root_console_targets=roots,
        external_distributions=before.external_distributions,
        installed_launcher_paths=tuple(sorted(expected_scripts)),
    )


__all__ = (
    "ObservedPublisherPipCandidate",
    "PublisherPipPreflightError",
    "audit_publisher_bound_pip_candidate",
)
