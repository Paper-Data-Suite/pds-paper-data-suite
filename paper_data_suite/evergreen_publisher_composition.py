"""Issue #49: independently authenticate every PDS wheel in a prepared lock.

A root-signed dependency lock is necessary but not a substitute for the
publisher-delegated release authorization of each PDS module. No execution,
installation, active receipt, network access, or launch rights are provided.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    RevisionCheckpoint,
    TrustedKeyring,
    verify_registry_document,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    verify_prepared_record_against_wheelhouse,
)
from paper_data_suite.evergreen_release_artifacts import (
    ReleaseArtifactError,
    VerifiedReleaseWheel,
    verify_signed_release_wheel,
)

_MAX_MODULES: Final = 32
_REPARSE: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class PublisherCompositionError(ValueError):
    """The closed composition lacks authentic delegated PDS release evidence."""


@dataclass(frozen=True, slots=True)
class VerifiedPublisherComposition:
    """Wheelhouse-only authorization observation; NOT an installed receipt."""

    transaction_id: str
    registry_payload_sha256: str
    lock_payload_sha256: str
    authorized_modules: tuple[VerifiedReleaseWheel, ...]
    external_distributions: tuple[str, ...]


def _ordinary_wheel(path: Path) -> None:
    """Supplement exact-hash inspection with explicit Windows reparse checks."""
    try:
        info = path.lstat()
    except OSError as error:
        raise PublisherCompositionError("publisher wheel unavailable") from error
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & _REPARSE)
    ):
        raise PublisherCompositionError("publisher wheel is not a regular file")


def verify_publisher_bound_composition(
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
) -> VerifiedPublisherComposition:
    """Require publisher signatures for all registered distributions in lock.

    Module envelopes are indexed by independently root-registered component ID,
    not a wheel-supplied name. A signer-supplied hash, the root lock alone, or
    a user-editable prepared record never substitutes for signed release facts.
    Unregistered transitive dependencies remain root-lock authorized only;
    ALL selected roots must be registered PDS components.
    """
    if (
        not isinstance(wheelhouse, Path)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or type(module_envelopes) is not dict
        or len(module_envelopes) > _MAX_MODULES
        or any(
            type(key) is not str or type(value) is not bytes
            for key, value in module_envelopes.items()
        )
    ):
        raise PublisherCompositionError("invalid publisher verification inputs")
    try:
        record = verify_prepared_record_against_wheelhouse(
            prepared_record,
            wheelhouse,
            lock_envelope=lock_envelope,
            registry_envelope=registry_envelope,
            trust=trust,
            now=now,
            checkpoint=lock_checkpoint,
        )
        registry = verify_registry_document(
            registry_envelope,
            trust=trust,
            now=now,
            checkpoint=registry_checkpoint,
        )
    except (PreparedRecordError, CatalogVerificationError, ValueError) as error:
        raise PublisherCompositionError(
            "publisher composition registry or dependency lock invalid"
        ) from error
    if record.registry_payload_sha256 != registry.payload_sha256:
        raise PublisherCompositionError("prepared and signed registry differ")
    registered = {
        canonicalize_name(module.distribution): module
        for module in registry.claims.modules
    }
    selected = {canonicalize_name(wheel.distribution): wheel for wheel in record.wheels}
    if not set(record.roots) <= registered.keys():
        raise PublisherCompositionError("unregistered PDS application root")
    # Require all registered PDS packages, including dependency-only modules.
    required = {
        registered[name].component_id for name in selected if name in registered
    }
    if not required or set(module_envelopes) != required:
        raise PublisherCompositionError(
            "missing or unexpected PDS publisher release envelope"
        )
    approved: list[VerifiedReleaseWheel] = []
    for name in sorted(selected):
        if name not in registered:
            continue
        wheel = selected[name]
        module = registered[name]
        _ordinary_wheel(wheelhouse / wheel.filename)
        try:
            verified = verify_signed_release_wheel(
                wheelhouse / wheel.filename,
                registry_envelope=registry_envelope,
                module_envelope=module_envelopes[module.component_id],
                trust=trust,
                now=now,
                version=wheel.version,
            )
        except (ReleaseArtifactError, ValueError) as error:
            raise PublisherCompositionError(
                "publisher-delegated release identity failed"
            ) from error
        if (
            verified.component_id != module.component_id
            or canonicalize_name(verified.distribution) != name
            or verified.filename != wheel.filename
            or verified.sha256 != wheel.sha256
            or verified.version != wheel.version
            or verified.registry_payload_sha256 != registry.payload_sha256
        ):
            raise PublisherCompositionError("publisher wheel disagrees with lock")
        approved.append(verified)
    return VerifiedPublisherComposition(
        transaction_id=record.transaction_id,
        registry_payload_sha256=registry.payload_sha256,
        lock_payload_sha256=record.lock_payload_sha256,
        authorized_modules=tuple(approved),
        external_distributions=tuple(sorted(set(selected) - set(registered))),
    )


__all__ = (
    "PublisherCompositionError",
    "VerifiedPublisherComposition",
    "verify_publisher_bound_composition",
)
