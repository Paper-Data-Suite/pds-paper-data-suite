"""Issue #49: non-executing staged virtualenv and console-wrapper inspection.

This is diagnostic metadata evidence, NEVER executable authorization. Signed
wheel provenance is rechecked, but neither native .exe stubs nor the staged
interpreter are authenticated. No subprocess, import, activation or installation.
"""

from __future__ import annotations

import ast
import base64
import configparser
import csv
import hashlib
import io
import re
import stat
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Final

from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    verify_prepared_record_against_wheelhouse,
)

_MAX_METADATA: Final = 256 * 1024
_MAX_WRAPPER: Final = 24 * 1024
_MAX_SCRIPT: Final = 16 * 1024 * 1024
_MAX_RECORD: Final = 2 * 1024 * 1024
_MAX_CFG: Final = 24 * 1024
_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
_DOTTED: Final = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*\Z")
_SCRIPT: Final = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,79}\Z")


class StagedRuntimeError(ValueError):
    """A staged virtualenv has incomplete, unsafe or mismatched runtime metadata."""


class _CaseSensitiveParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


@dataclass(frozen=True, slots=True)
class ObservedConsoleLauncher:
    """A matching wrapper; the native binary itself is UNAUTHENTICATED."""

    owner: str
    name: str
    target: str
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class StagedRuntimeInspection:
    """Metadata-only staged evidence; cannot be converted to launch permission."""

    transaction_id: str
    stage_root: Path
    site_packages: Path
    distributions: tuple[str, ...]
    console_launchers: tuple[ObservedConsoleLauncher, ...]
    native_executables_authenticated: bool = False


def _ordinary(path: Path, *, directory: bool) -> None:
    try:
        details = path.lstat()
    except OSError as error:
        raise StagedRuntimeError("missing staged path") from error
    flags = getattr(details, "st_file_attributes", 0)
    if (flags & 0x400) or stat.S_ISLNK(details.st_mode):
        raise StagedRuntimeError("staged path uses a reparse point")
    okay = stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(details.st_mode)
    if not okay:
        raise StagedRuntimeError("staged path has the wrong file type")


def _directories_from(root: Path, leaf: Path) -> None:
    """Check every path element between an owned staging root and one directory."""
    try:
        steps = leaf.relative_to(root).parts
    except ValueError as error:
        raise StagedRuntimeError("staged directory escapes root") from error
    here = root
    _ordinary(here, directory=True)
    for part in steps:
        here = here / part
        _ordinary(here, directory=True)


def _limited(path: Path, limit: int) -> bytes:
    _ordinary(path, directory=False)
    try:
        with path.open("rb") as handle:
            result = handle.read(limit + 1)
    except OSError as error:
        raise StagedRuntimeError("staged metadata could not be read") from error
    if len(result) > limit:
        raise StagedRuntimeError("staged metadata exceeds safety limit")
    return result


def _sha(path: Path, limit: int) -> tuple[str, int]:
    _ordinary(path, directory=False)
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise StagedRuntimeError("staged executable exceeds safety limit")
            digest.update(chunk)
    return digest.hexdigest(), total


def _config(path: Path) -> None:
    try:
        contents = _limited(path, _MAX_CFG).decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise StagedRuntimeError("invalid virtualenv configuration") from error
    found: dict[str, str] = {}
    for line in contents.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise StagedRuntimeError("invalid virtualenv configuration")
        key, value = (part.strip() for part in line.split("=", 1))
        key = key.lower()
        if not key or key in found:
            raise StagedRuntimeError("duplicate or invalid virtualenv setting")
        found[key] = value
    if found.get("include-system-site-packages", "").lower() != "false":
        raise StagedRuntimeError("staged virtualenv has system packages enabled")


def _entries(archive: zipfile.ZipFile) -> tuple[str, bytes, bytes, bytes | None]:
    names = archive.namelist()
    info = archive.infolist()
    if len(info) > 20000 or len(names) != len(set(names)):
        raise StagedRuntimeError("unsafe source wheel members")
    if any(x.orig_filename != x.filename or "\\" in x.orig_filename for x in info):
        raise StagedRuntimeError("normalized source wheel member name")
    prefixes = {
        name.split("/")[0] for name in names if name.endswith(".dist-info/METADATA")
    }
    if len(prefixes) != 1:
        raise StagedRuntimeError("source wheel metadata directory ambiguous")
    prefix = next(iter(prefixes))
    if not prefix.endswith(".dist-info"):
        raise StagedRuntimeError("invalid source wheel metadata prefix")
    paths = (f"{prefix}/METADATA", f"{prefix}/WHEEL")
    entry_path = f"{prefix}/entry_points.txt"
    for name in (*paths, entry_path):
        if name in names and archive.getinfo(name).file_size > _MAX_METADATA:
            raise StagedRuntimeError("source wheel metadata oversized")
    metadata = archive.read(paths[0])
    wheel = archive.read(paths[1])
    entries = archive.read(entry_path) if entry_path in names else None
    return prefix, metadata, wheel, entries


