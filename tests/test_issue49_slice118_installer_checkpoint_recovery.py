"""Slice 118: pure recovery classification cannot silently commit installation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from paper_data_suite import evergreen_windows_installer_checkpoint_recovery as target
from paper_data_suite.evergreen_windows_installer_checkpoint_cas import (
    CheckpointCasProposal,
    propose_installer_checkpoint_cas,
)
from paper_data_suite.evergreen_windows_installer_intent import _PHASES
from paper_data_suite.evergreen_windows_installer_trust_checkpoint_review import (
    InstallerTrustCheckpointReview,
)


def _canon(data: dict[str, object]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def _case() -> tuple[CheckpointCasProposal, bytes]:
    request = _canon(
        {
            "schema": 1,
            "operation": "NEW_PROTECTED_WINDOWS_INSTALLATION",
            "service_name": "PaperDataSuiteService",
            "transaction_id": "d" * 32,
            "catalog_sha256": "b" * 64,
            "recovery_basis_sha256": "e" * 64,
            "artifacts": [
                {"distribution": name, "version": "1.2.3", "sha256": "f" * 64}
                for name in ("paper-data-suite", "pds-core")
            ],
            "requested_phases": list(_PHASES),
        }
    )
    prev = _canon(
        {
            "schema": 1,
            "generation": 0,
            "trust_policy_sha256": "a" * 64,
            "trust_policy_revision": 3,
            "registry_revision": 0,
            "registry_sha256": "0" * 64,
            "lock_revision": 0,
            "lock_sha256": "0" * 64,
            "last_transaction_id": "0" * 32,
            "last_request_sha256": "0" * 64,
        }
    )
    review = InstallerTrustCheckpointReview(
        status="PINNED_TRUST_AND_REVISION_EVIDENCE_MATCH_SIGNED_WHEELS_ONLY",
        request_sha256=hashlib.sha256(request).hexdigest(),
        trust_policy_sha256="a" * 64,
        trust_policy_revision=3,
        registry_payload_sha256="b" * 64,
        registry_revision=5,
        signed_lock_payload_sha256="c" * 64,
        signed_lock_revision=7,
        artifact_distributions=("paper-data-suite", "pds-core"),
        dependency_edge_count=1,
    )
    return (
        propose_installer_checkpoint_cas(
            request, review=review, claimed_previous_bytes=prev
        ),
        prev,
    )


def _journal(phase: str = target._PREPARED) -> bytes:
    proposal, prev = _case()
    journal = json.loads(
        target.prepare_claimed_checkpoint_journal(proposal, claimed_previous_bytes=prev)
    )
    journal["phase"] = phase
    return _canon(journal)


@pytest.mark.parametrize(
    ("current", "phase", "status"),
    [
        (
            "old",
            "INTENT_PREPARED",
            "OLD_CHECKPOINT_REQUIRES_NATIVE_REVALIDATION_BEFORE_CAS",
        ),
        ("new", "INTENT_PREPARED", "REPLACEMENT_OBSERVED_JOURNAL_NOT_FINALIZED"),
        (
            "new",
            "CHECKPOINT_REPLACED_CLAIMED",
            "REPLACEMENT_CLAIMED_REQUIRES_NATIVE_COMMIT_ATTESTATION",
        ),
    ],
    ids=("intent-old", "intent-new", "replaced-new"),
)
def test_consistent_interruption_never_authorizes(
    current: str, phase: str, status: str
) -> None:
    proposal, prev = _case()
    checkpoint = prev if current == "old" else proposal.proposed_record_bytes
    outcome = target.classify_claimed_checkpoint_recovery(
        proposal,
        claimed_previous_bytes=prev,
        claimed_current_bytes=checkpoint,
        claimed_journal_bytes=_journal(phase),
    )
    assert outcome.status == status
    assert outcome.proposal_digest == proposal.proposed_record_sha256
    assert outcome.authority == target._NO_AUTHORITY
    assert all(
        getattr(outcome, key) is False
        for key in (
            "native_custody_verified",
            "durable_journal_verified",
            "independent_antirollback_verified",
            "permitted_to_discard_journal",
            "permitted_to_retry_replacement",
            "permitted_to_publish_receipt",
            "permitted_to_activate_or_launch",
        )
    )


def test_journal_is_canonical_reproducible_and_not_receipt() -> None:
    proposal, prev = _case()
    raw = target.prepare_claimed_checkpoint_journal(
        proposal, claimed_previous_bytes=prev
    )
    assert raw == _journal()
    parsed = target.parse_claimed_checkpoint_journal(raw)
    assert parsed["phase"] == "INTENT_PREPARED"
    assert parsed["transaction_id"] == "d" * 32
    assert parsed["proposed_checkpoint_sha256"] == proposal.proposed_record_sha256
    assert b"authorized" not in raw


def test_replaced_marker_with_previous_checkpoint_refuses() -> None:
    proposal, prev = _case()
    with pytest.raises(target.InstallerCheckpointRecoveryError, match="inconsistent"):
        target.classify_claimed_checkpoint_recovery(
            proposal,
            claimed_previous_bytes=prev,
            claimed_current_bytes=prev,
            claimed_journal_bytes=_journal(target._REPLACED),
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("transaction_id", "a" * 32),
        ("request_sha256", "a" * 64),
        ("previous_checkpoint_sha256", "b" * 64),
        ("proposed_checkpoint_sha256", "b" * 64),
        ("previous_generation", 1),
        ("proposed_generation", 2),
    ],
    ids=(
        "other-tx",
        "wrong-request",
        "wrong-previous",
        "wrong-new",
        "previous-gen",
        "new-gen",
    ),
)
def test_altered_journal_refuses(key: str, value: object) -> None:
    proposal, prev = _case()
    doc = json.loads(_journal())
    doc[key] = value
    with pytest.raises(target.InstallerCheckpointRecoveryError):
        target.classify_claimed_checkpoint_recovery(
            proposal,
            claimed_previous_bytes=prev,
            claimed_current_bytes=prev,
            claimed_journal_bytes=_canon(doc),
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema", True),
        ("schema", 2),
        ("phase", "COMMITTED"),
        ("transaction_id", "0" * 32),
        ("request_sha256", "0" * 64),
        ("previous_generation", False),
        ("proposed_generation", 0),
        ("proposed_checkpoint_sha256", "Z" * 64),
    ],
    ids=(
        "bool-schema",
        "bad-schema",
        "unknown-phase",
        "zero-tx",
        "zero-hash",
        "bool-gen",
        "missing-generation",
        "bad-sha",
    ),
)
def test_malformed_journal_field_refuses(key: str, value: object) -> None:
    doc = json.loads(_journal())
    doc[key] = value
    with pytest.raises(target.InstallerCheckpointRecoveryError):
        target.parse_claimed_checkpoint_journal(_canon(doc))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"junk",
        b"\xff",
        b" " + _journal(),
        _journal() + b"\n",
        b"x" * 4097,
        _journal().replace(b'"schema":1', b'"schema":1,"schema":1'),
    ],
    ids=(
        "empty",
        "missing-fields",
        "invalid-json",
        "bad-utf8",
        "extra-space",
        "trailing-newline",
        "oversized",
        "duplicate-key",
    ),
)
def test_invalid_journal_bytes_refuse(raw: bytes) -> None:
    with pytest.raises(target.InstallerCheckpointRecoveryError):
        target.parse_claimed_checkpoint_journal(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "COMPLETE"),
        ("authority", "APPROVED"),
        ("expected_generation", 1),
        ("proposed_generation", 2),
        ("expected_previous_sha256", "a" * 64),
        ("proposed_record_sha256", "b" * 64),
        ("request_sha256", "f" * 64),
        ("protected_baseline_authenticated", True),
        ("atomic_write_performed", True),
        ("service_or_admin_authenticated", True),
        ("authorized_to_provision", True),
        ("authorized_to_register_service", True),
        ("authorized_to_publish_receipt", True),
        ("authorized_to_activate_or_launch", True),
    ],
    ids=(
        "forged-status",
        "forged-authority",
        "bad-generation",
        "bad-next-gen",
        "bad-previous-hash",
        "bad-next-hash",
        "bad-request",
        "fake-baseline",
        "fake-write",
        "fake-admin",
        "fake-provision",
        "fake-scm",
        "fake-receipt",
        "fake-launch",
    ),
)
def test_forged_proposal_refuses(field: str, value: object) -> None:
    proposal, prev = _case()
    with pytest.raises(target.InstallerCheckpointRecoveryError):
        target.prepare_claimed_checkpoint_journal(
            replace(proposal, **{field: value}), claimed_previous_bytes=prev
        )


def test_other_checkpoint_bytes_refuse() -> None:
    proposal, prev = _case()
    mutated = json.loads(proposal.proposed_record_bytes)
    mutated["last_transaction_id"] = "e" * 32
    with pytest.raises(target.InstallerCheckpointRecoveryError):
        target.classify_claimed_checkpoint_recovery(
            proposal,
            claimed_previous_bytes=prev,
            claimed_current_bytes=_canon(mutated),
            claimed_journal_bytes=_journal(),
        )


def test_no_implicit_mutation_interface() -> None:
    import inspect

    source = inspect.getsource(target)
    for forbidden in (
        "subprocess",
        "os.replace",
        ".unlink(",
        "os.system",
        "winreg",
        "ctypes",
    ):
        assert forbidden not in source
