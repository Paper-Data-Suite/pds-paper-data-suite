"""Slice 119: OS-facing fixed-path checkpoint inspection is never an installer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_data_suite import (
    evergreen_windows_installer_checkpoint_custody_probe as target,
)


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _checkpoint(*, progressed: bool) -> bytes:
    return _canonical(
        {
            "schema": 1,
            "generation": 1 if progressed else 0,
            "trust_policy_sha256": "a" * 64,
            "trust_policy_revision": 3,
            "registry_revision": 5 if progressed else 0,
            "registry_sha256": "b" * 64 if progressed else "0" * 64,
            "lock_revision": 7 if progressed else 0,
            "lock_sha256": "c" * 64 if progressed else "0" * 64,
            "last_transaction_id": "d" * 32 if progressed else "0" * 32,
            "last_request_sha256": "e" * 64 if progressed else "0" * 64,
        }
    )


def _journal(*, phase: str = "INTENT_PREPARED") -> bytes:
    return _canonical(
        {
            "schema": 1,
            "phase": phase,
            "transaction_id": "d" * 32,
            "request_sha256": "e" * 64,
            "previous_checkpoint_sha256": hashlib.sha256(
                _checkpoint(progressed=False)
            ).hexdigest(),
            "previous_generation": 0,
            "proposed_checkpoint_sha256": hashlib.sha256(
                _checkpoint(progressed=True)
            ).hexdigest(),
            "proposed_generation": 1,
        }
    )


def _acl() -> dict[str, object]:
    return {
        "owner": "S-1-5-18",
        "rules": [
            {
                "sid": "S-1-5-18",
                "type": "Allow",
                "rights": 0x1F01FF,
                "inherited": False,
                "inherit_only": False,
            }
        ],
    }


def _read(_: Path) -> dict[str, object]:
    return _acl()


@pytest.fixture
def state(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "ProgramData"
    service = home / "Paper Data Suite" / "service-state"
    service.mkdir(parents=True)
    return (
        home,
        service / "installer-checkpoint-v1.json",
        service / "installer-intent-journal-v1.json",
    )


def _install(checkpoint: Path, journal: Path, *, progressed: bool, phase: str) -> None:
    checkpoint.write_bytes(_checkpoint(progressed=progressed))
    journal.write_bytes(_journal(phase=phase))


@pytest.mark.parametrize(
    ("progressed", "phase", "relationship"),
    [
        (False, "INTENT_PREPARED", "PREPARED_PREVIOUS_STATE_OBSERVED"),
        (True, "INTENT_PREPARED", "REPLACEMENT_WITH_UNFINALIZED_JOURNAL_OBSERVED"),
        (
            True,
            "CHECKPOINT_REPLACED_CLAIMED",
            "REPLACEMENT_CLAIMED_COMMIT_UNVERIFIED",
        ),
    ],
    ids=("old-prepared", "new-prepared", "new-replaced"),
)
def test_exact_current_state_observed_without_authority(
    state: tuple[Path, Path, Path], progressed: bool, phase: str, relationship: str
) -> None:
    home, checkpoint, journal = state
    _install(checkpoint, journal, progressed=progressed, phase=phase)
    report = target.inspect_claimed_windows_checkpoint_paths(home, read_acl=_read)
    assert report.checked_entries == 5
    assert report.status == "PROTECTED_CHECKPOINT_PATHS_OBSERVED_NO_NATIVE_CUSTODY"
    assert report.checkpoint_generation == int(progressed)
    assert report.relationship == relationship
    assert (
        report.checkpoint_sha256 == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    )
    assert report.journal_sha256 == hashlib.sha256(journal.read_bytes()).hexdigest()
    assert all(
        getattr(report, key) is False
        for key in (
            "os_handle_custody_verified",
            "privileged_service_authenticated",
            "durable_state_verified",
            "independent_antirollback_verified",
            "permitted_to_resume",
            "permitted_to_replace",
            "permitted_to_publish_receipt",
            "permitted_to_activate_or_launch",
        )
    )
    assert report.authority == target._NO_AUTHORITY
    assert "transaction_id" not in asdict(report)


@pytest.mark.parametrize(
    ("checkpoint_exists", "journal_exists", "status"),
    [
        (False, False, "PROTECTED_CHECKPOINT_GENESIS_NOT_ESTABLISHED"),
        (True, False, "PROTECTED_CHECKPOINT_INCOMPLETE_REFUSE_RECOVERY"),
        (False, True, "PROTECTED_CHECKPOINT_INCOMPLETE_REFUSE_RECOVERY"),
    ],
    ids=("absent-both", "checkpoint-only", "journal-only"),
)
def test_absence_never_proves_genesis(
    state: tuple[Path, Path, Path],
    checkpoint_exists: bool,
    journal_exists: bool,
    status: str,
) -> None:
    home, checkpoint, journal = state
    if checkpoint_exists:
        checkpoint.write_bytes(_checkpoint(progressed=False))
    if journal_exists:
        journal.write_bytes(_journal())
    report = target.inspect_claimed_windows_checkpoint_paths(home, read_acl=_read)
    assert report.status == status
    assert report.checkpoint_present is checkpoint_exists
    assert report.journal_present is journal_exists
    assert report.checkpoint_sha256 is None
    assert report.authority == target._NO_AUTHORITY


@pytest.mark.parametrize("missing", ["protected", "service"], ids=("app", "state"))
def test_missing_protected_directory_reports_provisioning(
    tmp_path: Path, missing: str
) -> None:
    root = tmp_path / "ProgramData"
    root.mkdir()
    if missing == "service":
        (root / "Paper Data Suite").mkdir()
    result = target.inspect_claimed_windows_checkpoint_paths(root, read_acl=_read)
    assert result.status == "PROTECTED_CHECKPOINT_PROVISIONING_REQUIRED"
    assert result.checked_entries in (1, 2)


def test_missing_programdata_root_refuses(tmp_path: Path) -> None:
    with pytest.raises(target.InstallerCheckpointCustodyProbeError, match="root"):
        target.inspect_claimed_windows_checkpoint_paths(
            tmp_path / "missing", read_acl=_read
        )


@pytest.mark.parametrize("node", ["app", "service", "checkpoint", "journal"])
def test_symlink_refuses_before_read(
    state: tuple[Path, Path, Path], tmp_path: Path, node: str
) -> None:
    home, checkpoint, journal = state
    try:
        if node == "app":
            (home / "Paper Data Suite" / "service-state").rmdir()
            (home / "Paper Data Suite").rmdir()
            (home / "Paper Data Suite").symlink_to(tmp_path, target_is_directory=True)
        elif node == "service":
            checkpoint.parent.rmdir()
            checkpoint.parent.symlink_to(tmp_path, target_is_directory=True)
        else:
            selected = checkpoint if node == "checkpoint" else journal
            selected.symlink_to(tmp_path / "missing")
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(target.InstallerCheckpointCustodyProbeError, match="unsafe"):
        target.inspect_claimed_windows_checkpoint_paths(home, read_acl=_read)


@pytest.mark.parametrize("node", ["checkpoint", "journal"])
def test_directory_instead_of_record_refuses(
    state: tuple[Path, Path, Path], node: str
) -> None:
    home, checkpoint, journal = state
    (checkpoint if node == "checkpoint" else journal).mkdir()
    with pytest.raises(target.InstallerCheckpointCustodyProbeError, match="unsafe"):
        target.inspect_claimed_windows_checkpoint_paths(home, read_acl=_read)


@pytest.mark.parametrize("node", ["checkpoint", "journal"])
def test_oversized_files_refuse(state: tuple[Path, Path, Path], node: str) -> None:
    home, checkpoint, journal = state
    _install(checkpoint, journal, progressed=False, phase="INTENT_PREPARED")
    (checkpoint if node == "checkpoint" else journal).write_bytes(b"x" * 4097)
    with pytest.raises(target.InstallerCheckpointCustodyProbeError, match="size"):
        target.inspect_claimed_windows_checkpoint_paths(home, read_acl=_read)


@pytest.mark.parametrize(
    ("node", "value"),
    [
        ("checkpoint", b""),
        ("checkpoint", b"{}"),
        ("checkpoint", b"x"),
        ("journal", b""),
        ("journal", b"{}"),
        ("journal", b"x"),
        ("journal", b"\xff"),
    ],
    ids=(
        "empty-cp",
        "empty-cp-object",
        "garbled-cp",
        "empty-j",
        "empty-j-object",
        "garbled-j",
        "nonutf8-j",
    ),
)
def test_invalid_file_contents_refuse(
    state: tuple[Path, Path, Path], node: str, value: bytes
) -> None:
    home, checkpoint, journal = state
    _install(checkpoint, journal, progressed=False, phase="INTENT_PREPARED")
    (checkpoint if node == "checkpoint" else journal).write_bytes(value)
    with pytest.raises(target.InstallerCheckpointCustodyProbeError):
        target.inspect_claimed_windows_checkpoint_paths(home, read_acl=_read)


@pytest.mark.parametrize("change", ["phase", "request", "checkpoint", "tx"])
def test_conflicting_checkpoint_journal_refuses(
    state: tuple[Path, Path, Path], change: str
) -> None:
    home, checkpoint, journal = state
    _install(checkpoint, journal, progressed=False, phase="INTENT_PREPARED")
    data = json.loads(journal.read_bytes())
    if change == "phase":
        data["phase"] = "CHECKPOINT_REPLACED_CLAIMED"
    elif change == "request":
        checkpoint.write_bytes(_checkpoint(progressed=True))
        data["request_sha256"] = "f" * 64
    elif change == "checkpoint":
        data["previous_checkpoint_sha256"] = "f" * 64
    else:
        checkpoint.write_bytes(_checkpoint(progressed=True))
        data["transaction_id"] = "f" * 32
    journal.write_bytes(_canonical(data))
    with pytest.raises(
        target.InstallerCheckpointCustodyProbeError, match="inconsistent"
    ):
        target.inspect_claimed_windows_checkpoint_paths(home, read_acl=_read)


@pytest.mark.parametrize("untrusted", ["app", "state", "checkpoint", "journal"])
def test_untrusted_writer_acl_refuses(
    state: tuple[Path, Path, Path], untrusted: str
) -> None:
    home, checkpoint, journal = state
    _install(checkpoint, journal, progressed=True, phase="INTENT_PREPARED")
    selected = {
        "app": home / "Paper Data Suite",
        "state": checkpoint.parent,
        "checkpoint": checkpoint,
        "journal": journal,
    }[untrusted]

    def unsafe(p: Path) -> object:
        data = _acl()
        if p == selected:
            data["rules"].append(
                {
                    "sid": "S-1-5-32-545",
                    "type": "Allow",
                    "rights": 0x2,
                    "inherited": False,
                    "inherit_only": False,
                }
            )
        return data

    with pytest.raises(target.InstallerCheckpointCustodyProbeError, match="ACL"):
        target.inspect_claimed_windows_checkpoint_paths(home, read_acl=unsafe)


def test_programdata_dangerous_parent_acl_refuses(
    state: tuple[Path, Path, Path],
) -> None:
    home, _, _ = state

    def unsafe(p: Path) -> object:
        data = _acl()
        if p == home:
            data["rules"].append(
                {
                    "sid": "S-1-5-32-545",
                    "type": "Allow",
                    "rights": 0x40,  # DELETE_CHILD
                    "inherited": False,
                    "inherit_only": False,
                }
            )
        return data

    with pytest.raises(target.InstallerCheckpointCustodyProbeError, match="ACL"):
        target.inspect_claimed_windows_checkpoint_paths(home, read_acl=unsafe)


@pytest.mark.parametrize("bad", ["relative", "not-a-path", "no-reader"])
def test_bad_path_or_acl_reader_refuses(
    state: tuple[Path, Path, Path], bad: str
) -> None:
    home, _, _ = state
    path: object = Path("relative") if bad == "relative" else home
    reader: object = None if bad == "no-reader" else _read
    if bad == "not-a-path":
        path = "C:/ProgramData"
    with pytest.raises(target.InstallerCheckpointCustodyProbeError):
        target.inspect_claimed_windows_checkpoint_paths(path, read_acl=reader)  # type: ignore[arg-type]


def test_actual_entrypoint_nonwindows_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target, "os", SimpleNamespace(name="posix"))
    with pytest.raises(target.InstallerCheckpointCustodyProbeError, match="Windows"):
        target.inspect_windows_checkpoint_custody()


def test_cli_has_no_apply_or_paths(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as err:
        target.main(["--apply"])
    assert err.value.code == 2
    with pytest.raises(SystemExit) as err2:
        target.main(["--path", "C:/arbitrary"])
    assert err2.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_cli_failure_no_authority(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse() -> target.CheckpointCustodyObservation:
        raise target.InstallerCheckpointCustodyProbeError("test")

    monkeypatch.setattr(target, "inspect_windows_checkpoint_custody", refuse)
    assert target.main([]) == 1
    assert target._NO_AUTHORITY in capsys.readouterr().err


def test_cli_status_two_never_says_authorized(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        target,
        "inspect_windows_checkpoint_custody",
        lambda: target.CheckpointCustodyObservation(
            "PROVISIONING_REQUIRED", 1, False, False
        ),
    )
    assert target.main([]) == 2
    output = capsys.readouterr().out
    assert '"os_handle_custody_verified": false' in output
    assert '"permitted_to_activate_or_launch": false' in output
    assert target._NO_AUTHORITY in output


def test_no_provisioning_or_execution_surface() -> None:
    import inspect

    source = inspect.getsource(target)
    for forbidden in (
        "os.replace(",
        "os.chmod(",
        "os.system(",
        "subprocess.run(",
        "winreg",
        "ctypes",
        ".unlink(",
    ):
        assert forbidden not in source
