"""Issue #49: read-only, narrow audit of pip-style staged virtualenv files.

Only wheel root/purelib/platlib relocation and the exact pip INSTALLER and
REQUESTED files are understood. This is a byte observation, never installation
or launch authority. In particular it does not allow generated scripts, data,
compiled bytecode, native-file provenance, or a mutable receipt to grant trust.
"""

from __future__ import annotations

import hashlib
import stat
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Final

from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    verify_prepared_record_against_wheelhouse,
)
from paper_data_suite.evergreen_pip_direct_url import (
    PipDirectUrlError,
    inspect_locked_pip_direct_url,
)
from paper_data_suite.evergreen_pip_script_records import (
    PipScriptRecordError,
    split_pip_record,
)
from paper_data_suite.evergreen_staged_install import (
    StageAuditError,
    _safe_relative,
    _sha_file,
    _walk_stage,
)
from paper_data_suite.evergreen_staged_runtime import (
    StagedRuntimeError,
    _directories_from,
    inspect_staged_virtualenv,
)

_MAX_MEMBER: Final = 512 * 1024 * 1024
_MAX_FILES: Final = 30000
_MAX_WHEEL: Final = 512 * 1024 * 1024
_MAX_RECORD: Final = 2 * 1024 * 1024


class PipLayoutError(ValueError):
    """Authenticated wheel payload and staged pip-layout contents disagree."""


@dataclass(frozen=True, slots=True)
class ObservedPipFile:
    relative_path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class StagedPipLayoutAudit:
    """Read-only, one-time observation; no active receipt or launch permission."""

    transaction_id: str
    site_packages: Path
    distributions: tuple[str, ...]
    relocated_files: tuple[str, ...]
    generated_metadata: tuple[str, ...]
    files: tuple[ObservedPipFile, ...]
    inventory_sha256: str
    launcher_records: tuple[ObservedPipFile, ...] = ()


