"""Issue #49: externally pinned active-receipt continuity, not launch authority.

Receipt bytes and a digest stored alongside them are equally replaceable.
Only a checkpoint supplied from an independently protected source can pin a
receipt; none of these pure helpers provisions or protects that source.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, cast

from paper_data_suite.evergreen_journal_pip_preflight import (
    ObservedJournalPipCandidate,
)

_MAX_RECEIPT: Final = 16 * 1024
_HEX64: Final = re.compile(r"[0-9a-f]{64}\Z")
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_ID: Final = re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
_DIST: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_CONSOLE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_TARGET: Final = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r":[A-Za-z_][A-Za-z0-9_]*\Z"
)
_UTC: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_REL: Final = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")


class ActiveReceiptError(ValueError):
    """Receipt bytes, continuity or an externally pinned head do not agree."""


@dataclass(frozen=True, slots=True)
class UntrustedActiveReceipt:
    """Parsed receipt claim, NOT proof of historical activity or launch rights."""

    generation: int
    recorded_at: datetime
    transaction_id: str
    stage_relative_path: str
    wheelhouse_relative_path: str
    prepared_sha256: str
    registry_sha256: str
    lock_sha256: str
    native_envelope_sha256: str
    native_payload_sha256: str
    pip_inventory_sha256: str
    publisher_digests: tuple[tuple[str, str], ...]
    root_console_targets: tuple[tuple[str, str, str], ...]
    external_distributions: tuple[str, ...]
    previous_receipt_sha256: str | None


@dataclass(frozen=True, slots=True)
class ExternallyPinnedReceiptHead:
    """Caller-supplied checkpoint; ONLY credible if stored outside local control."""

    generation: int
    receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.generation) is not int
            or not 1 <= self.generation <= 2**53 - 1
            or type(self.receipt_sha256) is not str
            or not _HEX64.fullmatch(self.receipt_sha256)
        ):
            raise ActiveReceiptError("invalid external checkpoint")


@dataclass(frozen=True, slots=True)
class PinnedReceiptObservation:
    """Pinned metadata only; installed bytes must still be reverified."""

    receipt: UntrustedActiveReceipt
    digest: str


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ActiveReceiptError("duplicate active receipt field")
        result[key] = value
    return result


def _name(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        raise ActiveReceiptError(f"invalid receipt {label}")
    return value


def _relative(value: object, label: str) -> str:
    path = _name(value, _REL, label)
    if any(part in (".", "..") for part in path.split("/")):
        raise ActiveReceiptError(f"unsafe receipt {label}")
    return path


def _hash(value: object, label: str) -> str:
    return _name(value, _HEX64, label)


def _utc(value: object) -> datetime:
    raw = _name(value, _UTC, "timestamp")
    try:
        when = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ActiveReceiptError("invalid receipt timestamp") from error
    return when


def _rows(
    value: object, size: int, patterns: tuple[re.Pattern[str], ...], label: str
) -> tuple[tuple[str, ...], ...]:
    if type(value) is not list or len(value) > 32:
        raise ActiveReceiptError(f"invalid receipt {label}")
    output: list[tuple[str, ...]] = []
    for row in value:
        if type(row) is not list or len(row) != size:
            raise ActiveReceiptError(f"invalid receipt {label} row")
        output.append(
            tuple(_name(item, pattern, label) for item, pattern in zip(row, patterns))
        )
    if output != sorted(set(output)):
        raise ActiveReceiptError(f"receipt {label} must be unique and sorted")
    if label == "publisher digests" and len({row[0] for row in output}) != len(output):
        raise ActiveReceiptError("duplicate publisher component identity")
    if label == "console targets" and len({row[1] for row in output}) != len(output):
        raise ActiveReceiptError("conflicting console launcher names")
    return tuple(output)


def _externals(value: object) -> tuple[str, ...]:
    if type(value) is not list or len(value) > 256:
        raise ActiveReceiptError("invalid external distributions")
    output = tuple(_name(item, _DIST, "external distribution") for item in value)
    if tuple(sorted(set(output))) != output:
        raise ActiveReceiptError("external distributions not unique and sorted")
    return output


def _time_str(when: datetime) -> str:
    if not isinstance(when, datetime) or when.tzinfo is None:
        raise ActiveReceiptError("receipt timestamp must be aware")
    utc = when.astimezone(timezone.utc)
    if utc.microsecond:
        raise ActiveReceiptError("receipt timestamp must have whole seconds")
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _document(receipt: UntrustedActiveReceipt) -> dict[str, object]:
    return {
        "record_type": "pds_evergreen_untrusted_active_receipt",
        "schema_version": 1,
        "generation": receipt.generation,
        "recorded_at": _time_str(receipt.recorded_at),
        "transaction_id": receipt.transaction_id,
        "stage_relative_path": receipt.stage_relative_path,
        "wheelhouse_relative_path": receipt.wheelhouse_relative_path,
        "prepared_sha256": receipt.prepared_sha256,
        "registry_sha256": receipt.registry_sha256,
        "lock_sha256": receipt.lock_sha256,
        "native_envelope_sha256": receipt.native_envelope_sha256,
        "native_payload_sha256": receipt.native_payload_sha256,
        "pip_inventory_sha256": receipt.pip_inventory_sha256,
        "publisher_digests": [list(row) for row in receipt.publisher_digests],
        "root_console_targets": [list(row) for row in receipt.root_console_targets],
        "external_distributions": list(receipt.external_distributions),
        "previous_receipt_sha256": receipt.previous_receipt_sha256,
    }


def _encode(receipt: UntrustedActiveReceipt) -> bytes:
    return json.dumps(
        _document(receipt), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def parse_untrusted_active_receipt(raw: bytes) -> UntrustedActiveReceipt:
    """Strict canonical parser; does not confer authority on local bytes."""
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_RECEIPT:
        raise ActiveReceiptError("active receipt size invalid")
    try:
        document: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except ActiveReceiptError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise ActiveReceiptError("malformed active receipt") from error
    if not isinstance(document, dict) or document.keys() != _document_fields():
        raise ActiveReceiptError("unexpected active receipt fields")
    data = cast(dict[str, object], document)
    if (
        data["record_type"] != "pds_evergreen_untrusted_active_receipt"
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or type(data["generation"]) is not int
        or not 1 <= data["generation"] <= 2**53 - 1
    ):
        raise ActiveReceiptError("invalid active receipt schema or generation")
    previous = data["previous_receipt_sha256"]
    if (data["generation"] == 1) != (previous is None):
        raise ActiveReceiptError("genesis or predecessor mismatch")
    previous_sha = None if previous is None else _hash(previous, "predecessor")
    publisher = _rows(data["publisher_digests"], 2, (_ID, _HEX64), "publisher digests")
    launchers = _rows(
        data["root_console_targets"],
        3,
        (_DIST, _CONSOLE, _TARGET),
        "console targets",
    )
    result = UntrustedActiveReceipt(
        generation=data["generation"],
        recorded_at=_utc(data["recorded_at"]),
        transaction_id=_name(data["transaction_id"], _TX, "transaction"),
        stage_relative_path=_relative(data["stage_relative_path"], "stage path"),
        wheelhouse_relative_path=_relative(
            data["wheelhouse_relative_path"], "wheelhouse path"
        ),
        prepared_sha256=_hash(data["prepared_sha256"], "prepared hash"),
        registry_sha256=_hash(data["registry_sha256"], "registry hash"),
        lock_sha256=_hash(data["lock_sha256"], "lock hash"),
        native_envelope_sha256=_hash(
            data["native_envelope_sha256"], "native envelope hash"
        ),
        native_payload_sha256=_hash(
            data["native_payload_sha256"], "native payload hash"
        ),
        pip_inventory_sha256=_hash(data["pip_inventory_sha256"], "pip hash"),
        publisher_digests=cast(tuple[tuple[str, str], ...], publisher),
        root_console_targets=cast(tuple[tuple[str, str, str], ...], launchers),
        external_distributions=_externals(data["external_distributions"]),
        previous_receipt_sha256=previous_sha,
    )
    if _encode(result) != raw:
        raise ActiveReceiptError("noncanonical active receipt")
    return result


def _document_fields() -> set[str]:
    return {
        "record_type",
        "schema_version",
        "generation",
        "recorded_at",
        "transaction_id",
        "stage_relative_path",
        "wheelhouse_relative_path",
        "prepared_sha256",
        "registry_sha256",
        "lock_sha256",
        "native_envelope_sha256",
        "native_payload_sha256",
        "pip_inventory_sha256",
        "publisher_digests",
        "root_console_targets",
        "external_distributions",
        "previous_receipt_sha256",
    }


def make_untrusted_active_receipt(
    candidate: ObservedJournalPipCandidate,
    *,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    native_envelope: bytes,
    generation: int,
    recorded_at: datetime,
    previous: ExternallyPinnedReceiptHead | None,
) -> bytes:
    """Prepare local receipt bytes; the resulting hash is NOT a trust anchor.

    Requires an already audited ephemeral candidate but does not reauthenticate
    it. Authorizing a new checkpoint is an independent, future OS-trust action.
    """
    if (
        not isinstance(candidate, ObservedJournalPipCandidate)
        or type(generation) is not int
        or not 1 <= generation <= 2**53 - 1
        or (generation == 1) != (previous is None)
        or (previous is not None and generation != previous.generation + 1)
        or any(
            type(data) is not bytes
            for data in (
                prepared_record,
                registry_envelope,
                lock_envelope,
                native_envelope,
            )
        )
    ):
        raise ActiveReceiptError("invalid receipt draft inputs or continuity")
    receipt = UntrustedActiveReceipt(
        generation=generation,
        recorded_at=recorded_at,
        transaction_id=candidate.transaction_id,
        stage_relative_path=candidate.stage_relative_path,
        wheelhouse_relative_path=candidate.wheelhouse_relative_path,
        prepared_sha256=_digest(prepared_record),
        registry_sha256=_digest(registry_envelope),
        lock_sha256=_digest(lock_envelope),
        native_envelope_sha256=_digest(native_envelope),
        native_payload_sha256=candidate.native_payload_sha256,
        pip_inventory_sha256=candidate.pip_inventory_sha256,
        publisher_digests=candidate.publisher_digests,
        root_console_targets=candidate.root_console_targets,
        external_distributions=candidate.external_distributions,
        previous_receipt_sha256=(previous.receipt_sha256 if previous else None),
    )
    raw = _encode(receipt)
    parse_untrusted_active_receipt(raw)
    return raw


def verify_externally_pinned_receipt(
    raw: bytes,
    *,
    head: ExternallyPinnedReceiptHead,
    predecessor: ExternallyPinnedReceiptHead | None,
) -> PinnedReceiptObservation:
    """Compare local bytes to independent head AND predecessor checkpoints.

    ``head`` and ``predecessor`` must originate from independently protected
    storage. Creating them from these receipt bytes would be circular.
    """
    if not isinstance(head, ExternallyPinnedReceiptHead) or (
        predecessor is not None
        and not isinstance(predecessor, ExternallyPinnedReceiptHead)
    ):
        raise ActiveReceiptError("missing independently pinned receipt checkpoint")
    receipt = parse_untrusted_active_receipt(raw)
    digest = _digest(raw)
    if digest != head.receipt_sha256 or receipt.generation != head.generation:
        raise ActiveReceiptError("receipt differs from independently pinned head")
    if predecessor is None:
        if receipt.generation != 1 or receipt.previous_receipt_sha256 is not None:
            raise ActiveReceiptError("missing pinned predecessor")
    elif (
        predecessor.generation + 1 != head.generation
        or receipt.previous_receipt_sha256 != predecessor.receipt_sha256
    ):
        raise ActiveReceiptError("receipt predecessor continuity mismatch")
    return PinnedReceiptObservation(receipt=receipt, digest=digest)


def compare_receipt_to_observed_candidate(
    verified: PinnedReceiptObservation,
    candidate: ObservedJournalPipCandidate,
    *,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    native_envelope: bytes,
) -> None:
    """Compare already observed bytes; caller must reauthenticate them afresh.

    This comparison does not re-run the signed publisher/pip/native audit and
    MUST NOT be treated as permission to launch or activate an environment.
    """
    if not isinstance(verified, PinnedReceiptObservation) or not isinstance(
        candidate, ObservedJournalPipCandidate
    ):
        raise ActiveReceiptError("invalid receipt-to-candidate inputs")
    for value in (prepared_record, registry_envelope, lock_envelope, native_envelope):
        if type(value) is not bytes:
            raise ActiveReceiptError("invalid candidate evidence bytes")
    row = verified.receipt
    if (
        row.transaction_id != candidate.transaction_id
        or row.stage_relative_path != candidate.stage_relative_path
        or row.wheelhouse_relative_path != candidate.wheelhouse_relative_path
        or row.native_payload_sha256 != candidate.native_payload_sha256
        or row.pip_inventory_sha256 != candidate.pip_inventory_sha256
        or row.publisher_digests != candidate.publisher_digests
        or row.root_console_targets != candidate.root_console_targets
        or row.external_distributions != candidate.external_distributions
        or row.prepared_sha256 != _digest(prepared_record)
        or row.registry_sha256 != _digest(registry_envelope)
        or row.lock_sha256 != _digest(lock_envelope)
        or row.native_envelope_sha256 != _digest(native_envelope)
    ):
        raise ActiveReceiptError("pinned receipt does not match candidate evidence")


__all__ = (
    "ActiveReceiptError",
    "ExternallyPinnedReceiptHead",
    "PinnedReceiptObservation",
    "UntrustedActiveReceipt",
    "compare_receipt_to_observed_candidate",
    "make_untrusted_active_receipt",
    "parse_untrusted_active_receipt",
    "verify_externally_pinned_receipt",
)
