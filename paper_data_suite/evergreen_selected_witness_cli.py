"""Issue #49 Slice 63: opt-in witnessed selected-installation CLI diagnostics.

An operator-provided configuration is NOT a trust anchor. The publisher policy,
TLS CA and witness public key pins must have independent provenances. This
networked audit never runs during default/offline modules, doctor or launch.
The reported state grants no launch, switch, CAS or receipt-write authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import cast

from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_catalog_state import (
    CatalogSnapshot,
    CatalogStateError,
    load_catalog_cache,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    parse_unverified_prepared_record,
)
from paper_data_suite.evergreen_staged_catalog_cli import (
    StagedCatalogCliError,
    _file,
    _ordinary_directory,
)
from paper_data_suite.evergreen_trust_provisioning import (
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)
from paper_data_suite.evergreen_witness_https import (
    ProvisionedHttpsWitnessTransport,
    WitnessHttpsError,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageError,
    WitnessSelectedStageObservation,
    inspect_witness_pinned_selected_staged_bytes,
)

_MAX_CONFIGURATION = 8 * 1024
_MAX_CACHE = 4 * 1024 * 1024
_MAX_POLICY = 24 * 1024
_MAX_PREPARED = 96 * 1024
_MAX_ENVELOPE = 192 * 1024
_MAX_NATIVE = 32 * 1024
_MAX_RECEIPT = 16 * 1024
_MAX_CA = 128 * 1024
_MAX_CERT = 64 * 1024
_MAX_KEY = 64 * 1024
_MAX_MODULES = 32
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_INSTALL = re.compile(r"[0-9a-f]{32}\Z")
_WITNESS = re.compile(r"[a-z][a-z0-9_-]{2,63}\Z")
_FIELDS = frozenset(
    {
        "schema_version",
        "software_root",
        "classroom_workspace",
        "receipt_file",
        "evidence_directory",
        "installation_id",
        "witness_id",
        "witness_origin",
        "witness_ca_file",
        "witness_ca_sha256",
        "client_certificate_file",
        "client_private_key_file",
        "witness_public_key_file",
        "witness_public_key_sha256",
    }
)
_EVIDENCE = frozenset(
    {
        "prepared.json",
        "registry-envelope.json",
        "lock-envelope.json",
        "native-envelope.json",
        "modules",
    }
)


class SelectedWitnessCliError(ValueError):
    """Selected witness diagnostic configuration or observations are unsafe."""


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise SelectedWitnessCliError("duplicate diagnostic configuration field")
        result[name] = value
    return result


def _configuration(raw: bytes) -> dict[str, object]:
    try:
        data: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except SelectedWitnessCliError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise SelectedWitnessCliError(
            "invalid diagnostic configuration JSON"
        ) from error
    if not isinstance(data, dict) or data.keys() != _FIELDS:
        raise SelectedWitnessCliError("unknown or missing diagnostic settings")
    value = cast(dict[str, object], data)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise SelectedWitnessCliError("unsupported diagnostic configuration version")
    return value


def _text(data: dict[str, object], field: str, maximum: int = 512) -> str:
    value = data[field]
    if (
        type(value) is not str
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise SelectedWitnessCliError(f"invalid {field} setting")
    return value


def _path(data: dict[str, object], field: str) -> Path:
    name = _text(data, field)
    value = Path(name)
    if not value.is_absolute() or any(part in (".", "..") for part in value.parts):
        raise SelectedWitnessCliError(f"{field} must be an absolute safe path")
    return value


def _hash(data: dict[str, object], field: str) -> str:
    value = _text(data, field, 64)
    if _SHA.fullmatch(value) is None:
        raise SelectedWitnessCliError(f"invalid independent {field} digest")
    return value


def render_selected_witness_audit(observed: WitnessSelectedStageObservation) -> str:
    """Format transient signed-head and staged-byte observations as diagnostic."""
    if not isinstance(observed, WitnessSelectedStageObservation):
        raise SelectedWitnessCliError("witnessed selected-stage observation required")
    lines = [
        "Paper Data Suite — witnessed selected-stage inspection (diagnostic)",
        "",
        "WITNESSED SELECTION OBSERVED — ACTIVE AUTHORITY NOT ESTABLISHED.",
        "Launch, update, rollback and receipt-write authority: NONE",
        "Signed witness and file observations can change after this inspection.",
        "Operator-provided trust pins require independent provenance.",
        "",
        f"Transaction: {observed.transaction_id}",
        f"Receipt generation: {observed.generation}",
        f"Witness revision: {observed.witness_revision}",
        f"Receipt SHA-256: {observed.receipt_sha256}",
        f"Pip inventory SHA-256: {observed.pip_inventory_sha256}",
        f"Native evidence SHA-256: {observed.native_payload_sha256}",
        "",
        "Publisher-verified selected-stage modules:",
    ]
    for wheel in observed.modules:
        lines.append(f"  {wheel.component_id} ({wheel.distribution}) {wheel.version}")
        lines.append(f"    Wheel SHA-256: {wheel.wheel_sha256}")
    lines.extend(
        (
            "",
            "An explicit external witness query was performed.",
            "No package execution, local write or launch was authorized.",
        )
    )
    return "\n".join(lines) + "\n"


def _read(path: Path, maximum: int, label: str) -> bytes:
    try:
        return _file(path, maximum, label)
    except StagedCatalogCliError as error:
        raise SelectedWitnessCliError(f"unsafe or unavailable {label}") from error


def _directory(path: Path, label: str) -> Path:
    try:
        return _ordinary_directory(path, label)
    except StagedCatalogCliError as error:
        raise SelectedWitnessCliError(f"unsafe or unavailable {label}") from error


def inspect_selected_witness_catalog_evidence(
    *,
    catalog_cache: Path,
    trust_policy: Path,
    pinned_policy_sha256: str,
    configuration: Path,
    now: datetime,
) -> tuple[CatalogSnapshot, WitnessSelectedStageObservation]:
    """Read strict operator config; authenticate and freshly inspect selection.

    Never used implicitly by modules/doctor/launch. This is a deliberately
    networked, read-only diagnostic with no persistence or activation path.
    """
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or type(pinned_policy_sha256) is not str
        or _SHA.fullmatch(pinned_policy_sha256) is None
    ):
        raise SelectedWitnessCliError(
            "aware clock and independent catalog pin required"
        )
    spec = _configuration(_read(configuration, _MAX_CONFIGURATION, "witness config"))
    installation = _text(spec, "installation_id", 32)
    witness = _text(spec, "witness_id", 64)
    if _INSTALL.fullmatch(installation) is None or _WITNESS.fullmatch(witness) is None:
        raise SelectedWitnessCliError("invalid witness/installation identity")
    software = _directory(_path(spec, "software_root"), "software root")
    classroom = _directory(_path(spec, "classroom_workspace"), "classroom workspace")
    evidence = _directory(_path(spec, "evidence_directory"), "evidence directory")
    if {item.name for item in evidence.iterdir()} != _EVIDENCE:
        raise SelectedWitnessCliError("unexpected or missing signed evidence")
    module_dir = _directory(evidence / "modules", "module evidence")
    try:
        policy = _read(trust_policy, _MAX_POLICY, "pinned trust policy")
        _read(catalog_cache, _MAX_CACHE, "signed catalog cache")
        pinned = load_digest_pinned_trust_policy(
            policy, pinned_sha256=pinned_policy_sha256
        )
        snapshot = load_catalog_cache(catalog_cache, trust=pinned.keyring, now=now)
        if snapshot is None:
            raise SelectedWitnessCliError("authenticated catalog cache is absent")
        prepared = _read(evidence / "prepared.json", _MAX_PREPARED, "prepared")
        claim = parse_unverified_prepared_record(prepared)
        registered = {
            canonicalize_name(item.distribution): item.component_id
            for item in snapshot.registry.claims.modules
        }
        selected = {
            registered[canonicalize_name(wheel.distribution)]
            for wheel in claim.wheels
            if canonicalize_name(wheel.distribution) in registered
        }
        if not 1 <= len(selected) <= _MAX_MODULES:
            raise SelectedWitnessCliError("no registered modules in signed stage")
        if {item.name for item in module_dir.iterdir()} != {
            component + ".json" for component in selected
        }:
            raise SelectedWitnessCliError("publisher evidence differs from stage")
        modules = {
            component: _read(
                module_dir / (component + ".json"),
                _MAX_ENVELOPE,
                f"module {component}",
            )
            for component in sorted(selected)
        }
        receipt = _read(_path(spec, "receipt_file"), _MAX_RECEIPT, "receipt")
        pubkey = _read(_path(spec, "witness_public_key_file"), 32, "witness public key")
        if len(pubkey) != 32 or hashlib.sha256(pubkey).hexdigest() != _hash(
            spec, "witness_public_key_sha256"
        ):
            raise SelectedWitnessCliError("witness public key digest mismatch")
        ca = _read(_path(spec, "witness_ca_file"), _MAX_CA, "TLS CA")
        if hashlib.sha256(ca).hexdigest() != _hash(spec, "witness_ca_sha256"):
            raise SelectedWitnessCliError("TLS CA digest mismatch")
        certificate = _path(spec, "client_certificate_file")
        secret = _path(spec, "client_private_key_file")
        _read(certificate, _MAX_CERT, "mTLS client certificate")
        _read(secret, _MAX_KEY, "mTLS private key")
        transport = ProvisionedHttpsWitnessTransport(
            origin=_text(spec, "witness_origin", 255),
            ca_certificate=_path(spec, "witness_ca_file"),
            pinned_ca_sha256=_hash(spec, "witness_ca_sha256"),
            client_certificate=certificate,
            client_key=secret,
        )
        observed = inspect_witness_pinned_selected_staged_bytes(
            snapshot,
            software,
            classroom_workspace=classroom,
            receipt_bytes=receipt,
            installation_id=installation,
            expected_witness_id=witness,
            witness_transport=transport,
            pinned_witness_public_key=pubkey,
            prepared_record=prepared,
            registry_envelope=_read(
                evidence / "registry-envelope.json", _MAX_ENVELOPE, "registry"
            ),
            lock_envelope=_read(evidence / "lock-envelope.json", _MAX_ENVELOPE, "lock"),
            module_envelopes=modules,
            native_envelope=_read(
                evidence / "native-envelope.json", _MAX_NATIVE, "native"
            ),
            trust=pinned.keyring,
            now=now,
        )
        return snapshot, observed
    except SelectedWitnessCliError:
        raise
    except (
        CatalogStateError,
        PreparedRecordError,
        StagedCatalogCliError,
        TrustProvisioningError,
        WitnessHttpsError,
        WitnessSelectedStageError,
        OSError,
        ValueError,
    ) as error:
        raise SelectedWitnessCliError(
            "signed witness or physical selected-stage verification refused"
        ) from error


def inspect_selected_witness_catalog_audit(
    *,
    catalog_cache: Path,
    trust_policy: Path,
    pinned_policy_sha256: str,
    configuration: Path,
    now: datetime,
) -> str:
    """Keep the existing public diagnostic output/API unchanged (Slice 63)."""
    _, observed = inspect_selected_witness_catalog_evidence(
        catalog_cache=catalog_cache,
        trust_policy=trust_policy,
        pinned_policy_sha256=pinned_policy_sha256,
        configuration=configuration,
        now=now,
    )
    return render_selected_witness_audit(observed)


__all__ = (
    "SelectedWitnessCliError",
    "inspect_selected_witness_catalog_audit",
    "inspect_selected_witness_catalog_evidence",
    "render_selected_witness_audit",
)