def _stream_hash(stream: IO[bytes], limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise PipLayoutError("source wheel or member exceeds audit size bound")
        digest.update(chunk)
    return digest.hexdigest(), size


def _expected(
    wheelhouse: Path,
    wheels: tuple[tuple[str, str, str], ...],
    *,
    windows: bool,
) -> tuple[
    dict[str, tuple[str, int]],
    dict[str, set[str]],
    dict[str, set[str]],
    tuple[str, ...],
    dict[str, str],
]:
    expected: dict[str, tuple[str, int]] = {}
    owned_by_record: dict[str, set[str]] = {}
    generated_by_record: dict[str, set[str]] = {}
    relocated: list[str] = []
    record_owners: dict[str, str] = {}
    collisions: set[str] = set()
    for filename, pin, distribution in wheels:
        path = wheelhouse / filename
        try:
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise PipLayoutError("unsafe wheelhouse source file")
            with path.open("rb") as source:
                digest, length = _stream_hash(source, _MAX_WHEEL)
                if digest != pin:
                    raise PipLayoutError("wheel changed after signed lock verification")
                source.seek(0)
                with zipfile.ZipFile(source) as archive:
                    files = [item for item in archive.infolist() if not item.is_dir()]
                    records = [
                        item.filename
                        for item in files
                        if item.filename.endswith(".dist-info/RECORD")
                    ]
                    if len(records) != 1 or len(files) > _MAX_FILES:
                        raise PipLayoutError("wheel has invalid RECORD or file count")
                    record_path = records[0]
                    dist_folder = record_path.split("/", 1)[0]
                    if record_path != f"{dist_folder}/RECORD":
                        raise PipLayoutError("nonstandard wheel RECORD path")
                    data_folder = dist_folder.removesuffix(".dist-info") + ".data"
                    owned: set[str] = set()
                    extras: set[str] = set()
                    for member in files:
                        name = member.filename
                        _safe_relative(name)
                        if member.orig_filename != name:
                            raise PipLayoutError("noncanonical source member")
                        destination = name
                        if name.startswith(data_folder + "/"):
                            parts = name[len(data_folder) + 1 :].split("/", 1)
                            if len(parts) != 2 or parts[0] not in {
                                "purelib",
                                "platlib",
                            }:
                                raise PipLayoutError("unsupported wheel .data scheme")
                            destination = parts[1]
                            _safe_relative(destination)
                            relocated.append(destination)
                        elif ".data/" in name:
                            raise PipLayoutError("foreign wheel .data scheme")
                        key = destination.casefold() if windows else destination
                        if key in collisions:
                            raise PipLayoutError("wheel installation path collision")
                        collisions.add(key)
                        if destination == record_path:
                            expected[destination] = ("", -1)
                        else:
                            with archive.open(member) as member_stream:
                                file_hash, file_size = _stream_hash(
                                    member_stream, _MAX_MEMBER
                                )
                            if file_size != member.file_size:
                                raise PipLayoutError("wheel member length mismatch")
                            expected[destination] = (file_hash, file_size)
                        owned.add(destination)
                    if record_path not in owned:
                        raise PipLayoutError("wheel RECORD missing after mapping")
                    for extra, data in (("INSTALLER", b"pip\n"), ("REQUESTED", b"")):
                        destination = f"{dist_folder}/{extra}"
                        key = destination.casefold() if windows else destination
                        if key in collisions:
                            raise PipLayoutError(
                                "installer metadata collides with wheel"
                            )
                        collisions.add(key)
                        expected[destination] = (
                            hashlib.sha256(data).hexdigest(),
                            len(data),
                        )
                        extras.add(destination)
                    owned_by_record[record_path] = owned
                    record_owners[record_path] = distribution
                    generated_by_record[record_path] = extras
                source.seek(0)
                second, second_size = _stream_hash(source, _MAX_WHEEL)
                if (second, second_size) != (pin, length):
                    raise PipLayoutError("source wheel changed during audit")
        except (OSError, RuntimeError, zipfile.BadZipFile, StageAuditError) as error:
            raise PipLayoutError("source wheel layout cannot be audited") from error
    if len(expected) > _MAX_FILES:
        raise PipLayoutError("combined installed file count exceeds audit bound")
    return (
        expected,
        owned_by_record,
        generated_by_record,
        tuple(sorted(relocated)),
        record_owners,
    )


def audit_staged_pip_layout(
    stage_root: Path,
    wheelhouse: Path,
    *,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
    require_launcher_records: bool = False,
) -> StagedPipLayoutAudit:
    """Authenticate files in an isolated pip-style virtualenv, without execution.

    Generated INSTALLER/REQUESTED are permitted only when they exactly match
    the expected pip forms and are explicitly listed in installed RECORD.
    ``RECORD`` is intentionally installer-generated and verified against every
    expected installed file instead of compared with the source wheel RECORD.
    """
    try:
        stage = inspect_staged_virtualenv(
            stage_root,
            wheelhouse,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            trust=trust,
            now=now,
            checkpoint=checkpoint,
            layout=layout,
        )
        record = verify_prepared_record_against_wheelhouse(
            prepared_record,
            wheelhouse,
            lock_envelope=lock_envelope,
            registry_envelope=registry_envelope,
            trust=trust,
            now=now,
            checkpoint=checkpoint,
        )
        _directories_from(stage.stage_root, stage.site_packages)
        installed = _walk_stage(stage.site_packages)
        windows = layout == "windows" or (layout is None and sys.platform == "win32")
        expected, owners, generated, relocated, record_owners = _expected(
            wheelhouse,
            tuple(
                (wheel.filename, wheel.sha256, wheel.distribution)
                for wheel in record.wheels
            ),
            windows=windows,
        )
        # A PEP 610 direct URL is installer metadata, not wheel authority.
        # It is accepted only for the exact authenticated local wheel path.
        wheel_pins = {wheel.distribution: wheel for wheel in record.wheels}
        for record_path, distribution in record_owners.items():
            metadata_name = record_path.rsplit("/", 1)[0] + "/direct_url.json"
            if metadata_name not in installed:
                continue
            wheel = wheel_pins[distribution]
            metadata_file = installed[metadata_name]
            with metadata_file.open("rb") as stream:
                raw = stream.read(4097)
            digest, size = inspect_locked_pip_direct_url(
                raw,
                wheel_path=wheelhouse / wheel.filename,
                wheel_sha256=wheel.sha256,
            )
            if metadata_name in expected:
                raise PipLayoutError("pip direct URL collides with wheel payload")
            expected[metadata_name] = (digest, size)
            generated[record_path].add(metadata_name)
        # A pip installation may omit REQUESTED for transitive wheels.
        # INSTALLER is optional on externally created but otherwise exact stages.
        optional: set[str] = set().union(*generated.values())
        if not (set(expected) - optional) <= set(installed):
            raise PipLayoutError("installed wheel payload is incomplete")
        if not set(installed) <= set(expected):
            raise PipLayoutError("unexpected installed file outside signed wheels")
        generated_present = optional & set(installed)
        actual: dict[str, ObservedPipFile] = {}
        for name, path in installed.items():
            digest, size = _sha_file(path)
            if (
                name in expected
                and (digest, size) != expected[name]
                and name not in owners
            ):
                raise PipLayoutError("installed file differs from authenticated wheel")
            actual[name] = ObservedPipFile(name, digest, size)
        if type(require_launcher_records) is not bool:
            raise PipLayoutError("invalid launcher RECORD policy")
        stage_relative_site = stage.site_packages.relative_to(stage.stage_root)
        parent_prefix = "../" * len(stage_relative_site.parts)
        launchers_by_owner: dict[str, dict[str, Path]] = {}
        for launcher in stage.console_launchers:
            script_path = (
                parent_prefix + launcher.path.relative_to(stage.stage_root).as_posix()
            )
            launchers_by_owner.setdefault(launcher.owner, {})[script_path] = (
                launcher.path
            )
        script_observed: dict[str, ObservedPipFile] = {}
        for record_path, owned in owners.items():
            with installed[record_path].open("rb") as stream:
                raw = stream.read(_MAX_RECORD + 1)
            if len(raw) > _MAX_RECORD:
                raise PipLayoutError("installed RECORD exceeds audit size bound")
            approved_scripts = launchers_by_owner.get(record_owners[record_path], {})
            try:
                rows, script_rows = split_pip_record(
                    raw, allowed_scripts=frozenset(approved_scripts)
                )
            except PipScriptRecordError as error:
                raise PipLayoutError("unsafe installed pip launcher RECORD") from error
            if script_rows and set(script_rows) != set(approved_scripts):
                raise PipLayoutError("installed launcher RECORD is incomplete")
            if require_launcher_records and set(script_rows) != set(approved_scripts):
                raise PipLayoutError("required launcher RECORD entries missing")
            for script_name, pair in script_rows.items():
                if _sha_file(approved_scripts[script_name]) != pair:
                    raise PipLayoutError("installed console RECORD digest mismatch")
                if script_name in script_observed:
                    raise PipLayoutError("multiple wheels claim the same launcher")
                script_observed[script_name] = ObservedPipFile(
                    script_name, pair[0], pair[1]
                )
            allowed = owned | (generated[record_path] & generated_present)
            if set(rows) != allowed:
                raise PipLayoutError("installed RECORD does not enumerate exact files")
            for name in allowed:
                expected_row = (
                    ("", -1)
                    if name == record_path
                    else (actual[name].sha256, actual[name].size)
                )
                if rows[name] != expected_row:
                    raise PipLayoutError("installed RECORD digest or size mismatch")
        inventory = hashlib.sha256()
        for name in sorted(actual):
            item = actual[name]
            inventory.update(f"{name}\0{item.sha256}\0{item.size}\n".encode("utf-8"))
        for name in sorted(script_observed):
            item = script_observed[name]
            inventory.update(
                f"script:{name}\0{item.sha256}\0{item.size}\n".encode("utf-8")
            )
        return StagedPipLayoutAudit(
            record.transaction_id,
            stage.site_packages,
            tuple(w.distribution for w in record.wheels),
            relocated,
            tuple(sorted(generated_present)),
            tuple(actual[name] for name in sorted(actual)),
            inventory.hexdigest(),
            tuple(script_observed[name] for name in sorted(script_observed)),
        )
    except PipLayoutError:
        raise
    except (
        StageAuditError,
        StagedRuntimeError,
        PreparedRecordError,
        PipDirectUrlError,
        ValueError,
        OSError,
        KeyError,
    ) as error:
        raise PipLayoutError("staged pip layout preflight failed") from error


__all__ = (
    "ObservedPipFile",
    "PipLayoutError",
    "StagedPipLayoutAudit",
    "audit_staged_pip_layout",
)