def _console(entries: bytes | None) -> tuple[tuple[str, str], ...]:
    if entries is None:
        return ()
    try:
        parser = _CaseSensitiveParser(interpolation=None, strict=True)
        parser.read_string(entries.decode("utf-8"))
        if not parser.has_section("console_scripts"):
            return ()
        output = tuple(parser.items("console_scripts"))
    except (configparser.Error, UnicodeDecodeError) as error:
        raise StagedRuntimeError("invalid signed wheel entry point metadata") from error
    if len(output) > 64:
        raise StagedRuntimeError("too many console entry points")
    for name, target in output:
        parts = target.split(":")
        if (
            not _SCRIPT.fullmatch(name)
            or len(parts) != 2
            or not _DOTTED.fullmatch(parts[0])
            or not _NAME.fullmatch(parts[1])
        ):
            raise StagedRuntimeError("unsupported console entry point target")
    return output


def _expected_wrapper(target: str) -> str:
    module, function = target.split(":", 1)
    return (
        "import re\nimport sys\n"
        f"from {module} import {function}\n"
        "if __name__ == '__main__':\n"
        "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
        f"    sys.exit({function}())\n"
    )


def _expected_windows_pip_wrapper(target: str) -> str:
    """Exact distlib template observed in real modern Windows pip launchers."""
    module, function = target.split(":", 1)
    return (
        "import sys\n"
        f"from {module} import {function}\n"
        "if __name__ == '__main__':\n"
        "    sys.argv[0] = sys.argv[0].removesuffix('.exe')\n"
        f"    sys.exit({function}())\n"
    )


def _safe_wrapper(raw: bytes, target: str, *, windows: bool) -> None:
    if len(raw) > _MAX_WRAPPER:
        raise StagedRuntimeError("generated console wrapper exceeds size limit")
    try:
        current = ast.parse(raw.decode("utf-8-sig"))
        expected = [ast.parse(_expected_wrapper(target))]
        if windows:
            expected.append(ast.parse(_expected_windows_pip_wrapper(target)))
    except (SyntaxError, UnicodeDecodeError, ValueError) as error:
        raise StagedRuntimeError("invalid generated console wrapper") from error
    observed_tree = ast.dump(current, include_attributes=False)
    if not any(
        observed_tree == ast.dump(approved, include_attributes=False)
        for approved in expected
    ):
        raise StagedRuntimeError("console wrapper does not match expected target")


def _wrapper(path: Path, target: str, *, windows: bool) -> str:
    digest, _ = _sha(path, _MAX_SCRIPT)
    if windows:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise StagedRuntimeError("Windows console launcher lacks MZ header")
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.namelist() != ["__main__.py"]:
                    raise StagedRuntimeError("unexpected embedded launcher members")
                raw = archive.read("__main__.py")
        except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as error:
            raise StagedRuntimeError(
                "console launcher is not an embedded ZIP"
            ) from error
    else:
        raw = _limited(path, _MAX_WRAPPER)
        if not raw.startswith(b"#!"):
            raise StagedRuntimeError("POSIX console launcher lacks shebang")
    _safe_wrapper(raw, target, windows=windows)
    return digest


def _hash_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _record_matches(path: Path, relative: str, digest: str, size: int) -> None:
    """Check the installed RECORD entry, never use RECORD as its own authority."""
    try:
        reader = csv.reader(io.StringIO(_limited(path, _MAX_RECORD).decode("utf-8")))
        rows = [row for row in reader if row and row[0] == relative]
    except (UnicodeDecodeError, csv.Error) as error:
        raise StagedRuntimeError("invalid installed RECORD") from error
    if len(rows) != 1 or len(rows[0]) != 3:
        raise StagedRuntimeError("installed RECORD omits or duplicates critical file")
    _, encoded, reported_size = rows[0]
    expected = "sha256=" + base64.urlsafe_b64encode(bytes.fromhex(digest)).decode(
        "ascii"
    ).rstrip("=")
    if encoded != expected or reported_size != str(size):
        raise StagedRuntimeError("installed RECORD differs from critical file")


