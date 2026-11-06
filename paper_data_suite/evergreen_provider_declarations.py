"""Issue #49: authenticated, metadata-only Core provider declaration observation.

An installed entry point is a declaration, not proof that loading the provider
is safe or that its interface works. Never imports, executes, activates or
reads the classroom workspace. This API cannot grant launch permissions.
"""

from __future__ import annotations

import configparser
import hashlib
import re
import stat
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
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
    parse_unverified_prepared_record,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    PublisherPipPreflightError,
    audit_publisher_bound_pip_candidate,
)

_PROVIDER_GROUPS: Final = frozenset(
    {
        "paper_data_suite.modules",
        "paper_data_suite.module_operations",
        "paper_data_suite.publication_producers",
    }
)
_ID: Final = re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
_TARGET: Final = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z"
)
_MAX_METADATA: Final = 32 * 1024
_MAX_WHEEL: Final = 512 * 1024 * 1024
_REPARSE: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class ProviderDeclarationError(ValueError):
    """A provider declaration is unsupported, ambiguous or unauthenticated."""


class DeclarationStatus(str, Enum):
    """Only a signed-wheel metadata observation, not provider readiness."""

    DECLARED_NOT_TESTED = "declared_not_tested"
    NOT_DECLARED = "not_declared"


@dataclass(frozen=True, slots=True)
class ObservedProviderDeclaration:
    """Publisher-bound installed provider entry point with no execution right."""

    transaction_id: str
    component_id: str
    group: str
    status: DeclarationStatus
    target: str | None
    wheel_sha256: str
    publisher_payload_sha256: str
    pip_inventory_sha256: str
    entry_points_sha256: str


class _ExactConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _declaration(
    raw: bytes,
    *,
    component_id: str,
    group: str,
    wheel_members: frozenset[str],
) -> tuple[DeclarationStatus, str | None]:
    """Reject ambiguous or foreign providers; do not import any target."""
    if not raw or len(raw) > _MAX_METADATA:
        raise ProviderDeclarationError("invalid entry point metadata length")
    try:
        parser = _ExactConfigParser(interpolation=None, strict=True)
        parser.read_string(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, configparser.Error) as error:
        raise ProviderDeclarationError("malformed entry point metadata") from error
    if parser.defaults():
        raise ProviderDeclarationError("entry point defaults are unsupported")
    if not parser.has_section(group):
        return DeclarationStatus.NOT_DECLARED, None
    candidates = dict(parser.items(group, raw=True))
    if not candidates:
        raise ProviderDeclarationError("empty declared provider group")
    if set(candidates) != {component_id}:
        raise ProviderDeclarationError("provider name differs from registered module")
    target = candidates[component_id].strip()
    if not _TARGET.fullmatch(target):
        raise ProviderDeclarationError("unsafe public provider entry point target")
    module_name, _ = target.split(":", 1)
    source = module_name.replace(".", "/")
    if (
        f"{source}.py" not in wheel_members
        and f"{source}/__init__.py" not in wheel_members
    ):
        raise ProviderDeclarationError("provider target is absent from signed wheel")
    return DeclarationStatus.DECLARED_NOT_TESTED, target


def _wheel_content(
    wheel_path: Path,
    *,
    expected_sha256: str,
) -> tuple[str, bytes, frozenset[str]]:
    """Rehash an already independently authenticated wheel around metadata read."""
    try:
        info = wheel_path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_size < 1
            or info.st_size > _MAX_WHEEL
            or bool(getattr(info, "st_file_attributes", 0) & _REPARSE)
        ):
            raise ProviderDeclarationError("unsafe provider wheel path")
        with wheel_path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected_sha256:
            raise ProviderDeclarationError("provider wheel changed after verification")
        with zipfile.ZipFile(wheel_path) as archive:
            names = archive.namelist()
            matched = [
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            ]
            if len(matched) != 1 or len(set(names)) != len(names):
                raise ProviderDeclarationError("ambiguous provider wheel metadata")
            name = matched[0]
            if archive.getinfo(name).file_size > _MAX_METADATA:
                raise ProviderDeclarationError("oversized provider entry points")
            raw = archive.read(name)
            if len(raw) > _MAX_METADATA:
                raise ProviderDeclarationError("oversized provider entry points")
        with wheel_path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha256:
                raise ProviderDeclarationError(
                    "provider wheel changed during inspection"
                )
        return name, raw, frozenset(names)
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as error:
        raise ProviderDeclarationError("provider wheel metadata unavailable") from error


def inspect_authenticated_provider_declaration(
    stage_root: Path,
    wheelhouse: Path,
    *,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    component_id: str,
    group: str,
    trust: TrustedKeyring,
    now: datetime,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> ObservedProviderDeclaration:
    """Observe one named public provider after full publisher/pip verification.

    Missing group means NOT_DECLARED (not necessarily a defect). Present group
    means DECLARED_NOT_TESTED; the public Core contract must still be probed
    and qualified separately. The calling authority chooses the named scope.
    """
    if (
        type(component_id) is not str
        or not _ID.fullmatch(component_id)
        or type(group) is not str
        or group not in _PROVIDER_GROUPS
    ):
        raise ProviderDeclarationError("unknown registered provider scope")
    try:
        before = audit_publisher_bound_pip_candidate(
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
        registry = verify_registry_document(
            registry_envelope,
            trust=trust,
            now=now,
            checkpoint=registry_checkpoint,
        )
        prepared = parse_unverified_prepared_record(prepared_record)
        registered = {item.component_id: item for item in registry.claims.modules}
        if component_id not in registered:
            raise ProviderDeclarationError("unknown registered provider component")
        distribution = canonicalize_name(registered[component_id].distribution)
        selected = {
            canonicalize_name(wheel.distribution): wheel for wheel in prepared.wheels
        }
        publisher_digests = dict(before.publisher_digests)
        if distribution not in selected or component_id not in publisher_digests:
            raise ProviderDeclarationError("provider distribution is not authenticated")
        wheel = selected[distribution]
        metadata_path, raw, members = _wheel_content(
            wheelhouse / wheel.filename, expected_sha256=wheel.sha256
        )
        windows = layout == "windows" or (layout is None and sys.platform == "win32")
        site_name = (
            "Lib/site-packages"
            if windows
            else (
                f"lib/python{sys.version_info.major}."
                f"{sys.version_info.minor}/site-packages"
            )
        )
        prefix = before.stage_root / site_name
        installed = prefix / metadata_path
        if installed.is_symlink() or not installed.is_file():
            raise ProviderDeclarationError("installed provider metadata is unsafe")
        if installed.read_bytes() != raw:
            raise ProviderDeclarationError("installed provider metadata differs")
        status, target = _declaration(
            raw, component_id=component_id, group=group, wheel_members=members
        )
        after = audit_publisher_bound_pip_candidate(
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
        if before != after:
            raise ProviderDeclarationError("provider software changed during audit")
        return ObservedProviderDeclaration(
            before.transaction_id,
            component_id,
            group,
            status,
            target,
            wheel.sha256,
            publisher_digests[component_id],
            before.pip_inventory_sha256,
            hashlib.sha256(raw).hexdigest(),
        )
    except (
        PublisherPipPreflightError,
        CatalogVerificationError,
        PreparedRecordError,
        OSError,
    ) as error:
        raise ProviderDeclarationError(
            "publisher-bound provider declaration audit failed"
        ) from error


__all__ = (
    "DeclarationStatus",
    "ObservedProviderDeclaration",
    "ProviderDeclarationError",
    "inspect_authenticated_provider_declaration",
)
