"""Issue #49 Slice 62: correlate signed witness receipt with selected staged bytes.

Explicitly invoked read-only diagnostic; NOT an active-installation attestation,
a persistent protected receipt, software activation, or permission to launch.
The witness endpoint/key and publisher trust MUST be independently provisioned.
Never call this at ordinary offline teacher launch time.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    UntrustedSlotSelection,
    read_candidate_selection,
)
from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    UntrustedActiveReceipt,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_stage_correlation import (
    CatalogStageCorrelationError,
    CatalogStagedWheel,
    inspect_catalog_bound_staged_bytes,
)
from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_checkpoint_witness import (
    CheckpointWitnessError,
    CheckpointWitnessTransport,
    WitnessReceiptObservation,
    query_checkpoint_witness,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    PublisherPipPreflightError,
    audit_publisher_bound_pip_candidate,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    _relative_child,
    _safe_root,
)


class WitnessSelectedStageError(ValueError):
    """Selected-stage, signed witness and publisher evidence cannot be reconciled."""


@dataclass(frozen=True, slots=True)
class WitnessSelectedStageObservation:
    """Transient matched observations, never a launch or activation credential."""

    transaction_id: str
    generation: int
    witness_revision: int
    receipt_sha256: str
    signed_witness_payload_sha256: str
    pip_inventory_sha256: str
    native_payload_sha256: str
    modules: tuple[CatalogStagedWheel, ...]
    status: str = "WITNESS_PINNED_SELECTED_STAGED_BYTES_OBSERVED_ONLY"
    authority: str = "NO_ACTIVE_LAUNCH_RECEIPT_WRITE_OR_ACTIVATION_AUTHORITY"


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _selection_matches(
    selection: UntrustedSlotSelection | None,
    receipt: UntrustedActiveReceipt,
    prepared_record: bytes,
    native_envelope: bytes,
) -> bool:
    return selection is not None and (
        selection.transaction_id == receipt.transaction_id
        and selection.generation == receipt.generation
        and selection.stage_relative_path == receipt.stage_relative_path
        and selection.prepared_sha256 == receipt.prepared_sha256
        and selection.native_envelope_sha256 == receipt.native_envelope_sha256
        and _sha(prepared_record) == receipt.prepared_sha256
        and _sha(native_envelope) == receipt.native_envelope_sha256
    )


def _witness_matches(
    signed: WitnessReceiptObservation, receipt: UntrustedActiveReceipt, digest: str
) -> bool:
    return (
        isinstance(signed, WitnessReceiptObservation)
        and signed.receipt.digest == digest
        and signed.receipt.receipt == receipt
        and signed.receipt.receipt.generation == receipt.generation
    )


def inspect_witness_pinned_selected_staged_bytes(
    snapshot: CatalogSnapshot,
    software_root: Path,
    *,
    classroom_workspace: Path,
    receipt_bytes: bytes,
    installation_id: str,
    expected_witness_id: str,
    witness_transport: CheckpointWitnessTransport,
    pinned_witness_public_key: bytes,
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
) -> WitnessSelectedStageObservation:
    """Read selected bytes, fresh witness head and signed stage; recheck for drift.

    Signed witness agreement is required both before and after the physical
    audits. Every locally claimed receipt composition field is cross-checked
    against signed inputs and the verified pip/native audit. The selected
    pointer alone has no authority and may be replaced after this returns.
    """
    if (
        not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(software_root, Path)
        or not isinstance(classroom_workspace, Path)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or any(
            type(blob) is not bytes
            for blob in (
                receipt_bytes,
                prepared_record,
                registry_envelope,
                lock_envelope,
                native_envelope,
                pinned_witness_public_key,
            )
        )
        or not callable(witness_transport)
        or type(module_envelopes) is not dict
        or not 1 <= len(module_envelopes) <= 32
        or any(
            type(component_id) is not str or type(raw) is not bytes
            for component_id, raw in module_envelopes.items()
        )
    ):
        raise WitnessSelectedStageError("invalid explicit witness-stage inputs")
    try:
        root = _safe_root(software_root, classroom_workspace)
        receipt = parse_untrusted_active_receipt(receipt_bytes)
        selected = read_candidate_selection(
            root, classroom_workspace=classroom_workspace
        )
        if not _selection_matches(selected, receipt, prepared_record, native_envelope):
            raise WitnessSelectedStageError("selected slot differs from pinned receipt")
        if (
            _sha(registry_envelope) != receipt.registry_sha256
            or _sha(lock_envelope) != receipt.lock_sha256
        ):
            raise WitnessSelectedStageError("signed inputs differ from pinned receipt")
        stage = root / receipt.stage_relative_path
        wheels = root / receipt.wheelhouse_relative_path
        if (
            _relative_child(root, stage) != receipt.stage_relative_path
            or _relative_child(root, wheels) != receipt.wheelhouse_relative_path
        ):
            raise WitnessSelectedStageError("selected paths are not confined")
        digest = _sha(receipt_bytes)
        first_head = query_checkpoint_witness(
            witness_transport,
            installation_id=installation_id,
            receipt_bytes=receipt_bytes,
            pinned_public_key=pinned_witness_public_key,
            expected_witness_id=expected_witness_id,
            now=now,
        )
        if not _witness_matches(first_head, receipt, digest):
            raise WitnessSelectedStageError("signed head differs from selected receipt")
        correlated = inspect_catalog_bound_staged_bytes(
            snapshot,
            stage,
            wheels,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            module_envelopes=module_envelopes,
            native_envelope=native_envelope,
            trust=trust,
            now=now,
            registry_checkpoint=registry_checkpoint,
            lock_checkpoint=lock_checkpoint,
            native_checkpoint=native_checkpoint,
            layout=layout,
        )
        if (
            correlated.transaction_id != receipt.transaction_id
            or correlated.registry_payload_sha256 != snapshot.registry.payload_sha256
            or correlated.pip_inventory_sha256 != receipt.pip_inventory_sha256
            or correlated.native_payload_sha256 != receipt.native_payload_sha256
            or tuple(
                sorted(
                    (module.component_id, module.publisher_payload_sha256)
                    for module in correlated.modules
                )
            )
            != receipt.publisher_digests
        ):
            raise WitnessSelectedStageError("audited stage differs from pinned receipt")
        # Slice 60 reports module/pip/native digests. Reread the whole pip
        # inventory here to bind the receipt's console and external dependency
        # claims, which the narrower correlation result does not expose.
        pip = audit_publisher_bound_pip_candidate(
            stage,
            wheels,
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
        if (
            pip.transaction_id != receipt.transaction_id
            or pip.registry_payload_sha256 != correlated.registry_payload_sha256
            or pip.pip_inventory_sha256 != correlated.pip_inventory_sha256
            or pip.publisher_digests != receipt.publisher_digests
            or pip.root_console_targets != receipt.root_console_targets
            or pip.external_distributions != receipt.external_distributions
            or pip.stage_root != stage
            or pip.wheelhouse != wheels
        ):
            raise WitnessSelectedStageError("receipt console/dependency audit differs")
        if (
            read_candidate_selection(root, classroom_workspace=classroom_workspace)
            != selected
        ):
            raise WitnessSelectedStageError("selected slot changed during audit")
        second_head = query_checkpoint_witness(
            witness_transport,
            installation_id=installation_id,
            receipt_bytes=receipt_bytes,
            pinned_public_key=pinned_witness_public_key,
            expected_witness_id=expected_witness_id,
            now=now,
            minimum_witness_revision=first_head.witness_revision,
        )
        if (
            not _witness_matches(second_head, receipt, digest)
            or second_head.witness_revision != first_head.witness_revision
            or read_candidate_selection(root, classroom_workspace=classroom_workspace)
            != selected
        ):
            raise WitnessSelectedStageError("witness head or selection changed")
        return WitnessSelectedStageObservation(
            receipt.transaction_id,
            receipt.generation,
            second_head.witness_revision,
            digest,
            second_head.signed_payload_sha256,
            correlated.pip_inventory_sha256,
            correlated.native_payload_sha256,
            correlated.modules,
        )
    except (
        ActiveReceiptError,
        ActivationSlotError,
        CheckpointWitnessError,
        CatalogStageCorrelationError,
        PublisherPipPreflightError,
        UpdateJournalError,
        OSError,
    ) as error:
        raise WitnessSelectedStageError(
            "selected receipt, signed witness or physical installed bytes refused"
        ) from error


__all__ = (
    "WitnessSelectedStageError",
    "WitnessSelectedStageObservation",
    "inspect_witness_pinned_selected_staged_bytes",
)
