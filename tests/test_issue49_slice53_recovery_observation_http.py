"""Slice 53: opt-in verified-peer service statement handler, no CAS or launch."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_recovery_observation_http import (
    ServiceRecoveryObservationHttpError,
    handle_service_recovery_observation,
    make_service_recovery_observation_request,
)
from paper_data_suite.evergreen_service_recovery_attestation import (
    verify_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceError,
    WitnessWriterQuiescenceState,
)

NOW = datetime(2026, 10, 22, 21, 30, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
CHALLENGE = b"V" * 32
PEER_DER = b"verified peer certificate placeholder for synthetic tests"
ROUTE = "/v1/recovery/service-observe"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _candidate(tx: str, stage: str, wheels: str) -> ObservedJournalPipCandidate:
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
def ready() -> dict[str, Any]:
    prior = make_untrusted_active_receipt(
        _candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"p",
        registry_envelope=b"r",
        lock_envelope=b"l",
        native_envelope=b"n",
        generation=1,
        recorded_at=NOW - timedelta(minutes=2),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        _candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"P",
        registry_envelope=b"R",
        lock_envelope=b"L",
        native_envelope=b"N",
        generation=2,
        recorded_at=NOW - timedelta(minutes=1),
        previous=ExternallyPinnedReceiptHead(1, sha(prior)),
    )
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, prior, successor)
    state = WitnessWriterQuiescenceState(
        INSTALL,
        sha(serialize_witness_commit_request(request)),
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        2,
        sha(successor),
    )
    key = Ed25519PrivateKey.generate()
    calls: dict[str, int] = {"identified": 0, "observed": 0, "signed": 0}
    context = object()

    def identify(fingerprint: str) -> object | None:
        calls["identified"] += 1
        return context if fingerprint == sha(PEER_DER) else None

    def observe(
        value: WitnessCommitRequest, service: object
    ) -> WitnessWriterQuiescenceState:
        calls["observed"] += 1
        assert value == request and service is context
        return state

    def sign(value: bytes) -> bytes:
        calls["signed"] += 1
        return key.sign(value)

    body = make_service_recovery_observation_request(request, challenge=CHALLENGE)
    return {
        "request": request,
        "state": state,
        "context": context,
        "key": key,
        "calls": calls,
        "inputs": {
            "method": "POST",
            "target": ROUTE,
            "headers": (
                ("Content-Type", "application/json"),
                ("Accept", "application/json"),
                ("Content-Length", str(len(body))),
            ),
            "body": body,
            "peer_der": PEER_DER,
            "identify_client": identify,
            "observe": observe,
            "sign": sign,
            "now": NOW,
        },
    }


def handle(ready: dict[str, Any], **changes: Any) -> Any:
    args: dict[str, Any] = {**ready["inputs"], **changes}
    if "body" in changes and "headers" not in changes and type(args["body"]) is bytes:
        args["headers"] = tuple(
            (
                name,
                str(len(args["body"])) if name.lower() == "content-length" else value,
            )
            for name, value in args["headers"]
        )
    return handle_service_recovery_observation(**args)


def test_good_request_returns_signed_challenge_bound_observation(
    ready: dict[str, Any],
) -> None:
    result = handle(ready)
    assert result.status == 200
    assert result.content_type == "application/json"
    observed = verify_service_recovery_attestation(
        result.body,
        request=ready["request"],
        challenge=CHALLENGE,
        pinned_service_public_key=ready["key"]
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw),
        now=NOW,
    )
    assert observed.transaction_id == NEXT
    assert observed.successor_sha256 == sha(ready["request"].successor_receipt_bytes)
    assert observed.authority == "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
    assert ready["calls"] == {"identified": 1, "observed": 1, "signed": 1}
    for name in ("activate", "rollback", "commit", "launch", "cleanup"):
        assert not hasattr(result, name)


def test_request_encoding_round_trips_exact_canonical_bytes(
    ready: dict[str, Any],
) -> None:
    raw = ready["inputs"]["body"]
    data = json.loads(raw)
    assert data["schema_version"] == 1
    assert base64.b64decode(data["challenge_b64"]) == CHALLENGE
    assert base64.b64decode(data["witness_request_b64"]) == (
        serialize_witness_commit_request(ready["request"])
    )
    assert raw == json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


@pytest.mark.parametrize("bad", [b"", b"short", b"x" * 31, b"x" * 33, None])
def test_client_cannot_make_invalid_challenge(ready: dict[str, Any], bad: Any) -> None:
    with pytest.raises(ServiceRecoveryObservationHttpError):
        make_service_recovery_observation_request(ready["request"], challenge=bad)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"method": "GET"}, 405),
        ({"method": "PUT"}, 405),
        ({"target": "/v1/receipt/head"}, 404),
        ({"target": ROUTE + "?x=y"}, 404),
        ({"body": b""}, 400),
        ({"body": b"x" * (48 * 1024 + 1)}, 413),
        ({"body": None}, 400),
        ({"peer_der": None}, 401),
        ({"peer_der": b""}, 401),
        ({"peer_der": b"x" * (64 * 1024 + 1)}, 401),
    ],
)
def test_pre_auth_refusals_do_not_call_service(
    ready: dict[str, Any], changes: dict[str, Any], code: int
) -> None:
    assert handle(ready, **changes).status == code
    assert ready["calls"] == {"identified": 0, "observed": 0, "signed": 0}


@pytest.mark.parametrize(
    "headers,expected",
    [
        ((("accept", "application/json"),), 415),
        ((("content-type", "text/plain"), ("accept", "application/json")), 415),
        ((("content-type", "application/json"), ("accept", "*/*")), 400),
        ((("content-type", "application/json"), ("accept", "application/json")), 400),
        (
            (
                ("content-type", "application/json"),
                ("content-type", "application/json"),
            ),
            400,
        ),
        ((("x-client-cert", "forged"),), 400),
        ((("Transfer-Encoding", "chunked"),), 400),
    ],
)
def test_header_refusals(ready: dict[str, Any], headers: Any, expected: int) -> None:
    assert handle(ready, headers=headers).status == expected
    assert ready["calls"] == {"identified": 0, "observed": 0, "signed": 0}


def test_wrong_length_header_rejected(ready: dict[str, Any]) -> None:
    headers = (
        ("content-type", "application/json"),
        ("accept", "application/json"),
        ("content-length", "01"),
    )
    assert handle(ready, headers=headers).status == 400


def test_unknown_client_denied_without_parser_or_signer(ready: dict[str, Any]) -> None:
    assert handle(ready, peer_der=b"unknown cert").status == 403
    assert ready["calls"] == {"identified": 1, "observed": 0, "signed": 0}


def test_client_policy_failure_returns_unavailable(ready: dict[str, Any]) -> None:
    def fail(_: str) -> None:
        raise OSError("policy disconnected")

    assert handle(ready, identify_client=fail).status == 503
    assert ready["calls"]["observed"] == 0


@pytest.mark.parametrize(
    "changes", [{"record_type": "other"}, {"schema_version": True}]
)
def test_unknown_request_contract_fails_closed(
    ready: dict[str, Any], changes: dict[str, Any]
) -> None:
    data = json.loads(ready["inputs"]["body"])
    data.update(changes)
    body = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    assert handle(ready, body=body).status == 400
    assert ready["calls"]["observed"] == 0


@pytest.mark.parametrize(
    "body",
    [
        b'{"x":0,"x":0}',
        b'{"record_type":"pds_evergreen_service_recovery_read_request"}',
        b"{}",
        b"not json",
    ],
)
def test_malformed_request_rejected(ready: dict[str, Any], body: bytes) -> None:
    assert handle(ready, body=body).status == 400
    assert ready["calls"]["observed"] == 0


def test_uncanonical_whitespace_and_unknown_field_rejected(
    ready: dict[str, Any],
) -> None:
    data = json.loads(ready["inputs"]["body"])
    assert handle(ready, body=json.dumps(data).encode()).status == 400
    data["can_launch"] = True
    body = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    assert handle(ready, body=body).status == 400


def test_mutated_challenge_or_nested_witness_proposal_rejected(
    ready: dict[str, Any],
) -> None:
    data = json.loads(ready["inputs"]["body"])
    data["challenge_b64"] = base64.b64encode(b"x" * 31).decode()
    body = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    assert handle(ready, body=body).status == 400
    data["challenge_b64"] = base64.b64encode(CHALLENGE).decode()
    data["witness_request_b64"] = base64.b64encode(b"invalid").decode()
    body = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    assert handle(ready, body=body).status == 400


def test_other_witness_request_reaches_gate_only_if_valid(
    ready: dict[str, Any],
) -> None:
    request = replace(ready["request"], witness_id="other_witness")
    body = make_service_recovery_observation_request(request, challenge=CHALLENGE)
    assert handle(ready, body=body).status == 503
    assert ready["calls"]["observed"] == 1
    assert ready["calls"]["signed"] == 0


@pytest.mark.parametrize(
    "status",
    ["CAS_MAY_BE_IN_FLIGHT", "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"],
)
def test_unresolved_or_prior_service_gate_will_not_sign_successor(
    ready: dict[str, Any], status: str
) -> None:
    def observer(_: WitnessCommitRequest, __: object) -> WitnessWriterQuiescenceState:
        return replace(ready["state"], status=status)

    assert handle(ready, observe=observer).status == 503
    assert ready["calls"]["signed"] == 0


def test_missing_gate_row_and_denial_do_not_sign(ready: dict[str, Any]) -> None:
    assert handle(ready, observe=lambda *_: None).status == 403

    def deny(_: WitnessCommitRequest, __: object) -> None:
        raise WitnessWriterQuiescenceError("not authorized")

    assert handle(ready, observe=deny).status == 403
    assert ready["calls"]["signed"] == 0


def test_broken_service_signer_fails_closed(ready: dict[str, Any]) -> None:
    def down(_: bytes) -> bytes:
        raise RuntimeError("signing key unavailable")

    assert handle(ready, sign=down).status == 503


def test_handler_does_not_launch_mutate_files_or_write_witness(
    ready: dict[str, Any], tmp_path: Path
) -> None:
    classroom = tmp_path / "classroom"
    classroom.mkdir()
    (classroom / "work.txt").write_text("untouched")
    with (
        patch("subprocess.run", side_effect=AssertionError("execution")),
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("pathlib.Path.write_bytes", side_effect=AssertionError("mutation")),
    ):
        assert handle(ready).status == 200
    assert (classroom / "work.txt").read_text() == "untouched"
