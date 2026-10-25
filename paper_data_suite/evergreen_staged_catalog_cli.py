"""Issue #49 Slice 61: explicit CLI adapter for signed staged-candidate evidence.

A read-only, offline diagnostic, never installed-state, activation or launch
approval. Trust-policy SHA-256 must be pinned by a separate trusted channel;
command-line arguments alone do not establish its provenance.
"""

from __future__ import annotations

import stat
from datetime import datetime
from pathlib import Path

from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_catalog_preview import _read_regular
from paper_data_suite.evergreen_catalog_stage_correlation import (
    CatalogStageCorrelation,
    CatalogStageCorrelationError,
    inspect_catalog_bound_staged_bytes,
)
from paper_data_suite.evergreen_catalog_state import (
    CatalogStateError,
    load_catalog_cache,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    parse_unverified_prepared_record,
)
from paper_data_suite.evergreen_trust_provisioning import (
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)

_MAX_CACHE = 4 * 1024 * 1024
_MAX_POLICY = 24 * 1024
_MAX_PREPARED = 96 * 1024
_MAX_ENVELOPE = 192 * 1024
_MAX_NATIVE = 32 * 1024
_MAX_MODULES = 32
_EVIDENCE_NAMES = frozenset(
    {
        "prepared.json",
        "registry-envelope.json",
        "lock-envelope.json",
        "native-envelope.json",
        "modules",
    }
)


class StagedCatalogCliError(ValueError):
    """Diagnostic evidence could not be authenticated or safely read."""


def _ordinary_directory(path: Path, label: str) -> Path:
    """Require an existing directory with no symlink or Windows reparse ancestors."""
    if not isinstance(path, Path):
        raise StagedCatalogCliError(f"{label} must be a filesystem Path")
    target = path.absolute()
    try:
        for member in (target, *target.parents):
            metadata = member.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & 0x400
            ):
                raise StagedCatalogCliError(f"unsafe {label} directory")
    except OSError as error:
        raise StagedCatalogCliError(f"unavailable {label} directory") from error
    return target


def _file(path: Path, limit: int, name: str) -> bytes:
    try:
        return _read_regular(path, limit, name)
    except (ValueError, OSError) as error:
        raise StagedCatalogCliError(f"unsafe or unreadable {name}") from error


def render_staged_catalog_audit(finding: CatalogStageCorrelation) -> str:
    """Explicitly label transient staged candidate evidence as NOT ACTIVE."""
    if not isinstance(finding, CatalogStageCorrelation):
        raise StagedCatalogCliError("authenticated staged correlation required")
    lines = [
        "Paper Data Suite — authenticated staged candidate audit (diagnostic)",
        "",
        "STAGED CANDIDATE ONLY — NOT ACTIVE OR APPROVED FOR LAUNCH.",
        "Installed/active composition: NOT ESTABLISHED",
        "Launch, update and activation authority: NONE",
        "Independent trust-policy pin provenance must be verified externally.",
        "",
        f"Transaction: {finding.transaction_id}",
        f"Registry SHA-256: {finding.registry_payload_sha256}",
        f"Pip file inventory SHA-256: {finding.pip_inventory_sha256}",
        f"Native evidence SHA-256: {finding.native_payload_sha256}",
        "",
        "Authenticated staged module wheel observations:",
    ]
    for wheel in finding.modules:
        lines.append(f"  {wheel.component_id} ({wheel.distribution}) {wheel.version}")
        lines.append(f"    Wheel SHA-256: {wheel.wheel_sha256}")
    lines.extend(
        (
            "",
            "Observation is non-atomic; files may change after inspection.",
            "No network access, package execution, activation or write was performed.",
        )
    )
    return "\n".join(lines) + "\n"


def inspect_offline_staged_catalog_audit(
    *,
    catalog_cache: Path,
    trust_policy: Path,
    pinned_policy_sha256: str,
    evidence_directory: Path,
    stage_root: Path,
    wheelhouse: Path,
    now: datetime,
) -> str:
    """Reverify signed release cache then fully audit a supplied pip/native stage.

    The evidence directory has exactly four fixed files and a ``modules/``
    directory with one ``<component_id>.json`` per selected PDS publisher.
    No filename or trust authority is taken from a package's local metadata.
    """
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or type(pinned_policy_sha256) is not str
        or len(pinned_policy_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in pinned_policy_sha256)
    ):
        raise StagedCatalogCliError("aware clock and independent SHA-256 pin required")
    root = _ordinary_directory(evidence_directory, "evidence")
    _ordinary_directory(stage_root, "staged root")
    _ordinary_directory(wheelhouse, "wheelhouse")
    try:
        if {part.name for part in root.iterdir()} != _EVIDENCE_NAMES:
            raise StagedCatalogCliError(
                "unexpected or missing evidence directory entry"
            )
        module_dir = _ordinary_directory(root / "modules", "module evidence")
        policy = _file(trust_policy, _MAX_POLICY, "pinned trust policy")
        _file(catalog_cache, _MAX_CACHE, "signed catalog cache")
        pinned = load_digest_pinned_trust_policy(
            policy, pinned_sha256=pinned_policy_sha256
        )
        snapshot = load_catalog_cache(catalog_cache, trust=pinned.keyring, now=now)
        if snapshot is None:
            raise StagedCatalogCliError("authenticated catalog cache is absent")
        prepared_bytes = _file(root / "prepared.json", _MAX_PREPARED, "prepared")
        prepared = parse_unverified_prepared_record(prepared_bytes)
        registered = {
            canonicalize_name(item.distribution): item.component_id
            for item in snapshot.registry.claims.modules
        }
        selected = {
            registered[canonicalize_name(wheel.distribution)]
            for wheel in prepared.wheels
            if canonicalize_name(wheel.distribution) in registered
        }
        if not 1 <= len(selected) <= _MAX_MODULES:
            raise StagedCatalogCliError("no selected authenticated PDS publisher")
        expected = {component + ".json" for component in selected}
        if {part.name for part in module_dir.iterdir()} != expected:
            raise StagedCatalogCliError(
                "module evidence files differ from selected PDS roots"
            )
        modules = {
            component: _file(
                module_dir / (component + ".json"),
                _MAX_ENVELOPE,
                f"module {component}",
            )
            for component in sorted(selected)
        }
        finding = inspect_catalog_bound_staged_bytes(
            snapshot,
            stage_root,
            wheelhouse,
            prepared_record=prepared_bytes,
            registry_envelope=_file(
                root / "registry-envelope.json", _MAX_ENVELOPE, "registry"
            ),
            lock_envelope=_file(root / "lock-envelope.json", _MAX_ENVELOPE, "lock"),
            module_envelopes=modules,
            native_envelope=_file(root / "native-envelope.json", _MAX_NATIVE, "native"),
            trust=pinned.keyring,
            now=now,
        )
        return render_staged_catalog_audit(finding)
    except (
        CatalogStateError,
        CatalogStageCorrelationError,
        PreparedRecordError,
        TrustProvisioningError,
        OSError,
    ) as error:
        raise StagedCatalogCliError(
            "signed staged candidate evidence could not be verified"
        ) from error


__all__ = (
    "StagedCatalogCliError",
    "inspect_offline_staged_catalog_audit",
    "render_staged_catalog_audit",
)
