"""Issue #49: publisher-bound, opt-in candidate console acceptance.

A signed wheelhouse lock alone is insufficient authorization to import PDS
module code. Verify every registered PDS publisher before running the
existing isolated staged console probe, and again after the probe. This is
an ephemeral observation, NEVER an active installed-state or launch receipt.
"""

from __future__ import annotations

import hashlib
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
from paper_data_suite.evergreen_public_contract_acceptance import (
    PublicContractAcceptanceError,
    accept_verified_candidate_public_contracts,
)
from paper_data_suite.evergreen_publisher_composition import (
    PublisherCompositionError,
    VerifiedPublisherComposition,
    verify_publisher_bound_composition,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
    load_update_intent,
)

_MAX_ENVELOPES: Final = 32
_MAX_ENVELOPE_BYTES: Final = 128 * 1024


class PublisherAcceptanceError(ValueError):
    """Publisher identity and public import acceptance cannot be joined."""


@dataclass(frozen=True, slots=True)
class ObservedPublisherBoundAcceptance:
    """Verified publishers plus observed console imports; no active authority."""

    transaction_id: str
    journal_revision: int
    stage_relative_path: str
    site_inventory_sha256: str
    native_payload_sha256: str
    root_console_targets: tuple[tuple[str, str, str], ...]
    publisher_digests: tuple[tuple[str, str], ...]
    external_distributions: tuple[str, ...]


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _root_consistency(
    publisher: VerifiedPublisherComposition,
    *,
    prepared_record: bytes,
    observed: tuple[tuple[str, str, str], ...],
) -> None:
    try:
        prepared = parse_unverified_prepared_record(prepared_record)
    except PreparedRecordError as error:
        raise PublisherAcceptanceError(
            "prepared roots could not be inspected"
        ) from error
    approved = {
        canonicalize_name(module.distribution): module
        for module in publisher.authorized_modules
    }
    expected: set[tuple[str, str, str]] = set()
    for name in prepared.roots:
        key = canonicalize_name(name)
        if key not in approved:
            raise PublisherAcceptanceError("selected root lacks publisher authority")
        release = approved[key]
        expected.add(
            (release.distribution, release.console_script, release.console_target)
        )
    normalized_actual = {
        (canonicalize_name(owner), console, target)
        for owner, console, target in observed
    }
    normalized_expected = {
        (canonicalize_name(owner), console, target)
        for owner, console, target in expected
    }
    if (
        not expected
        or len(expected) != len(observed)
        or normalized_actual != normalized_expected
    ):
        raise PublisherAcceptanceError("public consoles differ from signed releases")


def accept_publisher_bound_candidate_public_contracts(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    expected_revision: int,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    now: datetime,
    timeout_seconds: int = 30,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> ObservedPublisherBoundAcceptance:
    """Require delegated release proof before AND after explicit code imports.

    The existing public probe locks the journal/selection during imports and
    checks exact source/native bytes before/after. This entrypoint adds the
    independently delegated PDS release authority missing from the root lock.
    A successful observation does not prove Core provenance, integration
    compatibility, durable active-state continuity, or code sandboxing.
    """
    if (
        type(module_envelopes) is not dict
        or not 1 <= len(module_envelopes) <= _MAX_ENVELOPES
        or any(
            type(name) is not str
            or type(raw) is not bytes
            or not 1 <= len(raw) <= _MAX_ENVELOPE_BYTES
            for name, raw in module_envelopes.items()
        )
        or type(expected_revision) is not int
        or expected_revision != 1
    ):
        raise PublisherAcceptanceError("invalid publisher acceptance parameters")
    try:
        root = _safe_root(software_root, classroom_workspace)
        journal = load_update_intent(
            root,
            classroom_workspace=classroom_workspace,
            transaction_id=transaction_id,
        )
        if (
            journal is None
            or journal.phase is not UpdatePhase.CANDIDATE_VERIFIED
            or journal.revision != expected_revision
        ):
            raise PublisherAcceptanceError("exact candidate-verified journal required")
        for raw, pinned in (
            (prepared_record, journal.prepared_sha256),
            (registry_envelope, journal.registry_envelope_sha256),
            (lock_envelope, journal.lock_envelope_sha256),
            (evidence_envelope, journal.native_envelope_sha256),
        ):
            if _digest(raw) != pinned:
                raise PublisherAcceptanceError("journal candidate evidence mismatch")
        wheelhouse = root / journal.wheelhouse_relative_path
        if _relative_child(root, wheelhouse) != journal.wheelhouse_relative_path:
            raise PublisherAcceptanceError("unsafe locked wheelhouse path")
    except PublisherAcceptanceError:
        raise
    except (UpdateJournalError, OSError, ValueError) as error:
        raise PublisherAcceptanceError("candidate journal preflight failed") from error

    def verify_publishers() -> VerifiedPublisherComposition:
        try:
            verified = verify_publisher_bound_composition(
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
        except (PublisherCompositionError, ValueError, OSError) as error:
            raise PublisherAcceptanceError(
                "delegated publisher verification failed"
            ) from error
        if verified.transaction_id != transaction_id:
            raise PublisherAcceptanceError("publisher transaction mismatch")
        return verified

    before = verify_publishers()
    try:
        observed = accept_verified_candidate_public_contracts(
            root,
            classroom_workspace=classroom_workspace,
            transaction_id=transaction_id,
            expected_revision=expected_revision,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            evidence_envelope=evidence_envelope,
            trust=trust,
            now=now,
            timeout_seconds=timeout_seconds,
            layout=layout,
        )
    except (PublicContractAcceptanceError, ValueError, OSError) as error:
        raise PublisherAcceptanceError(
            "candidate public import acceptance failed"
        ) from error
    after = verify_publishers()
    if before != after:
        raise PublisherAcceptanceError("publisher evidence changed during imports")
    _root_consistency(
        after,
        prepared_record=prepared_record,
        observed=observed.console_targets,
    )
    return ObservedPublisherBoundAcceptance(
        transaction_id=observed.transaction_id,
        journal_revision=observed.journal_revision,
        stage_relative_path=observed.stage_relative_path,
        site_inventory_sha256=observed.site_inventory_sha256,
        native_payload_sha256=observed.native_payload_sha256,
        root_console_targets=observed.console_targets,
        publisher_digests=tuple(
            sorted(
                (module.component_id, module.publisher_payload_sha256)
                for module in after.authorized_modules
            )
        ),
        external_distributions=after.external_distributions,
    )


__all__ = (
    "ObservedPublisherBoundAcceptance",
    "PublisherAcceptanceError",
    "accept_publisher_bound_candidate_public_contracts",
)
