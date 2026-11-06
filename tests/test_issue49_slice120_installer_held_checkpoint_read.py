"""Issue #49 Slice 120: native Win32 held-file read stays non-authorizing."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_data_suite import evergreen_windows_installer_held_checkpoint_read as target


def _canon(o: dict[str, object]) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()


def _case() -> tuple[bytes, bytes, bytes]:
    old = _canon(
        {
            "schema": 1,
            "generation": 0,
            "trust_policy_sha256": "a" * 64,
            "trust_policy_revision": 2,
            "registry_revision": 0,
            "registry_sha256": "0" * 64,
            "lock_revision": 0,
            "lock_sha256": "0" * 64,
            "last_transaction_id": "0" * 32,
            "last_request_sha256": "0" * 64,
        }
    )
    new_obj = json.loads(old)
    new_obj.update(
        generation=1,
        registry_revision=3,
        registry_sha256="b" * 64,
        lock_revision=4,
        lock_sha256="c" * 64,
        last_transaction_id="d" * 32,
        last_request_sha256="e" * 64,
    )
    new = _canon(new_obj)
    journal = _canon(
        {
            "schema": 1,
            "phase": "INTENT_PREPARED",
            "transaction_id": "d" * 32,
            "request_sha256": "e" * 64,
            "previous_checkpoint_sha256": hashlib.sha256(old).hexdigest(),
            "previous_generation": 0,
            "proposed_checkpoint_sha256": hashlib.sha256(new).hexdigest(),
            "proposed_generation": 1,
        }
    )
    return old, new, journal


@pytest.mark.parametrize(
    "current,phase,relationship",
    [
        ("old", "INTENT_PREPARED", "PREPARED_PREVIOUS_STATE_OBSERVED"),
        ("new", "INTENT_PREPARED", "REPLACEMENT_WITH_UNFINALIZED_JOURNAL_OBSERVED"),
        ("new", "CHECKPOINT_REPLACED_CLAIMED", "REPLACEMENT_CLAIMED_COMMIT_UNVERIFIED"),
    ],
    ids=("old-prepared", "new-prepared", "new-claimed"),
)
def test_coherent_records_never_authorize(
    current: str, phase: str, relationship: str
) -> None:
    old, new, journal = _case()
    record = json.loads(journal)
    record["phase"] = phase
    observed = target._interpret_pair(old if current == "old" else new, _canon(record))
    assert observed.relationship == relationship
    assert observed.status == "WIN32_HELD_CHECKPOINT_BYTES_OBSERVED_NOT_AUTHORIZED"
    assert observed.os_handles_held_during_read is True
    assert observed.authority == target._NO_AUTHORITY
    for field in (
        "protected_path_acl_verified",
        "privileged_service_authenticated",
        "durable_state_verified",
        "independent_antirollback_verified",
        "permitted_to_resume",
        "permitted_to_replace",
        "permitted_to_publish_receipt",
        "permitted_to_activate_or_launch",
    ):
        assert getattr(observed, field) is False
    serialized = str(asdict(observed))
    assert "ProgramData" not in serialized and "secret" not in serialized


def test_claimed_replacement_with_old_refuses() -> None:
    old, _, journal = _case()
    record = json.loads(journal)
    record["phase"] = "CHECKPOINT_REPLACED_CLAIMED"
    with pytest.raises(target.HeldCheckpointReadError):
        target._interpret_pair(old, _canon(record))


@pytest.mark.parametrize(
    "change",
    [
        "transaction_id",
        "request_sha256",
        "previous_checkpoint_sha256",
        "proposed_checkpoint_sha256",
    ],
    ids=("tx", "request", "previous", "proposed"),
)
def test_cross_record_tamper_refuses(change: str) -> None:
    old, new, journal = _case()
    record = json.loads(journal)
    record[change] = "f" * (32 if change == "transaction_id" else 64)
    with pytest.raises(target.HeldCheckpointReadError):
        target._interpret_pair(
            new if change != "previous_checkpoint_sha256" else old, _canon(record)
        )


@pytest.mark.parametrize(
    "bad",
    [b"", b"{}", b"x" * 4097, b"\xff", b'{"a":1,"a":2}'],
    ids=("empty", "missing", "oversized", "invalid-utf8", "duplicate-fields"),
)
def test_invalid_record_refuses(bad: bytes) -> None:
    old, _, journal = _case()
    with pytest.raises(target.HeldCheckpointReadError):
        target._interpret_pair(bad, journal)
    with pytest.raises(target.HeldCheckpointReadError):
        target._interpret_pair(old, bad)


def test_non_bytes_refuse() -> None:
    old, _, journal = _case()
    with pytest.raises(target.HeldCheckpointReadError):
        target._interpret_pair(old.decode(), journal)  # type: ignore[arg-type]


class _FakeApi:
    def __init__(self, *, attrs: int = 0, reported_size: int = 4) -> None:
        self.attrs = attrs
        self.size = reported_size
        self.handles: list[int] = []
        self.closed: list[int] = []
        self.opens: list[tuple[str, int, int]] = []

    def CreateFileW(self, path: str, access: int, sharing: int, *args: object) -> int:
        handle = len(self.handles) + 1
        self.handles.append(handle)
        self.opens.append((path, access, sharing))
        return handle

    def GetFileInformationByHandle(self, handle: int, output: object) -> bool:
        info = target.ctypes.cast(
            output, target.ctypes.POINTER(target._ByHandleInfo)
        ).contents
        info.dwFileAttributes = self.attrs
        info.nFileSizeHigh = self.size >> 32
        info.nFileSizeLow = self.size & 0xFFFFFFFF
        info.nNumberOfLinks = 1
        return True

    def CloseHandle(self, handle: int) -> bool:
        self.closed.append(handle)
        return True

    def GetFileSizeEx(self, handle: int, output: object) -> bool:
        size = target.ctypes.cast(
            output, target.ctypes.POINTER(target.ctypes.c_longlong)
        )
        size.contents.value = self.size
        return True

    def ReadFile(
        self, handle: int, buffer: object, length: int, count: object, *args: object
    ) -> bool:
        raw = b"abcd"[: self.size]
        target.ctypes.memmove(buffer, raw, len(raw))
        used = target.ctypes.cast(count, target.ctypes.POINTER(target.wintypes.DWORD))
        used.contents.value = len(raw)
        return True


def test_win32_held_object_opens_reparse_node_and_closes() -> None:
    fake = _FakeApi()
    with target._held(fake, Path("C:/fake/checkpoint.json"), directory=False) as handle:
        assert handle == 1
        assert target._read_held(fake, handle) == b"abcd"
        assert fake.closed == []
    assert fake.closed == [1]
    assert fake.opens[0][1] == target._GENERIC_READ
    assert fake.opens[0][2] == target._SHARE_READ


@pytest.mark.parametrize(
    "attrs,directory",
    [
        (target._FILE_ATTRIBUTE_REPARSE_POINT, False),
        (target._FILE_ATTRIBUTE_DIRECTORY, False),
        (0, True),
        (target._FILE_ATTRIBUTE_DIRECTORY | target._FILE_ATTRIBUTE_REPARSE_POINT, True),
    ],
    ids=("link-file", "dir-as-file", "file-as-dir", "link-directory"),
)
def test_unsafe_held_object_refuses_and_closes(attrs: int, directory: bool) -> None:
    fake = _FakeApi(attrs=attrs)
    with pytest.raises(target.HeldCheckpointReadError):
        with target._held(fake, Path("C:/fake"), directory=directory):
            pass
    assert fake.closed == [1]


@pytest.mark.parametrize(
    "size", [0, 4097, 2**32 + 1], ids=("empty", "oversized", "huge")
)
def test_file_size_refuses(size: int) -> None:
    fake = _FakeApi(reported_size=size)
    with pytest.raises(target.HeldCheckpointReadError):
        with target._held(fake, Path("C:/fake"), directory=False):
            pass
    assert fake.closed == [1]


def test_missing_close_never_presumed_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeApi()
    monkeypatch.setattr(target, "_windows_api", lambda: fake)
    monkeypatch.setattr(target, "os", SimpleNamespace(name="nt"))
    # Test WindowsPath handling only through an existing absolute POSIX Path.
    # No live privileged state can be inferred from synthetic Win32 handles.
    with pytest.raises(target.HeldCheckpointReadError):
        target._read_native_pair(Path("relative"))


def test_cli_refuses_apply_and_paths(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        target.main(["--apply"])
    assert error.value.code == 2
    with pytest.raises(SystemExit) as error:
        target.main(["--path", "C:\\temp"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_non_windows_refuses_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target, "os", SimpleNamespace(name="posix"))
    with pytest.raises(target.HeldCheckpointReadError, match="Windows is required"):
        target.inspect_windows_held_checkpoint()


def test_native_contract_has_no_write_api() -> None:
    import inspect

    source = inspect.getsource(target)
    for forbidden in (
        "WriteFile",
        "MoveFileExW",
        "ReplaceFileW",
        "CreateService",
        "StartService",
        "DeleteFileW",
        "winreg",
        "os.replace",
    ):
        assert forbidden not in source


def test_entire_win32_pair_read_holds_ancestors_and_both_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, _, journal = _case()

    class PairApi(_FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.records = {4: old, 5: journal}
            self.read_open_counts: list[int] = []

        def GetFileInformationByHandle(self, handle: int, output: object) -> bool:
            info = target.ctypes.cast(
                output, target.ctypes.POINTER(target._ByHandleInfo)
            ).contents
            info.dwFileAttributes = (
                target._FILE_ATTRIBUTE_DIRECTORY if handle <= 3 else 0
            )
            length = len(self.records.get(handle, b""))
            info.nFileSizeHigh = length >> 32
            info.nFileSizeLow = length & 0xFFFFFFFF
            info.nNumberOfLinks = 1
            return True

        def GetFileSizeEx(self, handle: int, output: object) -> bool:
            size = target.ctypes.cast(
                output, target.ctypes.POINTER(target.ctypes.c_longlong)
            )
            size.contents.value = len(self.records[handle])
            return True

        def ReadFile(
            self, handle: int, buffer: object, length: int, count: object, *args: object
        ) -> bool:
            self.read_open_counts.append(len(self.handles) - len(self.closed))
            raw = self.records[handle]
            target.ctypes.memmove(buffer, raw, len(raw))
            used = target.ctypes.cast(
                count, target.ctypes.POINTER(target.wintypes.DWORD)
            )
            used.contents.value = len(raw)
            return True

    api = PairApi()
    monkeypatch.setattr(target, "_windows_api", lambda: api)
    monkeypatch.setattr(target, "os", SimpleNamespace(name="nt"))
    observed = target._read_native_pair(
        Path("C:/ProgramData" if os.name == "nt" else "/ProgramData")
    )
    assert observed == (old, journal)
    assert api.read_open_counts == [5, 5]
    assert api.closed == [5, 4, 3, 2, 1]
    assert len(api.opens) == 5
    assert all(
        access == target._GENERIC_READ and sharing == target._SHARE_READ
        for _, access, sharing in api.opens
    )


def test_held_hardlinked_record_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    class LinkedApi(_FakeApi):
        def GetFileInformationByHandle(self, handle: int, output: object) -> bool:
            super().GetFileInformationByHandle(handle, output)
            info = target.ctypes.cast(
                output, target.ctypes.POINTER(target._ByHandleInfo)
            ).contents
            info.nNumberOfLinks = 2
            return True

    api = LinkedApi()
    with pytest.raises(target.HeldCheckpointReadError, match="hard-linked"):
        with target._held(api, Path("C:/fake/record"), directory=False):
            pass
    assert api.closed == [1]
