"""Slice 109: service registry observations cannot establish service authority."""

from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from paper_data_suite import evergreen_windows_service_identity_preflight as target


def _present(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "present": True,
        "name": "PaperDataSuiteService",
        "start_name": "LocalSystem",
        "path_name": r'"C:\Program Files\Paper Data Suite\service.exe" --service',
        "state": "Stopped",
        "start_mode": "Manual",
        "process_id": 0,
    }
    payload.update(overrides)
    return payload


def test_absent_is_distinct_from_refusal_and_not_authority() -> None:
    observed = target.inspect_service_snapshot({"present": False})
    assert observed.status == "SERVICE_NOT_INSTALLED"
    assert observed.service_sid_type == "NOT_VERIFIED"
    assert observed.registered_binary_path == "NOT_VERIFIED"
    assert not observed.production_authority
    assert not observed.active_receipt_authority


def test_present_metadata_only_never_grants_authority() -> None:
    observed = target.inspect_service_snapshot(_present())
    assert observed.status == "SERVICE_METADATA_OBSERVED_UNVERIFIED"
    assert observed.account_category == "SHARED_PRIVILEGED_ACCOUNT_OBSERVED"
    assert observed.registered_binary_path.endswith("NOT_DISCLOSED")
    assert observed.effective_token == "NOT_VERIFIED"
    assert observed.service_dacl == "NOT_VERIFIED"
    assert observed.executable_integrity == "NOT_VERIFIED"
    assert observed.protected_receipt_head == "NOT_VERIFIED"
    assert not observed.production_authority
    assert not observed.active_receipt_authority


@pytest.mark.parametrize(
    ("start_name", "category"),
    [
        ("NT SERVICE\\PaperDataSuiteService", "NAMED_VIRTUAL_SERVICE_ACCOUNT_OBSERVED"),
        ("LocalService", "SHARED_LOCAL_SERVICE_ACCOUNT_OBSERVED"),
        ("NetworkService", "SHARED_NETWORK_SERVICE_ACCOUNT_OBSERVED"),
        ("Example\\teacher", "OTHER_ACCOUNT_UNVERIFIED"),
    ],
)
def test_service_accounts_are_only_categories(start_name: str, category: str) -> None:
    observed = target.inspect_service_snapshot(_present(start_name=start_name))
    assert observed.account_category == category
    assert start_name not in json.dumps(asdict(observed))
    assert observed.production_authority is False


def test_running_with_pid_is_unverified() -> None:
    observed = target.inspect_service_snapshot(
        _present(state="Running", process_id=123)
    )
    assert observed.observed_state == "RUNNING_OBSERVED"
    assert not observed.production_authority


@pytest.mark.parametrize(
    "bad", [None, [], "text", {"present": 1}, {"present": False, "name": "x"}]
)
def test_bad_roots_refuse(bad: object) -> None:
    with pytest.raises(target.ServiceIdentityPreflightError):
        target.inspect_service_snapshot(bad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "OtherService"),
        ("name", "PaperDataSuiteService\n"),
        ("start_name", ""),
        ("start_name", "LocalSystem\n"),
        ("path_name", ""),
        ("path_name", "x" * 2049),
        ("path_name", "abc\rdef"),
        ("state", "SomeNewState"),
        ("start_mode", "Unknown"),
        ("process_id", True),
        ("process_id", -1),
        ("process_id", 2**32),
        ("process_id", "123"),
    ],
)
def test_malformed_present_metadata_refuses(field: str, value: object) -> None:
    with pytest.raises(target.ServiceIdentityPreflightError):
        target.inspect_service_snapshot(_present(**{field: value}))


def test_inconsistent_running_pid_refuses() -> None:
    with pytest.raises(target.ServiceIdentityPreflightError):
        target.inspect_service_snapshot(_present(state="Running", process_id=0))


def test_inconsistent_stopped_pid_refuses() -> None:
    with pytest.raises(target.ServiceIdentityPreflightError):
        target.inspect_service_snapshot(_present(state="Stopped", process_id=4))


def test_extra_fields_refuse() -> None:
    with pytest.raises(target.ServiceIdentityPreflightError):
        target.inspect_service_snapshot(_present(approval=True))


def test_fixed_powershell_command_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        assert kwargs.get("capture_output") is True
        assert kwargs.get("timeout") == 15
        assert kwargs.get("check") is False
        return SimpleNamespace(returncode=0, stdout='{"present":false}')

    monkeypatch.setattr(target.subprocess, "run", fake_run)
    assert target._read_scm_snapshot() == {"present": False}
    assert len(calls) == 1
    assert calls[0][:4] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
    ]
    script = base64.b64decode(calls[0][4]).decode("utf-16le")
    assert "Get-CimInstance" in script
    assert "PaperDataSuiteService" in script
    assert not any(
        word in script for word in ("New-Service", "Set-Service", "Start-Service")
    )


@pytest.mark.parametrize(
    "stdout,returncode",
    [("", 0), ("garbage", 0), ("{}", 0), ('{"present":false}', 1), ("x" * 17000, 0)],
)
def test_scm_query_fail_closed(
    monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int
) -> None:
    monkeypatch.setattr(
        target.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stdout=stdout),
    )
    with pytest.raises(target.ServiceIdentityPreflightError):
        snapshot = target._read_scm_snapshot()
        target.inspect_service_snapshot(snapshot)


def test_duplicate_scm_fields_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        target.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout='{"present":false,"present":true}'
        ),
    )
    with pytest.raises(target.ServiceIdentityPreflightError, match="duplicate"):
        target._read_scm_snapshot()


def test_scm_timeout_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired("powershell.exe", 15)

    monkeypatch.setattr(target.subprocess, "run", timeout)
    with pytest.raises(target.ServiceIdentityPreflightError):
        target._read_scm_snapshot()


def test_cli_absent_returns_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        target,
        "audit_windows_service_identity",
        lambda: target.inspect_service_snapshot({"present": False}),
    )
    assert target.main([]) == 2
    output = capsys.readouterr().out
    assert "SERVICE_NOT_INSTALLED" in output
    assert target._NO_AUTHORITY in output


def test_cli_present_returns_zero_but_not_authority(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        target,
        "audit_windows_service_identity",
        lambda: target.inspect_service_snapshot(_present()),
    )
    assert target.main([]) == 0
    output = capsys.readouterr().out
    assert '"production_authority": false' in output
    assert '"active_receipt_authority": false' in output
    assert target._NO_AUTHORITY in output


def test_cli_failure_returns_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unavailable() -> target.ServiceIdentityObservation:
        raise target.ServiceIdentityPreflightError("unavailable")

    monkeypatch.setattr(target, "audit_windows_service_identity", unavailable)
    assert target.main([]) == 1
    assert target._NO_AUTHORITY in capsys.readouterr().err


def test_non_windows_refuses_without_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target, "os", SimpleNamespace(name="posix"))
    with pytest.raises(
        target.ServiceIdentityPreflightError, match="Windows is required"
    ):
        target.audit_windows_service_identity()
