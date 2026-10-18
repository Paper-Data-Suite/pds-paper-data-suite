"""Issue #49 Slice 25: journal-bound publisher/native/real-pip stage audit."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice24_publisher_pip_preflight as publisher_fixture
from test_issue49_slice3_signature_verification import NOW, _encode, _private, _ring

from paper_data_suite.evergreen_journal_pip_preflight import (
    JournalPipPreflightError,
    inspect_journal_bound_publisher_pip_candidate,
)
from paper_data_suite.evergreen_update_journal import begin_verified_update_intent

_CONTEXT = b"pds-evergreen-staged-native-evidence-v1\x00"


def _native(stage: Path, prepared: bytes) -> bytes:
    claim = json.loads(prepared)
    scripts = "Scripts" if os.name == "nt" else "bin"
    paths = [f"{scripts}/python.exe" if os.name == "nt" else f"{scripts}/python"]
    paths.append(f"{scripts}/demo.exe" if os.name == "nt" else f"{scripts}/demo")
    if (stage / "Scripts/pythonw.exe").exists():
        paths.append("Scripts/pythonw.exe")
    payload = _encode(
        {
            "record_type": "pds_evergreen_staged_native_evidence",
            "schema_version": 1,
            "revision": 1,
            "issued_at": "2026-10-17T16:00:00Z",
            "expires_at": "2026-11-17T16:00:00Z",
            "transaction_id": claim["transaction_id"],
            "registry_payload_sha256": claim["registry_payload_sha256"],
            "lock_payload_sha256": claim["lock_payload_sha256"],
            "trust_fingerprint": claim["trust_fingerprint"],
            "python_minor": claim["python_minor"],
            "platform": claim["platform"],
            "files": [
                {
                    "relative_path": path,
                    "sha256": hashlib.sha256((stage / path).read_bytes()).hexdigest(),
                    "size": (stage / path).stat().st_size,
                }
                for path in paths
            ],
        }
    )
    return _encode(
        {
            "envelope_version": 1,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "signatures": [
                {
                    "key_id": "root-primary",
                    "algorithm": "ed25519",
                    "signature_b64": base64.b64encode(
                        _private("root-primary").sign(_CONTEXT + payload)
                    ).decode("ascii"),
                }
            ],
        }
    )


@pytest.fixture(scope="module")
def journal_candidate(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("journal-publisher-real-pip")
    monkeypatch = pytest.MonkeyPatch()
    try:
        stage, wheels, registry, lock, prepared, publisher = (
            publisher_fixture._signed_stage(root, monkeypatch)
        )
    finally:
        monkeypatch.undo()
    root = stage.parent
    workspace = root.parent / (root.name + "-classroom")
    workspace.mkdir(exist_ok=True)
    (root / "transactions").mkdir(exist_ok=True)
    native = _native(stage, prepared)
    begin_verified_update_intent(
        root,
        classroom_workspace=workspace,
        stage_root=stage,
        wheelhouse=wheels,
        prepared_record=prepared,
        registry_envelope=registry,
        lock_envelope=lock,
        evidence_envelope=native,
        trust=_ring(),
        now=NOW,
    )
    return {
        "software_root": root,
        "classroom_workspace": workspace,
        "transaction_id": "e" * 32,
        "expected_revision": 1,
        "prepared_record": prepared,
        "registry_envelope": registry,
        "lock_envelope": lock,
        "evidence_envelope": native,
        "module_envelopes": {"demo": publisher},
        "trust": _ring(),
        "now": NOW,
    }


def _args(values: dict[str, Any]) -> dict[str, Any]:
    output = dict(values)
    output["module_envelopes"] = dict(values["module_envelopes"])
    return output


def test_journal_binds_real_pip_publisher_and_signed_native_evidence(
    journal_candidate: dict[str, Any],
) -> None:
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        result = inspect_journal_bound_publisher_pip_candidate(
            **_args(journal_candidate)
        )
    assert result.transaction_id == "e" * 32
    assert result.journal_revision == 1
    assert result.root_console_targets == (("demo-app", "demo", "demo_app.cli:main"),)
    assert result.external_distributions == ("demo-core",)
    assert len(result.native_payload_sha256) == 64
    assert len(result.pip_inventory_sha256) == 64
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "active_receipt")
    assert not hasattr(result, "activate")


@pytest.mark.parametrize(
    "field", ["prepared_record", "evidence_envelope", "lock_envelope"]
)
def test_wrong_journal_evidence_is_not_accepted(
    journal_candidate: dict[str, Any], field: str
) -> None:
    args = _args(journal_candidate)
    args[field] = args[field] + b"\n"
    with pytest.raises(JournalPipPreflightError, match="hash mismatch"):
        inspect_journal_bound_publisher_pip_candidate(**args)


def test_stale_revision_and_wrong_transaction_rejected(
    journal_candidate: dict[str, Any],
) -> None:
    for key, value in (("expected_revision", 2), ("transaction_id", "f" * 32)):
        args = _args(journal_candidate)
        args[key] = value
        with pytest.raises(JournalPipPreflightError):
            inspect_journal_bound_publisher_pip_candidate(**args)


def test_missing_publisher_signature_rejected_before_any_stage_authorization(
    journal_candidate: dict[str, Any],
) -> None:
    args = _args(journal_candidate)
    args["module_envelopes"] = {"demo": b"not signed"}
    with pytest.raises(JournalPipPreflightError, match="preflight failed"):
        inspect_journal_bound_publisher_pip_candidate(**args)


def test_untrusted_local_recovery_state_blocks_inspection(
    journal_candidate: dict[str, Any],
) -> None:
    marker = journal_candidate["software_root"] / "pending-slot-recovery.json"
    marker.write_bytes(b"unverified recovery")
    try:
        with pytest.raises(JournalPipPreflightError, match="pending selection"):
            inspect_journal_bound_publisher_pip_candidate(**_args(journal_candidate))
    finally:
        marker.unlink()


def test_competing_selection_lock_refuses_to_enter(
    journal_candidate: dict[str, Any],
) -> None:
    lock = journal_candidate["software_root"] / "candidate-selection.lock"
    lock.write_text("occupied")
    try:
        with pytest.raises(JournalPipPreflightError, match="locked"):
            inspect_journal_bound_publisher_pip_candidate(**_args(journal_candidate))
    finally:
        lock.unlink()


def test_changed_installed_code_refused_and_restored(
    journal_candidate: dict[str, Any],
) -> None:
    path = journal_candidate["software_root"] / "private-staged-venv"
    name = (
        "Lib/site-packages"
        if os.name == "nt"
        else (
            f"lib/python{os.sys.version_info.major}."
            f"{os.sys.version_info.minor}/site-packages"
        )
    )
    source = path / name / "demo_app/__init__.py"
    original = source.read_bytes()
    source.write_bytes(original + b"# unauthorized\n")
    try:
        with pytest.raises(JournalPipPreflightError, match="preflight failed"):
            inspect_journal_bound_publisher_pip_candidate(**_args(journal_candidate))
    finally:
        source.write_bytes(original)


def test_inconsistent_publisher_observation_does_not_authorize(
    journal_candidate: dict[str, Any],
) -> None:
    from paper_data_suite.evergreen_journal_pip_preflight import (
        audit_publisher_bound_pip_candidate,
    )

    def changed(*args: Any, **kwargs: Any) -> Any:
        result = audit_publisher_bound_pip_candidate(*args, **kwargs)
        return replace(result, transaction_id="f" * 32)

    with patch(
        "paper_data_suite.evergreen_journal_pip_preflight."
        "audit_publisher_bound_pip_candidate",
        side_effect=changed,
    ):
        with pytest.raises(JournalPipPreflightError, match="identity"):
            inspect_journal_bound_publisher_pip_candidate(**_args(journal_candidate))


def test_missing_classroom_boundary_is_rejected(
    journal_candidate: dict[str, Any],
) -> None:
    args = _args(journal_candidate)
    args["classroom_workspace"] = args["software_root"] / "transactions"
    with pytest.raises(JournalPipPreflightError, match="unsafe"):
        inspect_journal_bound_publisher_pip_candidate(**args)


def test_changed_publisher_envelope_during_inspection_refused(
    journal_candidate: dict[str, Any],
) -> None:
    from paper_data_suite.evergreen_journal_pip_preflight import (
        audit_publisher_bound_pip_candidate,
    )

    args = _args(journal_candidate)

    def change(*positional: Any, **keywords: Any) -> Any:
        result = audit_publisher_bound_pip_candidate(*positional, **keywords)
        args["module_envelopes"]["demo"] = b"replaced"
        return result

    with patch(
        "paper_data_suite.evergreen_journal_pip_preflight."
        "audit_publisher_bound_pip_candidate",
        side_effect=change,
    ):
        with pytest.raises(JournalPipPreflightError, match="changed during"):
            inspect_journal_bound_publisher_pip_candidate(**args)


def test_lock_and_journal_remain_unchanged_after_success(
    journal_candidate: dict[str, Any],
) -> None:
    root = journal_candidate["software_root"]
    journal = root / "transactions" / ("e" * 32 + ".json")
    before = journal.read_bytes()
    inspect_journal_bound_publisher_pip_candidate(**_args(journal_candidate))
    assert journal.read_bytes() == before
    assert not (root / "candidate-selection.lock").exists()
    assert not (root / "transactions" / ("e" * 32 + ".lock")).exists()
    assert not (root / "pending-slot-recovery.json").exists()
