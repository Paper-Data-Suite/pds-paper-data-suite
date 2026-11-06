"""Slice 117: prepare a new-install CAS proposal without authority or I/O."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from paper_data_suite import evergreen_windows_installer_checkpoint_cas as target
from paper_data_suite.evergreen_windows_installer_intent import _PHASES
from paper_data_suite.evergreen_windows_installer_trust_checkpoint_review import (
    InstallerTrustCheckpointReview,
)

_POLICY_SHA = "a" * 64
_REGISTRY_SHA = "b" * 64
_LOCK_SHA = "c" * 64
_NAMES = ("paper-data-suite", "pds-core", "quillan")


def _canon(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _intent() -> bytes:
    return _canon(
        {
            "schema": 1,
            "operation": "NEW_PROTECTED_WINDOWS_INSTALLATION",
            "service_name": "PaperDataSuiteService",
            "transaction_id": "d" * 32,
            "catalog_sha256": _REGISTRY_SHA,
            "recovery_basis_sha256": "e" * 64,
            "artifacts": [
                {"distribution": name, "version": "1.2.3", "sha256": "f" * 64}
                for name in _NAMES
            ],
            "requested_phases": list(_PHASES),
        }
    )


def _review(raw: bytes | None = None) -> InstallerTrustCheckpointReview:
    raw = _intent() if raw is None else raw
    return InstallerTrustCheckpointReview(
        status="PINNED_TRUST_AND_REVISION_EVIDENCE_MATCH_SIGNED_WHEELS_ONLY",
        request_sha256=hashlib.sha256(raw).hexdigest(),
        trust_policy_sha256=_POLICY_SHA,
        trust_policy_revision=3,
        registry_payload_sha256=_REGISTRY_SHA,
        registry_revision=5,
        signed_lock_payload_sha256=_LOCK_SHA,
        signed_lock_revision=7,
        artifact_distributions=_NAMES,
        dependency_edge_count=3,
    )


def _genesis() -> dict[str, object]:
    return {
        "schema": 1,
        "generation": 0,
        "trust_policy_sha256": _POLICY_SHA,
        "trust_policy_revision": 3,
        "registry_revision": 0,
        "registry_sha256": "0" * 64,
        "lock_revision": 0,
        "lock_sha256": "0" * 64,
        "last_transaction_id": "0" * 32,
        "last_request_sha256": "0" * 64,
    }


def _propose(
    raw: bytes | None = None,
    review: InstallerTrustCheckpointReview | None = None,
    previous: bytes | None = None,
) -> target.CheckpointCasProposal:
    return target.propose_installer_checkpoint_cas(
        _intent() if raw is None else raw,
        review=_review() if review is None else review,
        claimed_previous_bytes=_canon(_genesis()) if previous is None else previous,
    )


def test_genesis_proposal_is_canonical_deterministic_and_unprivileged() -> None:
    result = _propose()
    assert result == _propose()
    assert result.status == "PROPOSED_PROTECTED_CHECKPOINT_CAS_NOT_APPLIED"
    assert (
        result.expected_previous_sha256
        == hashlib.sha256(_canon(_genesis())).hexdigest()
    )
    assert result.expected_generation == 0
    assert result.proposed_generation == 1
    assert (
        result.proposed_record_sha256
        == hashlib.sha256(result.proposed_record_bytes).hexdigest()
    )
    obj = target.parse_claimed_checkpoint(result.proposed_record_bytes)
    assert obj["last_transaction_id"] == "d" * 32
    assert obj["last_request_sha256"] == hashlib.sha256(_intent()).hexdigest()
    assert obj["trust_policy_sha256"] == _POLICY_SHA
    assert obj["registry_revision"] == 5
    assert obj["lock_revision"] == 7
    assert b"recovery_basis" not in result.proposed_record_bytes
    assert all(
        getattr(result, name) is False
        for name in (
            "protected_baseline_authenticated",
            "atomic_write_performed",
            "service_or_admin_authenticated",
            "authorized_to_provision",
            "authorized_to_register_service",
            "authorized_to_publish_receipt",
            "authorized_to_activate_or_launch",
        )
    )
    assert result.authority == target._NO_AUTHORITY


def test_replay_against_previous_new_install_checkpoint_refuses() -> None:
    previous = _propose().proposed_record_bytes
    with pytest.raises(target.InstallerCheckpointCasError, match="replay"):
        _propose(previous=previous)


def test_other_new_install_transaction_cannot_replace_previous_install() -> None:
    old = _propose().proposed_record_bytes
    mutated = json.loads(_intent())
    mutated["transaction_id"] = "a" * 32
    raw = _canon(mutated)
    with pytest.raises(
        target.InstallerCheckpointCasError, match="existing installation"
    ):
        _propose(raw=raw, review=_review(raw), previous=old)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "ADMIN_AUTHORIZED"),
        ("request_sha256", "1" * 64),
        ("registry_payload_sha256", "1" * 64),
        ("artifact_distributions", ("paper-data-suite", "pds-core")),
        ("authority", "AUTHORIZED"),
        ("pin_independently_provisioned", True),
        ("checkpoint_custody_independently_established", True),
        ("administrator_authenticated", True),
        ("authorized_to_provision", True),
        ("authorized_to_register_service", True),
        ("authorized_to_publish_receipt", True),
        ("authorized_to_activate_or_launch", True),
    ],
    ids=(
        "false-status",
        "wrong-request",
        "wrong-registry",
        "wrong-artifacts",
        "forged-authority",
        "fake-pin",
        "fake-custody",
        "fake-admin",
        "fake-provision",
        "fake-scm",
        "fake-receipt",
        "fake-launch",
    ),
)
def test_inconsistent_or_authorizing_review_refuses(field: str, value: object) -> None:
    with pytest.raises(target.InstallerCheckpointCasError):
        _propose(review=replace(_review(), **{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("trust_policy_sha256", "1" * 64),
        ("trust_policy_revision", 4),
        ("registry_revision", 1),
        ("registry_sha256", "1" * 64),
        ("lock_revision", 1),
        ("lock_sha256", "1" * 64),
        ("generation", 1),
        ("last_transaction_id", "e" * 32),
        ("last_request_sha256", "e" * 64),
        ("schema", 2),
    ],
    ids=(
        "rotated-pin",
        "rotated-policy",
        "genesis-reg-rev",
        "genesis-reg-hash",
        "genesis-lock-rev",
        "genesis-lock-hash",
        "not-genesis",
        "genesis-tx",
        "genesis-request",
        "bad-schema",
    ),
)
def test_wrong_genesis_or_root_rotation_refuses(field: str, value: object) -> None:
    data = {**_genesis(), field: value}
    with pytest.raises(target.InstallerCheckpointCasError):
        _propose(previous=_canon(data))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"not-json",
        b"\xff",
        b" " + _canon(_genesis()),
        _canon(_genesis()) + b"\n",
        b"x" * 4097,
        _canon(_genesis()).replace(b'"schema":1', b'"schema":1,"schema":1'),
    ],
    ids=(
        "empty",
        "unknown-schema",
        "bad-json",
        "invalid-utf8",
        "leading-space",
        "trailing-newline",
        "oversized",
        "duplicate-field",
    ),
)
def test_invalid_previous_bytes_refuse(raw: bytes) -> None:
    with pytest.raises(target.InstallerCheckpointCasError):
        _propose(previous=raw)


def test_boolean_revision_and_surplus_fields_refuse() -> None:
    data = _genesis()
    data["generation"] = False
    with pytest.raises(target.InstallerCheckpointCasError):
        _propose(previous=_canon(data))
    data = _genesis()
    data["unexpected_authorization"] = True
    with pytest.raises(target.InstallerCheckpointCasError):
        _propose(previous=_canon(data))


def test_review_signed_revision_bounds_refuse() -> None:
    for field, value in (
        ("registry_revision", 0),
        ("signed_lock_revision", 2**53),
        ("trust_policy_revision", True),
        ("signed_lock_payload_sha256", "0" * 64),
    ):
        with pytest.raises(target.InstallerCheckpointCasError):
            _propose(review=replace(_review(), **{field: value}))


def test_prior_claimed_new_install_guard_has_no_disk_io(tmp_path) -> None:
    before = list(tmp_path.iterdir())
    result = _propose()
    assert result.proposed_record_bytes
    assert list(tmp_path.iterdir()) == before


def test_no_public_apply_or_writer_api() -> None:
    assert not hasattr(target, "install")
    assert not hasattr(target, "apply")
    assert not hasattr(target, "write_checkpoint")
    assert not hasattr(target, "main")
    assert target.__all__ == (
        "CheckpointCasProposal",
        "InstallerCheckpointCasError",
        "parse_claimed_checkpoint",
        "propose_installer_checkpoint_cas",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("registry_revision", 6),
        ("registry_sha256", "f" * 64),
        ("lock_revision", 8),
        ("lock_sha256", "e" * 64),
    ],
    ids=(
        "registry-rollback",
        "registry-equivocation",
        "lock-rollback",
        "lock-equivocation",
    ),
)
def test_existing_record_revision_regressions_refuse(field: str, value: object) -> None:
    previous = target.parse_claimed_checkpoint(_propose().proposed_record_bytes)
    previous[field] = value
    with pytest.raises(target.InstallerCheckpointCasError):
        _propose(previous=_canon(previous))


def test_forced_wrong_transaction_correlation_refuses() -> None:
    raw = _intent().replace(b'"transaction_id":"dddd', b'"transaction_id":"cccc')
    with pytest.raises(target.InstallerCheckpointCasError):
        _propose(raw=raw)


def test_previous_record_must_not_assert_privileges() -> None:
    old = _genesis()
    old["administrator_approved"] = True
    with pytest.raises(target.InstallerCheckpointCasError, match="schema"):
        target.parse_claimed_checkpoint(_canon(old))
