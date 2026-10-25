"""Slice 62: fresh external witness and full selected-stage audit are diagnostic."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice58_catalog_preview as previous
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import paper_data_suite.evergreen_witness_selected_stage as module
from paper_data_suite.evergreen_activation_slots import (
    UntrustedSlotSelection,
    _selection_bytes,
)
from paper_data_suite.evergreen_active_receipts import (
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_stage_correlation import (
    CatalogStageCorrelation,
    CatalogStageCorrelationError,
    CatalogStagedWheel,
)
from paper_data_suite.evergreen_catalog_verification import (
    TrustedKeyring,
    TrustedPublicKey,
)
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_publisher_pip_preflight import (
    ObservedPublisherPipCandidate,
    PublisherPipPreflightError,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageError,
    inspect_witness_pinned_selected_staged_bytes,
)

NOW = datetime(2026, 10, 25, 15, tzinfo=UTC)
TX = "f" * 32
INSTALL = "a" * 32
WITNESS = "independent_witness"
REGISTRY = "a" * 64
PUBLISHER = "d" * 64
PIP = "1" * 64
NATIVE = "2" * 64
CONSOLES = (("pds-quillan", "quillan", "quillan.cli:main"),)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "software"
    workspace = tmp_path / "classroom"
    stage = root / "candidate" / "slot"
    wheels = root / "candidate" / "wheels"
    workspace.mkdir()
    stage.mkdir(parents=True)
    wheels.mkdir(parents=True)
    (workspace / "student.txt").write_text("do not touch classroom evidence")
    (stage / "installed.txt").write_text("staged bytes")
    prepared, registry, lock, native = b"prepared", b"registry", b"lock", b"native"
    candidate = ObservedJournalPipCandidate(
        TX,
        1,
        "candidate/slot",
        "candidate/wheels",
        NATIVE,
        PIP,
        (("quillan", PUBLISHER),),
        CONSOLES,
        ("packaging",),
    )
    receipt = make_untrusted_active_receipt(
        candidate,
        prepared_record=prepared,
        registry_envelope=registry,
        lock_envelope=lock,
        native_envelope=native,
        generation=1,
        recorded_at=NOW - timedelta(minutes=1),
        previous=None,
    )
    selected = _selection_bytes(
        UntrustedSlotSelection(TX, "candidate/slot", sha(prepared), sha(native), 1)
    )
    (root / "candidate-selection.json").write_bytes(selected)
    private = Ed25519PrivateKey.generate()
    store = MonotonicCheckpointStore(
        sqlite3.connect(":memory:", isolation_level=None),
        witness_id=WITNESS,
        authorize=lambda install, operation, context: (
            install == INSTALL and context == "operator"
        ),
        sign=private.sign,
    )
    store.commit_receipt(INSTALL, receipt, context="operator")
    requests: list[bytes] = []

    def transport(challenge: bytes) -> bytes:
        requests.append(challenge)
        return store.answer_challenge(challenge, context="operator", now=NOW)

    snapshot = previous.fixture_snapshot()
    signing = Ed25519PrivateKey.generate()
    trust = TrustedKeyring(
        (
            TrustedPublicKey(
                "root-key",
                signing.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
            ),
        ),
        ("root-key",),
    )
    staged = CatalogStageCorrelation(
        TX,
        REGISTRY,
        PIP,
        NATIVE,
        (CatalogStagedWheel("quillan", "pds-quillan", "0.8.0", "b" * 64, PUBLISHER),),
    )
    pip = ObservedPublisherPipCandidate(
        TX,
        stage,
        wheels,
        REGISTRY,
        "c" * 64,
        PIP,
        (("quillan", PUBLISHER),),
        CONSOLES,
        ("packaging",),
        ("Scripts/quillan.exe",),
    )
    calls: list[str] = []

    def stage_audit(*args: Any, **kwargs: Any) -> CatalogStageCorrelation:
        calls.append("stage")
        assert args == (snapshot, stage, wheels)
        assert kwargs["trust"] is trust
        return staged

    def pip_audit(*args: Any, **kwargs: Any) -> ObservedPublisherPipCandidate:
        calls.append("pip")
        assert args == (stage, wheels)
        return pip

    monkeypatch.setattr(module, "inspect_catalog_bound_staged_bytes", stage_audit)
    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", pip_audit)
    args: dict[str, Any] = {
        "snapshot": snapshot,
        "software_root": root,
        "classroom_workspace": workspace,
        "receipt_bytes": receipt,
        "installation_id": INSTALL,
        "expected_witness_id": WITNESS,
        "witness_transport": transport,
        "pinned_witness_public_key": private.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        ),
        "prepared_record": prepared,
        "registry_envelope": registry,
        "lock_envelope": lock,
        "module_envelopes": {"quillan": b"publisher"},
        "native_envelope": native,
        "trust": trust,
        "now": NOW,
    }
    return {
        "args": args,
        "root": root,
        "workspace": workspace,
        "stage": stage,
        "requests": requests,
        "calls": calls,
        "store": store,
        "pip": pip,
        "staged": staged,
        "receipt": receipt,
        "selection": selected,
    }


def run(ready: dict[str, Any], **change: Any) -> Any:
    return inspect_witness_pinned_selected_staged_bytes(**{**ready["args"], **change})


def test_signed_witness_read_twice_after_rechecking_physical_stage(
    ready: dict[str, Any],
) -> None:
    root = ready["root"]
    workspace = ready["workspace"]
    before = {
        f.relative_to(root): f.read_bytes() for f in root.rglob("*") if f.is_file()
    }
    with (
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("subprocess.run", side_effect=AssertionError("execution")),
    ):
        observed = run(ready)
    assert observed.status == "WITNESS_PINNED_SELECTED_STAGED_BYTES_OBSERVED_ONLY"
    assert observed.authority == (
        "NO_ACTIVE_LAUNCH_RECEIPT_WRITE_OR_ACTIVATION_AUTHORITY"
    )
    assert observed.receipt_sha256 == sha(ready["receipt"])
    assert observed.witness_revision == 1
    assert observed.generation == 1
    assert observed.pip_inventory_sha256 == PIP
    assert observed.native_payload_sha256 == NATIVE
    assert ready["calls"] == ["stage", "pip"]
    assert len(ready["requests"]) == 2
    assert ready["requests"][0] != ready["requests"][1]
    after = {
        f.relative_to(root): f.read_bytes() for f in root.rglob("*") if f.is_file()
    }
    assert after == before
    assert (workspace / "student.txt").read_text() == "do not touch classroom evidence"
    for name in ("launch", "activate", "commit", "rollback", "write_receipt"):
        assert not hasattr(observed, name)


@pytest.mark.parametrize(
    "change",
    [
        {"snapshot": object()},
        {"software_root": "not-a-path"},
        {"trust": None},
        {"now": datetime(2026, 10, 25, 15)},
        {"pinned_witness_public_key": "not-bytes"},
        {"module_envelopes": {}},
    ],
)
def test_invalid_input_never_queries_witness(
    ready: dict[str, Any], change: dict[str, Any]
) -> None:
    with pytest.raises(WitnessSelectedStageError, match="inputs"):
        run(ready, **change)
    assert ready["requests"] == []


def test_missing_selection_refuses_before_network(ready: dict[str, Any]) -> None:
    (ready["root"] / "candidate-selection.json").unlink()
    with pytest.raises(WitnessSelectedStageError, match="selected slot"):
        run(ready)
    assert ready["requests"] == []


def test_pending_recovery_refuses_before_network(ready: dict[str, Any]) -> None:
    (ready["root"] / "pending-slot-recovery.json").write_bytes(b"pending")
    with pytest.raises(WitnessSelectedStageError):
        run(ready)
    assert ready["requests"] == []


def test_different_local_selection_refuses(ready: dict[str, Any]) -> None:
    (ready["root"] / "candidate-selection.json").write_bytes(
        _selection_bytes(
            UntrustedSlotSelection(
                TX, "candidate/slot", sha(b"wrong"), sha(b"native"), 1
            )
        )
    )
    with pytest.raises(WitnessSelectedStageError, match="selected slot"):
        run(ready)
    assert ready["requests"] == []


@pytest.mark.parametrize(
    "field",
    ["registry_envelope", "lock_envelope", "prepared_record", "native_envelope"],
)
def test_modified_signed_input_refuses_before_network(
    ready: dict[str, Any], field: str
) -> None:
    with pytest.raises(WitnessSelectedStageError):
        run(ready, **{field: b"different"})
    assert ready["requests"] == []


def test_wrong_witness_pinned_key_refuses_without_physical_audit(
    ready: dict[str, Any],
) -> None:
    private = Ed25519PrivateKey.generate()
    with pytest.raises(WitnessSelectedStageError, match="signed witness"):
        run(
            ready,
            pinned_witness_public_key=private.public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw
            ),
        )
    assert ready["calls"] == []


def test_wrong_witness_installation_refuses(ready: dict[str, Any]) -> None:
    with pytest.raises(WitnessSelectedStageError):
        run(ready, installation_id="b" * 32)
    assert ready["calls"] == []


def test_modified_physical_candidate_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise CatalogStageCorrelationError("tampered")

    monkeypatch.setattr(module, "inspect_catalog_bound_staged_bytes", fail)
    with pytest.raises(WitnessSelectedStageError, match="physical"):
        run(ready)
    assert len(ready["requests"]) == 1


def test_console_target_drift_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "audit_publisher_bound_pip_candidate",
        lambda *a, **k: replace(ready["pip"], root_console_targets=()),
    )
    with pytest.raises(WitnessSelectedStageError, match="console"):
        run(ready)


def test_external_dependency_drift_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "audit_publisher_bound_pip_candidate",
        lambda *a, **k: replace(ready["pip"], external_distributions=()),
    )
    with pytest.raises(WitnessSelectedStageError, match="console"):
        run(ready)


def test_selected_slot_drift_after_audits(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_audit = module.audit_publisher_bound_pip_candidate

    def mutate(*args: Any, **kwargs: Any) -> Any:
        result = previous_audit(*args, **kwargs)
        (ready["root"] / "candidate-selection.json").unlink()
        return result

    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", mutate)
    with pytest.raises(WitnessSelectedStageError, match="selected slot changed"):
        run(ready)
    assert len(ready["requests"]) == 1


def test_head_advancement_between_queries_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = module.query_checkpoint_witness
    observed = 0

    def change(*args: Any, **kwargs: Any) -> Any:
        nonlocal observed
        observed += 1
        result = original(*args, **kwargs)
        if observed == 2:
            return replace(result, witness_revision=result.witness_revision + 1)
        return result

    monkeypatch.setattr(module, "query_checkpoint_witness", change)
    with pytest.raises(WitnessSelectedStageError, match="witness head"):
        run(ready)


def test_stage_hash_mismatch_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "inspect_catalog_bound_staged_bytes",
        lambda *a, **k: replace(ready["staged"], pip_inventory_sha256="0" * 64),
    )
    with pytest.raises(WitnessSelectedStageError, match="audited stage"):
        run(ready)


def test_classroom_software_overlap_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(WitnessSelectedStageError):
        run(ready, classroom_workspace=ready["root"])
    assert ready["requests"] == []


def test_pip_audit_failure_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise PublisherPipPreflightError("changed package")

    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", fail)
    with pytest.raises(WitnessSelectedStageError, match="physical"):
        run(ready)
