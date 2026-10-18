"""Issue #49: strictly bounded PREPARED installation-composition records.

No record asserts an installed artifact, validated installed RECORD entries,
managed activation, or permission to launch. Parsed records are untrusted;
comparison always repeats verification of raw signed documents and wheel bytes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, cast

from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_dependency_lock import (
    VerifiedLockedWheelhouse,
    verify_signed_locked_wheelhouse,
)

_MAX_RECORD: Final = 96 * 1024
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_UTC: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_ID: Final = re.compile(r"[a-z0-9][a-z0-9._-]{1,95}\Z")
_WHEEL_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,190}\.whl\Z")


class PreparedRecordError(ValueError):
    """Malformed or mismatched stage-only composition record."""


@dataclass(frozen=True, slots=True)
class PreparedWheel:
    distribution: str
    version: str
    filename: str
    sha256: str


@dataclass(frozen=True, slots=True)
class UnverifiedPreparedRecord:
    """Only a candidate manifest, NOT evidence that packages were installed."""

    transaction_id: str
    prepared_at: datetime
    python_minor: str
    platform: str
    registry_payload_sha256: str
    trust_fingerprint: str
    lock_payload_sha256: str
    lock_revision: int
    roots: tuple[str, ...]
    wheels: tuple[PreparedWheel, ...]
    dependency_edges: tuple[tuple[str, str], ...]


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PreparedRecordError("duplicate prepared record JSON member")
        result[key] = value
    return result


def _checked(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PreparedRecordError(f"invalid prepared record {label}")
    return value


def _time(value: object) -> datetime:
    raw = _checked(value, _UTC, "prepared_at")
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise PreparedRecordError("invalid prepared record timestamp") from error


def _ids(value: object, maximum: int, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise PreparedRecordError(f"invalid prepared record {label}")
    items = tuple(_checked(item, _ID, label) for item in value)
    if len(set(items)) != len(items):
        raise PreparedRecordError(f"duplicate prepared record {label}")
    return items


def _wheels(value: object) -> tuple[PreparedWheel, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 128:
        raise PreparedRecordError("invalid prepared record wheel count")
    output: list[PreparedWheel] = []
    for entry in value:
        if not isinstance(entry, dict) or entry.keys() != {
            "distribution",
            "version",
            "filename",
            "sha256",
        }:
            raise PreparedRecordError("invalid prepared wheel fields")
        item = cast(dict[str, object], entry)
        output.append(
            PreparedWheel(
                _checked(item["distribution"], _ID, "distribution"),
                _checked(item["version"], _ID, "version"),
                _checked(item["filename"], _WHEEL_NAME, "filename"),
                _checked(item["sha256"], _SHA, "sha256"),
            )
        )
    if len({wheel.distribution for wheel in output}) != len(output):
        raise PreparedRecordError("duplicate prepared wheel distribution")
    return tuple(output)


def _edges(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or len(value) > 16384:
        raise PreparedRecordError("invalid dependency edge count")
    edges: list[tuple[str, str]] = []
    for entry in value:
        if not isinstance(entry, list) or len(entry) != 2:
            raise PreparedRecordError("invalid dependency edge")
        edges.append((_checked(entry[0], _ID, "edge"), _checked(entry[1], _ID, "edge")))
    if len(set(edges)) != len(edges):
        raise PreparedRecordError("duplicate dependency edge")
    return tuple(edges)


def _record_from_verified(
    verified: VerifiedLockedWheelhouse,
    transaction_id: str,
    prepared_at: datetime,
) -> UnverifiedPreparedRecord:
    lock = verified.lock
    inspected = verified.inspection
    return UnverifiedPreparedRecord(
        transaction_id=transaction_id,
        prepared_at=prepared_at,
        python_minor=lock.python_minor,
        platform=lock.platform,
        registry_payload_sha256=lock.registry_payload_sha256,
        trust_fingerprint=lock.trust_fingerprint,
        lock_payload_sha256=lock.payload_sha256,
        lock_revision=lock.revision,
        roots=inspected.roots,
        wheels=tuple(
            PreparedWheel(item.distribution, item.version, item.filename, item.sha256)
            for item in inspected.wheels
        ),
        dependency_edges=inspected.dependency_edges,
    )


def prepare_composition_record(
    directory: Path,
    *,
    lock_envelope: bytes,
    registry_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    transaction_id: str,
    checkpoint: RevisionCheckpoint | None = None,
) -> UnverifiedPreparedRecord:
    """Reverify signatures and wheel bytes, then describe candidate stage only."""
    tx = _checked(transaction_id, _TX, "transaction ID")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise PreparedRecordError("aware preparation clock required")
    verified = verify_signed_locked_wheelhouse(
        directory,
        lock_envelope=lock_envelope,
        registry_envelope=registry_envelope,
        trust=trust,
        now=now,
        checkpoint=checkpoint,
    )
    return _record_from_verified(
        verified, tx, now.astimezone(timezone.utc).replace(microsecond=0)
    )


def serialize_prepared_record(record: UnverifiedPreparedRecord) -> bytes:
    """Canonicalize an untrusted candidate only. Serialization is NOT signing."""
    if not isinstance(record, UnverifiedPreparedRecord):
        raise PreparedRecordError("expected prepared record data")
    document = {
        "record_type": "pds_evergreen_prepared_composition",
        "schema_version": 1,
        "phase": "prepared_not_installed",
        "transaction_id": record.transaction_id,
        "prepared_at": record.prepared_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python_minor": record.python_minor,
        "platform": record.platform,
        "registry_payload_sha256": record.registry_payload_sha256,
        "trust_fingerprint": record.trust_fingerprint,
        "lock_payload_sha256": record.lock_payload_sha256,
        "lock_revision": record.lock_revision,
        "roots": list(record.roots),
        "wheels": [
            {
                "distribution": w.distribution,
                "version": w.version,
                "filename": w.filename,
                "sha256": w.sha256,
            }
            for w in record.wheels
        ],
        "dependency_edges": [list(edge) for edge in record.dependency_edges],
    }
    data = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    if len(data) > _MAX_RECORD:
        raise PreparedRecordError("prepared record exceeds size limit")
    return data


def parse_unverified_prepared_record(data: bytes) -> UnverifiedPreparedRecord:
    """Reject malformed serialized records; does NOT authenticate their claims."""
    if type(data) is not bytes or not 1 <= len(data) <= _MAX_RECORD:
        raise PreparedRecordError("invalid prepared record size")
    try:
        raw: object = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise PreparedRecordError("invalid prepared record JSON") from error
    if not isinstance(raw, dict):
        raise PreparedRecordError("prepared record must be an object")
    doc = cast(dict[str, object], raw)
    expected = {
        "record_type",
        "schema_version",
        "phase",
        "transaction_id",
        "prepared_at",
        "python_minor",
        "platform",
        "registry_payload_sha256",
        "trust_fingerprint",
        "lock_payload_sha256",
        "lock_revision",
        "roots",
        "wheels",
        "dependency_edges",
    }
    if doc.keys() != expected:
        raise PreparedRecordError("unknown prepared record fields")
    if (
        doc["record_type"] != "pds_evergreen_prepared_composition"
        or type(doc["schema_version"]) is not int
        or doc["schema_version"] != 1
        or doc["phase"] != "prepared_not_installed"
    ):
        raise PreparedRecordError("unsupported prepared record phase or version")
    revision = doc["lock_revision"]
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise PreparedRecordError("invalid prepared lock revision")
    record = UnverifiedPreparedRecord(
        transaction_id=_checked(doc["transaction_id"], _TX, "transaction ID"),
        prepared_at=_time(doc["prepared_at"]),
        python_minor=_checked(doc["python_minor"], _ID, "python"),
        platform=_checked(doc["platform"], _ID, "platform"),
        registry_payload_sha256=_checked(
            doc["registry_payload_sha256"], _SHA, "registry hash"
        ),
        trust_fingerprint=_checked(doc["trust_fingerprint"], _SHA, "trust fingerprint"),
        lock_payload_sha256=_checked(doc["lock_payload_sha256"], _SHA, "lock hash"),
        lock_revision=revision,
        roots=_ids(doc["roots"], 128, "roots"),
        wheels=_wheels(doc["wheels"]),
        dependency_edges=_edges(doc["dependency_edges"]),
    )
    if serialize_prepared_record(record) != data:
        raise PreparedRecordError("prepared record must use canonical encoding")
    return record


def verify_prepared_record_against_wheelhouse(
    data: bytes,
    directory: Path,
    *,
    lock_envelope: bytes,
    registry_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    checkpoint: RevisionCheckpoint | None = None,
) -> UnverifiedPreparedRecord:
    """Recheck candidate against CURRENT signed lock and exact wheel bytes.

    Returning a matching prepared record is NOT proof of installation, mutable
    site-packages, safe entry points, activation, or receipt durability.
    """
    record = parse_unverified_prepared_record(data)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise PreparedRecordError("aware verification clock required")
    if record.prepared_at > now.astimezone(timezone.utc):
        raise PreparedRecordError("prepared record claims a future clock")
    recomputed = prepare_composition_record(
        directory,
        lock_envelope=lock_envelope,
        registry_envelope=registry_envelope,
        trust=trust,
        now=now,
        transaction_id=record.transaction_id,
        checkpoint=checkpoint,
    )
    recomputed = UnverifiedPreparedRecord(
        transaction_id=recomputed.transaction_id,
        prepared_at=record.prepared_at,
        python_minor=recomputed.python_minor,
        platform=recomputed.platform,
        registry_payload_sha256=recomputed.registry_payload_sha256,
        trust_fingerprint=recomputed.trust_fingerprint,
        lock_payload_sha256=recomputed.lock_payload_sha256,
        lock_revision=recomputed.lock_revision,
        roots=recomputed.roots,
        wheels=recomputed.wheels,
        dependency_edges=recomputed.dependency_edges,
    )
    if recomputed != record:
        raise PreparedRecordError(
            "prepared record mismatches current verified wheelhouse"
        )
    return record


__all__ = (
    "PreparedRecordError",
    "PreparedWheel",
    "UnverifiedPreparedRecord",
    "prepare_composition_record",
    "serialize_prepared_record",
    "parse_unverified_prepared_record",
    "verify_prepared_record_against_wheelhouse",
)
