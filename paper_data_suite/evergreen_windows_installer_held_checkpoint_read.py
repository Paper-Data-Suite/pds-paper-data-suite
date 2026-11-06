"""Issue #49 Slice 120: read checkpoint records through held Win32 handles.

A bounded read-only Win32 observation; NOT an authenticated administrator,
service, protected ledger, durable CAS, installation, recovery, or receipt.
The Python caller and its ProgramData environment are not independent custody.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sys
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Iterator, cast

from paper_data_suite.evergreen_windows_installer_checkpoint_cas import (
    InstallerCheckpointCasError,
    parse_claimed_checkpoint,
)
from paper_data_suite.evergreen_windows_installer_checkpoint_recovery import (
    InstallerCheckpointRecoveryError,
    parse_claimed_checkpoint_journal,
)

_NO_AUTHORITY: Final = (
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
)
_MAX_RECORD: Final = 4096
_APP: Final = "Paper Data Suite"
_STATE: Final = "service-state"
_CHECKPOINT: Final = "installer-checkpoint-v1.json"
_JOURNAL: Final = "installer-intent-journal-v1.json"
_GENERIC_READ: Final = 0x80000000
_SHARE_READ: Final = 1
_OPEN_EXISTING: Final = 3
_OPEN_REPARSE: Final = 0x00200000
_BACKUP_SEMANTICS: Final = 0x02000000
_FILE_ATTRIBUTE_DIRECTORY: Final = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT: Final = 0x400
_INVALID: Final = ctypes.c_void_p(-1).value


class HeldCheckpointReadError(ValueError):
    """A Win32 held-handle record read or record consistency check refused."""


class _ByHandleInfo(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


@dataclass(frozen=True, slots=True)
class HeldCheckpointObservation:
    """One held-handle observation, without independently authenticated custody."""

    status: str
    checkpoint_generation: int
    journal_phase: str
    checkpoint_sha256: str
    journal_sha256: str
    relationship: str
    os_handles_held_during_read: bool = True
    protected_path_acl_verified: bool = False
    privileged_service_authenticated: bool = False
    durable_state_verified: bool = False
    independent_antirollback_verified: bool = False
    permitted_to_resume: bool = False
    permitted_to_replace: bool = False
    permitted_to_publish_receipt: bool = False
    permitted_to_activate_or_launch: bool = False
    authority: str = _NO_AUTHORITY


def _interpret_pair(checkpoint: bytes, journal: bytes) -> HeldCheckpointObservation:
    """Require exact canonical records and a coherent interrupted transaction."""
    if (
        type(checkpoint) is not bytes
        or type(journal) is not bytes
        or not 1 <= len(checkpoint) <= _MAX_RECORD
        or not 1 <= len(journal) <= _MAX_RECORD
    ):
        raise HeldCheckpointReadError("invalid bounded held record bytes")
    try:
        record = parse_claimed_checkpoint(checkpoint)
        intent = parse_claimed_checkpoint_journal(journal)
    except (InstallerCheckpointCasError, InstallerCheckpointRecoveryError) as exc:
        raise HeldCheckpointReadError("malformed held checkpoint or journal") from exc
    checkpoint_hash = hashlib.sha256(checkpoint).hexdigest()
    generation = record["generation"]
    phase = intent["phase"]
    if (
        generation == 0
        and phase == "INTENT_PREPARED"
        and checkpoint_hash == intent["previous_checkpoint_sha256"]
    ):
        relationship = "PREPARED_PREVIOUS_STATE_OBSERVED"
    elif (
        generation == 1
        and checkpoint_hash == intent["proposed_checkpoint_sha256"]
        and record["last_transaction_id"] == intent["transaction_id"]
        and record["last_request_sha256"] == intent["request_sha256"]
    ):
        relationship = (
            "REPLACEMENT_WITH_UNFINALIZED_JOURNAL_OBSERVED"
            if phase == "INTENT_PREPARED"
            else "REPLACEMENT_CLAIMED_COMMIT_UNVERIFIED"
        )
    else:
        raise HeldCheckpointReadError("held transaction and checkpoint disagree")
    return HeldCheckpointObservation(
        status="WIN32_HELD_CHECKPOINT_BYTES_OBSERVED_NOT_AUTHORIZED",
        checkpoint_generation=generation,
        journal_phase=cast(str, phase),
        checkpoint_sha256=checkpoint_hash,
        journal_sha256=hashlib.sha256(journal).hexdigest(),
        relationship=relationship,
    )


def _windows_api() -> object:
    """Load kernel32 lazily; no Windows API touched at Python import time."""
    if os.name != "nt":
        raise HeldCheckpointReadError("Windows is required")
    # WinDLL exists only on Windows; use an explicit runtime lookup so
    # platform-independent type checkers can validate this module on Linux.
    loader = getattr(ctypes, "WinDLL", None)
    if not callable(loader):
        raise HeldCheckpointReadError("Win32 kernel32 loader unavailable")
    api = loader("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    api.CreateFileW.restype = wintypes.HANDLE
    api.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleInfo),
    ]
    api.GetFileInformationByHandle.restype = wintypes.BOOL
    api.GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
    api.GetFileSizeEx.restype = wintypes.BOOL
    api.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    api.ReadFile.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


@contextmanager
def _held(api: object, path: Path, *, directory: bool) -> Iterator[int]:
    """Open the reparse object itself, prohibit concurrent delete/write sharing."""
    flags = _OPEN_REPARSE | _BACKUP_SEMANTICS
    handle = api.CreateFileW(  # type: ignore[attr-defined]
        str(path), _GENERIC_READ, _SHARE_READ, None, _OPEN_EXISTING, flags, None
    )
    if handle is None or handle == _INVALID:
        raise HeldCheckpointReadError("protected Win32 path cannot be held")
    try:
        info = _ByHandleInfo()
        if not api.GetFileInformationByHandle(handle, ctypes.byref(info)):  # type: ignore[attr-defined]
            raise HeldCheckpointReadError("Win32 handle attributes unavailable")
        attrs = info.dwFileAttributes
        if (
            attrs & _FILE_ATTRIBUTE_REPARSE_POINT
            or bool(attrs & _FILE_ATTRIBUTE_DIRECTORY) != directory
        ):
            raise HeldCheckpointReadError(
                "reparse point or unexpected held object type"
            )
        if not directory and info.nNumberOfLinks != 1:
            raise HeldCheckpointReadError("hard-linked protected record refused")
        if not directory and (
            info.nFileSizeHigh or not 1 <= info.nFileSizeLow <= _MAX_RECORD
        ):
            raise HeldCheckpointReadError("held record size outside bounds")
        yield handle
    finally:
        api.CloseHandle(handle)  # type: ignore[attr-defined]


def _read_held(api: object, handle: int) -> bytes:
    """Read at most one bounded record from a previously validated file handle."""
    length = ctypes.c_longlong()
    if not api.GetFileSizeEx(handle, ctypes.byref(length)):  # type: ignore[attr-defined]
        raise HeldCheckpointReadError("cannot size held record")
    if not 1 <= length.value <= _MAX_RECORD:
        raise HeldCheckpointReadError("held record size outside bounds")
    buffer = ctypes.create_string_buffer(_MAX_RECORD + 1)
    count = wintypes.DWORD()
    if not api.ReadFile(handle, buffer, _MAX_RECORD + 1, ctypes.byref(count), None):  # type: ignore[attr-defined]
        raise HeldCheckpointReadError("held record read failed")
    if count.value != length.value:
        raise HeldCheckpointReadError("held file changed during read")
    return buffer.raw[: count.value]


def _read_native_pair(program_data: Path) -> tuple[bytes, bytes]:
    """Keep every ancestor and both files open until BOTH reads complete."""
    if (
        os.name != "nt"
        or not isinstance(program_data, Path)
        or not program_data.is_absolute()
    ):
        raise HeldCheckpointReadError("invalid native Windows record root")
    api = _windows_api()
    app = program_data / _APP
    state = app / _STATE
    checkpoint = state / _CHECKPOINT
    journal = state / _JOURNAL
    with ExitStack() as stack:
        for path in (program_data, app, state):
            stack.enter_context(_held(api, path, directory=True))
        ck = stack.enter_context(_held(api, checkpoint, directory=False))
        jr = stack.enter_context(_held(api, journal, directory=False))
        first = _read_held(api, ck)
        second = _read_held(api, jr)
        return first, second


def inspect_windows_held_checkpoint() -> HeldCheckpointObservation:
    """Fixed ProgramData read-only entrypoint; no caller paths or apply flags."""
    if os.name != "nt":
        raise HeldCheckpointReadError("Windows is required")
    root = os.environ.get("ProgramData")
    if not root or not Path(root).is_absolute():
        raise HeldCheckpointReadError("Windows ProgramData path unavailable")
    try:
        first, second = _read_native_pair(Path(root).absolute())
        return _interpret_pair(first, second)
    except OSError as exc:
        raise HeldCheckpointReadError(
            "Win32 held-state observation unavailable"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        report = inspect_windows_held_checkpoint()
    except HeldCheckpointReadError as exc:
        print(f"REFUSED: {exc}. {_NO_AUTHORITY}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(report), indent=2))
    print(_NO_AUTHORITY)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
