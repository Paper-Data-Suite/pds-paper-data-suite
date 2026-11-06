"""Slice 47: signed successor bytes need fresh physical readback, never launch."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite.evergreen_activation_slots import (
    PendingSlotRecovery,
    UntrustedSlotSelection,
    _recovery_bytes,
    _selection_bytes,
)
from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_verification import (
    TrustedKeyring,
    TrustedPublicKey,
)
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_forward_byte_requalification import (
    ForwardByteRequalificationError,
    requalify_witnessed_successor_bytes,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_local_receipt_recovery import (
    inspect_pending_forward_recovery,
    persist_untrusted_successor_proposal,
)
from paper_data_suite.evergreen_native_evidence import NativeEvidenceError
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
from paper_data_suite.evergreen_publisher_pip_preflight import (
    PublisherPipPreflightError,
)
from paper_data_suite.evergreen_recovery_convergence import (
    compare_recovery_convergence,
)
from paper_data_suite.evergreen_successor_receipt_draft import (
    WitnessBoundSuccessorDraft,
)
from paper_data_suite.evergreen_update_journal import (
    UntrustedUpdateJournal,
    UpdatePhase,
    _serialize,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    make_witness_commit_request,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)

NOW = datetime(2026, 10, 21, 19, tzinfo=UTC)
INSTALL = "a" * 32
OLD = "b" * 32
NEW = "c" * 32
WITNESS = "independent_witness"
CONTEXT = "service-operator"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidate(tx: str, stage: str, wheels: str) -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        tx,
        1,
        stage,
        wheels,
        "3" * 64,
        "4" * 64,
        (("quillan", "5" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "software"
    workspace = tmp_path / "classroom"
    root.mkdir()
    workspace.mkdir()
    (root / "transactions").mkdir()
    for part in ("prior/one", "prior/wheels", "candidate/two", "candidate/wheels"):
        (root / part).mkdir(parents=True)
    candidate_file = root / "candidate/two/bytes.bin"
    candidate_file.write_bytes(b"good candidate")
    old = ProposedCandidateEvidence(b"p", b"r", b"l", b"n")
    new = ProposedCandidateEvidence(b"P", b"R", b"L", b"N")
    prior = make_untrusted_active_receipt(
        candidate(OLD, "prior/one", "prior/wheels"),
        prepared_record=old.prepared_record,
        registry_envelope=old.registry_envelope,
        lock_envelope=old.lock_envelope,
        native_envelope=old.native_envelope,
        generation=1,
        recorded_at=NOW - timedelta(minutes=2),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        candidate(NEW, "candidate/two", "candidate/wheels"),
        prepared_record=new.prepared_record,
        registry_envelope=new.registry_envelope,
        lock_envelope=new.lock_envelope,
        native_envelope=new.native_envelope,
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, sha(prior)),
    )
    old_pointer = _selection_bytes(
        UntrustedSlotSelection(OLD, "prior/one", sha(b"p"), sha(b"n"), 1)
    )
    selected = _selection_bytes(
        UntrustedSlotSelection(NEW, "candidate/two", sha(b"P"), sha(b"N"), 2)
    )
    (root / "candidate-selection.json").write_bytes(selected)
    (root / "pending-slot-recovery.json").write_bytes(
        _recovery_bytes(
            PendingSlotRecovery(NEW, old_pointer, sha(selected), sha(old_pointer))
        )
    )
    journal_file = root / "transactions" / f"{NEW}.json"
    journal_file.write_bytes(
        _serialize(
            UntrustedUpdateJournal(
                NEW,
                2,
                UpdatePhase.ACTIVATION_INTENT,
                NOW - timedelta(seconds=30),
                "candidate/two",
                "candidate/wheels",
                sha(b"P"),
                sha(b"R"),
                sha(b"L"),
                sha(b"N"),
                sha(b"prior record"),
            )
        )
    )
    signer = Ed25519PrivateKey.generate()
    verifier = signer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    store = MonotonicCheckpointStore(
        sqlite3.connect(":memory:", isolation_level=None),
        witness_id=WITNESS,
        authorize=lambda identity, operation, context: (
            identity == INSTALL and context == CONTEXT
        ),
        sign=signer.sign,
    )
    store.commit_receipt(INSTALL, prior, context=CONTEXT)

    def transport(challenge: bytes) -> bytes:
        return store.answer_challenge(challenge, context=CONTEXT, now=NOW)

    draft = WitnessBoundSuccessorDraft(
        NEW, 1, 2, sha(prior), 1, sha(successor), successor
    )
    persist_untrusted_successor_proposal(
        root,
        classroom_workspace=workspace,
        transaction_id=NEW,
        draft=draft,
        previous_receipt_bytes=prior,
        installation_id=INSTALL,
        witness_id=WITNESS,
        witness_transport=transport,
        pinned_public_key=verifier,
        now=NOW,
    )
    store.commit_receipt(INSTALL, successor, context=CONTEXT)
    local = inspect_pending_forward_recovery(
        root,
        classroom_workspace=workspace,
        transaction_id=NEW,
        witness_transport=transport,
        pinned_public_key=verifier,
        now=NOW,
    )
    request = make_witness_commit_request(
        draft,
        installation_id=INSTALL,
        witness_id=WITNESS,
        previous_receipt_bytes=prior,
    )
    service = WitnessWriterQuiescenceState(
        INSTALL,
        sha(serialize_witness_commit_request(request)),
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        2,
        sha(successor),
    )
    finding = compare_recovery_convergence(request, service=service, local=local)
    trust_signer = Ed25519PrivateKey.generate()
    trust = TrustedKeyring(
        (
            TrustedPublicKey(
                "root_key",
                trust_signer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
            ),
        ),
        ("root_key",),
    )
    counts = {"pip": 0, "native": 0}

    def fake_pip(stage: Path, wheels: Path, **kwargs: Any) -> SimpleNamespace:
        counts["pip"] += 1
        if candidate_file.read_bytes() != b"good candidate":
            raise PublisherPipPreflightError("changed candidate bytes")
        return SimpleNamespace(
            transaction_id=NEW,
            stage_root=stage,
            wheelhouse=wheels,
            pip_inventory_sha256="4" * 64,
            publisher_digests=(("quillan", "5" * 64),),
            root_console_targets=(("quillan", "quillan", "quillan.cli:main"),),
            external_distributions=("pds-core",),
        )

    def fake_native(stage: Path, wheels: Path, **kwargs: Any) -> SimpleNamespace:
        counts["native"] += 1
        if candidate_file.read_bytes() != b"good candidate":
            raise NativeEvidenceError("changed native bytes")
        return SimpleNamespace(
            transaction_id=NEW, stage_root=stage, payload_sha256="3" * 64
        )

    import paper_data_suite.evergreen_forward_byte_requalification as module

    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", fake_pip)
    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", fake_native)
    args: dict[str, Any] = {
        "software_root": root,
        "classroom_workspace": workspace,
        "transaction_id": NEW,
        "convergence": finding,
        "candidate": new,
        "candidate_module_envelopes": {"quillan": b"module"},
        "trust": trust,
        "witness_transport": transport,
        "pinned_public_key": verifier,
        "now": NOW,
    }
    return {
        "args": args,
        "root": root,
        "workspace": workspace,
        "file": candidate_file,
        "counts": counts,
        "store": store,
        "prior": prior,
        "successor": successor,
        "journal": journal_file,
        "proposal": root / "transactions" / f"{NEW}.successor-proposal.json",
    }


def run(ready: dict[str, Any], **change: Any) -> Any:
    return requalify_witnessed_successor_bytes(**{**ready["args"], **change})


def test_twice_audited_successor_is_still_not_activated(ready: dict[str, Any]) -> None:
    (ready["workspace"] / "teacher.txt").write_text("keep")
    before = {
        p.relative_to(ready["root"]): p.read_bytes()
        for p in ready["root"].rglob("*")
        if p.is_file()
    }
    result = run(ready)
    assert result.status == (
        "POST_CAS_SIGNED_BYTES_OBSERVED_FORWARD_RECOVERY_STILL_REQUIRED"
    )
    assert result.authority == "NO_LAUNCH_ROLLBACK_OR_RECEIPT_COMMIT_AUTHORITY"
    assert result.successor_receipt_sha256 == sha(ready["successor"])
    assert result.pip_inventory_sha256 == "4" * 64
    assert result.native_payload_sha256 == "3" * 64
    assert result.witness_revision == 2 and result.generation == 2
    assert ready["counts"] == {"pip": 2, "native": 2}
    assert all(
        p.read_bytes() == content
        for name, content in before.items()
        for p in (ready["root"] / name,)
    )
    assert (ready["workspace"] / "teacher.txt").read_text() == "keep"
    assert not hasattr(result, "activate") and not hasattr(result, "clear_recovery")


def test_prior_head_refused_after_proposal(ready: dict[str, Any]) -> None:
    request = ready["args"]["convergence"]
    prior_claim = replace(request, finding="MATCHED_PRIOR_HEAD_REVIEW_STILL_REQUIRED")
    with pytest.raises(ForwardByteRequalificationError, match="invalid"):
        run(ready, convergence=prior_claim)


@pytest.mark.parametrize(
    "field,value",
    [
        ("convergence", None),
        ("trust", None),
        ("candidate_module_envelopes", {}),
        ("pinned_public_key", b"X"),
        ("now", datetime(2026, 10, 21)),
        ("now", NOW.replace(microsecond=1)),
        ("layout", "windows" if os.name != "nt" else "posix"),
    ],
)
def test_bounded_inputs_refused(ready: dict[str, Any], field: str, value: Any) -> None:
    with pytest.raises(ForwardByteRequalificationError):
        run(ready, **{field: value})


def test_untrusted_proposal_missing_is_not_success(ready: dict[str, Any]) -> None:
    ready["proposal"].unlink()
    with pytest.raises(ForwardByteRequalificationError, match="missing"):
        run(ready)


def test_modified_pending_journal_rejected(ready: dict[str, Any]) -> None:
    ready["journal"].write_bytes(b"corrupt")
    with pytest.raises(ForwardByteRequalificationError):
        run(ready)


def test_modified_recovery_capsule_rejected(ready: dict[str, Any]) -> None:
    (ready["root"] / "pending-slot-recovery.json").write_bytes(b"corrupt")
    with pytest.raises(ForwardByteRequalificationError):
        run(ready)


def test_wrong_candidate_inputs_refused_before_network(ready: dict[str, Any]) -> None:
    wrong = replace(ready["args"]["candidate"], lock_envelope=b"tampered")
    with pytest.raises(ForwardByteRequalificationError, match="identity"):
        run(ready, candidate=wrong)
    assert ready["counts"] == {"pip": 0, "native": 0}


def test_corrupt_candidate_pip_files_refused(ready: dict[str, Any]) -> None:
    ready["file"].write_bytes(b"changed")
    with pytest.raises(ForwardByteRequalificationError):
        run(ready)


def test_candidate_bytes_changed_during_witness_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(challenge: bytes) -> bytes:
        response = original(challenge)
        ready["file"].write_bytes(b"changed")
        return response

    with pytest.raises(ForwardByteRequalificationError):
        run(ready, witness_transport=tamper)
    assert ready["counts"]["pip"] == 2


def test_incorrect_pip_inventory_digest_fails_closed(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import paper_data_suite.evergreen_forward_byte_requalification as module

    original = module.audit_publisher_bound_pip_candidate

    def wrong(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            **{**vars(original(*args, **kwargs)), "pip_inventory_sha256": "0" * 64}
        )

    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", wrong)
    with pytest.raises(ForwardByteRequalificationError, match="installed"):
        run(ready)


def test_native_payload_mismatch_fails_closed(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import paper_data_suite.evergreen_forward_byte_requalification as module

    original = module.verify_signed_staged_native_evidence

    def wrong(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            **{**vars(original(*args, **kwargs)), "payload_sha256": "0" * 64}
        )

    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", wrong)
    with pytest.raises(ForwardByteRequalificationError, match="installed"):
        run(ready)


def test_second_pass_audit_is_mandatory(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import paper_data_suite.evergreen_forward_byte_requalification as module

    original = module.verify_signed_staged_native_evidence

    def fail_second(*args: Any, **kwargs: Any) -> Any:
        if ready["counts"]["native"] == 1:
            raise NativeEvidenceError("second native audit refused")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", fail_second)
    with pytest.raises(ForwardByteRequalificationError):
        run(ready)


def test_witness_outage_refused_without_cleanup(ready: dict[str, Any]) -> None:
    def offline(challenge: bytes) -> bytes:
        raise ConnectionError("offline")

    with pytest.raises(ForwardByteRequalificationError):
        run(ready, witness_transport=offline)
    assert ready["proposal"].exists()
    assert (ready["root"] / "pending-slot-recovery.json").exists()


def test_wrong_witness_signer_is_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(ForwardByteRequalificationError):
        run(ready, pinned_public_key=b"0" * 32)


def test_mutated_selection_during_witness_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(challenge: bytes) -> bytes:
        response = original(challenge)
        (ready["root"] / "candidate-selection.json").write_bytes(b"corrupt")
        return response

    with pytest.raises(ForwardByteRequalificationError):
        run(ready, witness_transport=tamper)


def test_changed_proposal_during_witness_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(challenge: bytes) -> bytes:
        response = original(challenge)
        ready["proposal"].write_bytes(b"corrupt")
        return response

    with pytest.raises(ForwardByteRequalificationError, match="drifted"):
        run(ready, witness_transport=tamper)


def test_changed_module_map_during_witness_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(challenge: bytes) -> bytes:
        response = original(challenge)
        ready["args"]["candidate_module_envelopes"]["quillan"] = b"tampered"
        return response

    with pytest.raises(ForwardByteRequalificationError, match="drifted"):
        run(ready, witness_transport=tamper)


def test_witness_freshness_budget_enforced(ready: dict[str, Any]) -> None:
    import paper_data_suite.evergreen_forward_byte_requalification as module

    with patch.object(module.time, "monotonic", side_effect=[0.0, 46.0]):
        with pytest.raises(ForwardByteRequalificationError, match="freshness"):
            run(ready)


def test_existing_selection_lock_blocks_read(ready: dict[str, Any]) -> None:
    lock = ready["root"] / "candidate-selection.lock"
    lock.write_bytes(b"")
    with pytest.raises(ForwardByteRequalificationError, match="locked"):
        run(ready)
    assert lock.exists()


def test_no_process_launch_or_new_files(ready: dict[str, Any]) -> None:
    with patch("subprocess.run", side_effect=AssertionError("launch forbidden")):
        result = run(ready)
    assert result.authority.startswith("NO_LAUNCH")
    assert not (ready["root"] / "active-receipt.json").exists()
    assert (ready["root"] / "pending-slot-recovery.json").exists()
