"""Issue #49 Slice 60: correlate signed catalog claims with fresh staged bytes.

This is an explicitly invoked, read-only candidate audit. Neither signed
release claims nor a successful pip/native audit prove that the candidate is
ACTIVE, protected from replacement, or safe to launch. No CLI activation path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    RevisionCheckpoint,
    TrustedKeyring,
    verify_module_document,
    verify_registry_document,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    parse_unverified_prepared_record,
)
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    VerifiedNativeEvidence,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    ObservedPublisherPipCandidate,
    PublisherPipPreflightError,
    audit_publisher_bound_pip_candidate,
)


class CatalogStageCorrelationError(ValueError):
    """Authenticated release and staged installed-byte evidence do not agree."""


@dataclass(frozen=True, slots=True)
class CatalogStagedWheel:
    """An observed candidate wheel, not an active installed distribution."""

    component_id: str
    distribution: str
    version: str
    wheel_sha256: str
    publisher_payload_sha256: str


@dataclass(frozen=True, slots=True)
class CatalogStageCorrelation:
    """One transient candidate observation; no launch or activation capability."""

    transaction_id: str
    registry_payload_sha256: str
    pip_inventory_sha256: str
    native_payload_sha256: str
    modules: tuple[CatalogStagedWheel, ...]
    status: str = "SIGNED_STAGED_BYTES_OBSERVED_NOT_ACTIVE"
    authority: str = "NO_LAUNCH_RECEIPT_ACTIVATION_OR_UPDATE_AUTHORITY"


def inspect_catalog_bound_staged_bytes(
    snapshot: CatalogSnapshot,
    stage_root: Path,
    wheelhouse: Path,
    *,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    native_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    native_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> CatalogStageCorrelation:
    """Reauthenticate signed claims and reread staged pip/native bytes twice.

    The caller must have loaded ``snapshot`` using the independently pinned
    trust policy at the current time. Original envelopes are separately
    verified here to prevent substituting unrelated signed release claims.
    The existing auditors must validate the *whole* prepared wheelhouse and
    staged pip files; native evidence must bind the actual executable bytes.
    Even repeated reads are non-atomic and do not confer launch authority.
    """
    if (
        not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(stage_root, Path)
        or not isinstance(wheelhouse, Path)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or type(prepared_record) is not bytes
        or type(registry_envelope) is not bytes
        or type(lock_envelope) is not bytes
        or type(native_envelope) is not bytes
        or type(module_envelopes) is not dict
        or not 1 <= len(module_envelopes) <= 32
        or any(
            type(component) is not str or type(envelope) is not bytes
            for component, envelope in module_envelopes.items()
        )
    ):
        raise CatalogStageCorrelationError("invalid staged correlation inputs")
    try:
        registry = verify_registry_document(
            registry_envelope,
            trust=trust,
            now=now,
            checkpoint=registry_checkpoint,
        )
        if registry != snapshot.registry:
            raise CatalogStageCorrelationError(
                "signed registry differs from authenticated cache"
            )
        cached = {item.claims.component_id: item for item in snapshot.modules}
        if len(cached) != len(snapshot.modules):
            raise CatalogStageCorrelationError("duplicate cached module identity")
        if not set(module_envelopes) <= cached.keys():
            raise CatalogStageCorrelationError("publisher not present in signed cache")
        for component_id, envelope in module_envelopes.items():
            document = verify_module_document(
                envelope,
                registry=registry,
                trust=trust,
                now=now,
                checkpoint=cached[component_id].checkpoint,
            )
            if document != cached[component_id] or (
                document.claims.component_id != component_id
            ):
                raise CatalogStageCorrelationError(
                    "publisher envelope differs from authenticated cache"
                )
        prepared = parse_unverified_prepared_record(prepared_record)
        if (
            prepared.registry_payload_sha256 != registry.payload_sha256
            or prepared.trust_fingerprint != registry.trust_fingerprint
        ):
            raise CatalogStageCorrelationError("prepared registry or trust differs")
        registered = {
            canonicalize_name(item.distribution): item
            for item in registry.claims.modules
        }
        matched: list[CatalogStagedWheel] = []
        for wheel in prepared.wheels:
            registration = registered.get(canonicalize_name(wheel.distribution))
            if registration is None:
                continue  # Root-locked transitive dependency; auditor checks it.
            match_doc = cached.get(registration.component_id)
            if match_doc is None or registration.component_id not in module_envelopes:
                raise CatalogStageCorrelationError("selected publisher is not cached")
            matches = [
                release
                for release in match_doc.claims.releases
                if release.version == wheel.version
                and release.wheel == wheel.filename
                and release.sha256 == wheel.sha256
            ]
            if len(matches) != 1 or matches[0].revoked:
                raise CatalogStageCorrelationError(
                    "staged release absent, mismatched or revoked"
                )
            matched.append(
                CatalogStagedWheel(
                    registration.component_id,
                    wheel.distribution,
                    wheel.version,
                    wheel.sha256,
                    match_doc.payload_sha256,
                )
            )
        if not matched or {item.component_id for item in matched} != set(
            module_envelopes
        ):
            raise CatalogStageCorrelationError(
                "candidate publisher set disagrees with authenticated cache"
            )
        expected_publishers = tuple(
            sorted((row.component_id, row.publisher_payload_sha256) for row in matched)
        )

        def observe() -> tuple[ObservedPublisherPipCandidate, VerifiedNativeEvidence]:
            pip = audit_publisher_bound_pip_candidate(
                stage_root,
                wheelhouse,
                prepared_record=prepared_record,
                registry_envelope=registry_envelope,
                lock_envelope=lock_envelope,
                module_envelopes=module_envelopes,
                trust=trust,
                now=now,
                registry_checkpoint=registry_checkpoint,
                lock_checkpoint=lock_checkpoint,
                layout=layout,
            )
            native = verify_signed_staged_native_evidence(
                stage_root,
                wheelhouse,
                evidence_envelope=native_envelope,
                prepared_record=prepared_record,
                registry_envelope=registry_envelope,
                lock_envelope=lock_envelope,
                trust=trust,
                now=now,
                checkpoint=native_checkpoint,
                layout=layout,
            )
            if (
                pip.transaction_id != prepared.transaction_id
                or native.transaction_id != prepared.transaction_id
                or pip.stage_root != stage_root
                or native.stage_root != stage_root
                or pip.registry_payload_sha256 != registry.payload_sha256
                or pip.lock_payload_sha256 != prepared.lock_payload_sha256
                or pip.publisher_digests != expected_publishers
            ):
                raise CatalogStageCorrelationError(
                    "audited stage differs from signed prepared composition"
                )
            return pip, native

        first = observe()
        second = observe()
        if first != second:
            raise CatalogStageCorrelationError("staged bytes changed during re-audit")
        pip_result, native_result = second
        return CatalogStageCorrelation(
            prepared.transaction_id,
            registry.payload_sha256,
            pip_result.pip_inventory_sha256,
            native_result.payload_sha256,
            tuple(sorted(matched, key=lambda row: row.component_id)),
        )
    except (
        CatalogVerificationError,
        PreparedRecordError,
        PublisherPipPreflightError,
        NativeEvidenceError,
        OSError,
    ) as error:
        raise CatalogStageCorrelationError(
            "publisher authorization or physical stage verification refused"
        ) from error


__all__ = (
    "CatalogStageCorrelation",
    "CatalogStageCorrelationError",
    "CatalogStagedWheel",
    "inspect_catalog_bound_staged_bytes",
)