def inspect_staged_virtualenv(
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
) -> StagedRuntimeInspection:
    """Observe isolated venv metadata and generated wrappers without executing.

    `layout` is for testing both supported layouts; it never changes the
    already-verified host-specific wheel lock and cannot authorize launching.
    The native interpreter/Windows EXE executable code remains UNAUTHENTICATED.
    """
    if not isinstance(stage_root, Path) or not isinstance(wheelhouse, Path):
        raise StagedRuntimeError("stage paths must be Path")
    root = stage_root.absolute()
    _ordinary(root, directory=True)
    running = (Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())
    resolved = root.resolve()
    if any(
        resolved == p or p.is_relative_to(resolved) or resolved.is_relative_to(p)
        for p in running
    ):
        raise StagedRuntimeError("cannot inspect running interpreter as stage")
    windows = (sys.platform == "win32") if layout is None else (layout == "windows")
    if layout not in (None, "windows", "posix"):
        raise StagedRuntimeError("unsupported staged virtualenv layout")
    site = root / (
        "Lib/site-packages"
        if windows
        else (
            f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
        )
    )
    scripts = root / ("Scripts" if windows else "bin")
    python = scripts / ("python.exe" if windows else "python")
    _directories_from(root, site)
    _directories_from(root, scripts)
    _ordinary(python, directory=False)
    _config(root / "pyvenv.cfg")
    try:
        prepared = verify_prepared_record_against_wheelhouse(
            prepared_record,
            wheelhouse,
            lock_envelope=lock_envelope,
            registry_envelope=registry_envelope,
            trust=trust,
            now=now,
            checkpoint=checkpoint,
        )
    except (PreparedRecordError, ValueError, OSError) as error:
        raise StagedRuntimeError("staged composition provenance mismatch") from error
    expected_dist: set[str] = set()
    expected_launchers: dict[str, tuple[str, str]] = {}
    metadata_info: list[tuple[Path, bytes, bytes, bytes | None]] = []
    for wheel in prepared.wheels:
        artifact = wheelhouse / wheel.filename
        try:
            _ordinary(artifact, directory=False)
            with artifact.open("rb") as stream:
                if _hash_stream(stream) != wheel.sha256:
                    raise StagedRuntimeError("source wheel changed after lock check")
                stream.seek(0)
                with zipfile.ZipFile(stream) as archive:
                    prefix, meta, wheel_info, entry_info = _entries(archive)
                stream.seek(0)
                if _hash_stream(stream) != wheel.sha256:
                    raise StagedRuntimeError("source wheel changed during inspection")
        except (OSError, zipfile.BadZipFile, KeyError) as error:
            raise StagedRuntimeError("source wheel metadata unreadable") from error
        expected_dist.add(prefix)
        metadata_info.append((site / prefix, meta, wheel_info, entry_info))
        for name, target in _console(entry_info):
            key = name.lower() if windows else name
            if key in expected_launchers:
                raise StagedRuntimeError("duplicate owned console launcher")
            expected_launchers[key] = (wheel.distribution, target)
    observed_dist = {p.name for p in site.iterdir() if p.name.endswith(".dist-info")}
    if observed_dist != expected_dist:
        raise StagedRuntimeError("installed distribution inventory differs from lock")
    for item in site.iterdir():
        if item.suffix in {".pth", ".egg-link"} or item.name in {
            "sitecustomize.py",
            "usercustomize.py",
        }:
            raise StagedRuntimeError("unqualified startup injection in stage")
    for folder, meta, wheel_info, entry_info in metadata_info:
        _ordinary(folder, directory=True)
        paths = (("METADATA", meta), ("WHEEL", wheel_info))
        for filename, expected in paths:
            metadata_path = folder / filename
            if _limited(metadata_path, _MAX_METADATA) != expected:
                raise StagedRuntimeError("installed distribution metadata differs")
            size = len(expected)
            sha = hashlib.sha256(expected).hexdigest()
            _record_matches(folder / "RECORD", f"{folder.name}/{filename}", sha, size)
        entry = folder / "entry_points.txt"
        if entry_info is None:
            if entry.exists() or entry.is_symlink():
                raise StagedRuntimeError("unexpected installed entry point metadata")
        else:
            if _limited(entry, _MAX_METADATA) != entry_info:
                raise StagedRuntimeError("installed entry point metadata differs")
            _record_matches(
                folder / "RECORD",
                f"{folder.name}/{entry.name}",
                hashlib.sha256(entry_info).hexdigest(),
                len(entry_info),
            )
    allowed_exes = {"python.exe", "pythonw.exe"} if windows else set()
    allowed_exes.update(
        f"{name}.exe" if windows else name for name in expected_launchers
    )
    for item in scripts.iterdir():
        if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
            raise StagedRuntimeError("staged Scripts contains a reparse point")
        if (
            windows
            and item.suffix.lower() == ".exe"
            and item.name.lower() not in allowed_exes
        ):
            raise StagedRuntimeError("unexpected unowned staged executable")
    launchers: list[ObservedConsoleLauncher] = []
    for key, (owner, target) in sorted(expected_launchers.items()):
        name = key
        script = scripts / (f"{name}.exe" if windows else name)
        digest = _wrapper(script, target, windows=windows)
        launchers.append(ObservedConsoleLauncher(owner, name, target, script, digest))
    return StagedRuntimeInspection(
        prepared.transaction_id,
        root,
        site,
        tuple(w.distribution for w in prepared.wheels),
        tuple(launchers),
    )


__all__ = (
    "ObservedConsoleLauncher",
    "StagedRuntimeError",
    "StagedRuntimeInspection",
    "inspect_staged_virtualenv",
)
