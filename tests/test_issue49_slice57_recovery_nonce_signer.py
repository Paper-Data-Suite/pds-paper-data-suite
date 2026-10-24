"""Slice 57: service-owned nonce burn, SQLite restart, and real host wiring."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from paper_data_suite.evergreen_recovery_nonce_signer import (
    DurableRecoveryNonceSigner,
    RecoveryNonceSignerError,
)

NOW = datetime(2026, 10, 24, 16, 0, 0, tzinfo=UTC)
DOMAIN = b"pds-evergreen-service-recovery-observation-v1\x00"
INSTALL = "a" * 32


def statement(
    *, challenge: bytes = b"R" * 32, when: datetime = NOW, **changes: Any
) -> bytes:
    fields: dict[str, Any] = {
        "installation_id": INSTALL,
        "transaction_id": "b" * 32,
        "request_sha256": "c" * 64,
        "predecessor_sha256": "d" * 64,
        "successor_sha256": "e" * 64,
        "witness_id": "independent_witness",
        "witness_revision": 2,
        "successor_generation": 2,
        "service_status": "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        "authority": "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY",
        "issued_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (when + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "challenge_b64": base64.b64encode(challenge).decode("ascii"),
    }
    fields.update(changes)
    return DOMAIN + json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    # The mTLS server runs on a separate thread. Its single-threaded request
    # loop and the test's sequential reads never use this connection concurrently.
    connection = sqlite3.connect(
        tmp_path / "protected-service.sqlite",
        isolation_level=None,
        check_same_thread=False,
    )
    yield connection
    connection.close()


def guarded(
    db: sqlite3.Connection,
    *,
    now: datetime = NOW,
    signer: Any = None,
) -> DurableRecoveryNonceSigner:
    key = Ed25519PrivateKey.generate()
    return DurableRecoveryNonceSigner(db, sign=signer or key.sign, clock=lambda: now)


def rows(db: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return db.execute("SELECT * FROM recovery_service_nonce_claims").fetchall()


def test_one_challenge_burns_before_any_repeat(db: sqlite3.Connection) -> None:
    signer = guarded(db)
    original = statement()
    assert len(signer(original)) == 64
    assert len(rows(db)) == 1
    assert rows(db)[0][0] == INSTALL
    assert rows(db)[0][1] == hashlib.sha256(b"R" * 32).hexdigest()
    with pytest.raises(RecoveryNonceSignerError, match="already consumed"):
        signer(original)
    assert len(rows(db)) == 1


def test_different_challenges_are_admitted(db: sqlite3.Connection) -> None:
    signer = guarded(db)
    assert len(signer(statement(challenge=b"A" * 32))) == 64
    assert len(signer(statement(challenge=b"B" * 32))) == 64
    assert len(rows(db)) == 2


def test_same_nonce_other_request_cannot_bypass(db: sqlite3.Connection) -> None:
    signer = guarded(db)
    signer(statement())
    with pytest.raises(RecoveryNonceSignerError, match="consumed"):
        signer(statement(transaction_id="f" * 32, request_sha256="f" * 64))


def test_replay_persists_across_reopening_and_another_signer(
    tmp_path: Path,
) -> None:
    path = tmp_path / "signer.sqlite"
    with sqlite3.connect(path, isolation_level=None) as first:
        guarded(first)(statement())
    with sqlite3.connect(path, isolation_level=None) as next_connection:
        second = guarded(next_connection)
        with pytest.raises(RecoveryNonceSignerError, match="consumed"):
            second(statement())
        assert len(second(statement(challenge=b"S" * 32))) == 64


def test_signer_failure_still_consumes_nonce(db: sqlite3.Connection) -> None:
    calls: list[bytes] = []

    def broken(value: bytes) -> bytes:
        calls.append(value)
        raise RuntimeError("signer offline")

    signer = guarded(db, signer=broken)
    with pytest.raises(RecoveryNonceSignerError, match="nonce consumed"):
        signer(statement())
    with pytest.raises(RecoveryNonceSignerError, match="already consumed"):
        signer(statement())
    assert len(calls) == 1
    assert len(rows(db)) == 1


@pytest.mark.parametrize("returned", [b"", b"short", b"x" * 65, "string"])
def test_invalid_signature_is_burned(db: sqlite3.Connection, returned: Any) -> None:
    signer = guarded(db, signer=lambda _: returned)
    with pytest.raises(RecoveryNonceSignerError, match="nonce consumed"):
        signer(statement())
    assert len(rows(db)) == 1


@pytest.mark.parametrize(
    "message",
    [
        b"garbage",
        b"wrong-domain\x00{}",
        DOMAIN + b"{}",
        DOMAIN + b"not json",
        DOMAIN + b"[]",
        statement(challenge=b"R" * 31),
        statement(challenge=b"R" * 33),
        statement(service_status="CAN_ROLLBACK"),
        statement(authority="CAN_ACTIVATE"),
        statement(installation_id="wrong"),
        statement(request_sha256="not-a-hash"),
        statement(issued_at="not-a-time"),
        statement(expires_at="2026-10-24T16:00:30Z"),
        statement(extra_field="unknown"),
        statement(witness_revision=True),
    ],
)
def test_incorrect_signing_contract_never_claims_nonce(
    db: sqlite3.Connection, message: bytes
) -> None:
    signer = guarded(db)
    with pytest.raises(RecoveryNonceSignerError):
        signer(message)
    assert rows(db) == []


def test_noncanonical_spacing_and_duplicate_json_fields_refuse(
    db: sqlite3.Connection,
) -> None:
    signer = guarded(db)
    pretty = (
        DOMAIN + json.dumps(json.loads(statement()[len(DOMAIN) :]), indent=2).encode()
    )
    duplicate = DOMAIN + b'{"issued_at":"now","issued_at":"then"}'
    for invalid in (pretty, duplicate):
        with pytest.raises(RecoveryNonceSignerError):
            signer(invalid)
    assert rows(db) == []


@pytest.mark.parametrize("delta", [-1, 6, 61])
def test_signed_time_cannot_drift_from_independent_service_clock(
    db: sqlite3.Connection, delta: int
) -> None:
    signer = guarded(db, now=NOW + timedelta(seconds=delta))
    with pytest.raises(RecoveryNonceSignerError, match="clock drift"):
        signer(statement())
    assert rows(db) == []


def test_service_clock_rollback_refuses_even_with_fresh_new_statement(
    db: sqlite3.Connection,
) -> None:
    guarded(db, now=NOW + timedelta(seconds=4))(
        statement(challenge=b"A" * 32, when=NOW + timedelta(seconds=4))
    )
    backward = guarded(db, now=NOW + timedelta(seconds=3))
    with pytest.raises(RecoveryNonceSignerError, match="clock moved backward"):
        backward(statement(challenge=b"B" * 32, when=NOW + timedelta(seconds=3)))
    assert len(rows(db)) == 1


def test_old_nonce_retention_is_bounded_by_stable_clock(
    db: sqlite3.Connection,
) -> None:
    guarded(db)(statement(challenge=b"A" * 32))
    later = NOW + timedelta(days=2)
    guarded(db, now=later)(statement(challenge=b"B" * 32, when=later))
    assert len(rows(db)) == 1
    assert rows(db)[0][1] == hashlib.sha256(b"B" * 32).hexdigest()
    with pytest.raises(RecoveryNonceSignerError, match="clock drift"):
        guarded(db, now=later)(statement(challenge=b"A" * 32))


def test_missing_persistent_database_and_active_transaction_refused() -> None:
    with sqlite3.connect(":memory:", isolation_level=None) as temporary:
        with pytest.raises(RecoveryNonceSignerError, match="persistent"):
            guarded(temporary)
    with sqlite3.connect(":memory:", isolation_level=None) as pending:
        pending.execute("BEGIN IMMEDIATE")
        with pytest.raises(RecoveryNonceSignerError, match="invalid service"):
            guarded(pending)
        pending.execute("ROLLBACK")


def test_unsafe_in_memory_journal_on_file_is_refused(tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "non_durable.sqlite", isolation_level=None) as db:
        assert db.execute("PRAGMA journal_mode=MEMORY").fetchone()[0] == "memory"
        with pytest.raises(RecoveryNonceSignerError, match="journal mode"):
            guarded(db)


def test_invalid_wall_clock_and_clock_exception_refused(
    db: sqlite3.Connection,
) -> None:
    key = Ed25519PrivateKey.generate()
    signer = DurableRecoveryNonceSigner(
        db, sign=key.sign, clock=lambda: NOW.replace(tzinfo=None)
    )
    with pytest.raises(RecoveryNonceSignerError, match="whole-second"):
        signer(statement())
    assert rows(db) == []
    failed = DurableRecoveryNonceSigner(db, sign=key.sign, clock=lambda: 1 / 0)
    with pytest.raises(RecoveryNonceSignerError, match="clock unavailable"):
        failed(statement())


def test_ledger_is_only_filesystem_change(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    student = tmp_path / "classroom" / "essay.txt"
    student.parent.mkdir()
    student.write_bytes(b"student data unchanged")
    with (
        patch("subprocess.run", side_effect=AssertionError("execute")),
        patch("socket.create_connection", side_effect=AssertionError("network")),
    ):
        guarded(db)(statement())
    assert student.read_bytes() == b"student data unchanged"


def test_real_mtls_server_wires_nonce_guard_and_refuses_replay(
    tmp_path: Path, db: sqlite3.Connection
) -> None:
    import threading

    import test_issue49_slice54_recovery_observation_server as previous

    tls = previous.tls.__wrapped__(tmp_path)
    case = previous.case.__wrapped__()
    guard = DurableRecoveryNonceSigner(
        db, sign=case["signing"].sign, clock=lambda: previous.NOW
    )
    server = previous._server(case, tls, sign=guard)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}
    )
    thread.start()
    try:
        status, payload, _ = previous._request(
            server.server_port, tls["client"], body=case["body"]
        )
        assert status == 200
        assert payload.startswith(b"{")
        assert len(rows(db)) == 1
        status, _, _ = previous._request(
            server.server_port, tls["client"], body=case["body"]
        )
        assert status == 503
        assert len(rows(db)) == 1
        assert case["calls"] == [
            "identify",
            "observe",
            "identify",
            "observe",
        ]  # Signing was delegated to the ledger, not the fixture's signer.
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
