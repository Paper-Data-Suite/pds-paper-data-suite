"""Slice 37: explicit operator witness read acceptance, never launch authority."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite.evergreen_active_receipts import make_untrusted_active_receipt
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_journal_pip_preflight import (
    ObservedJournalPipCandidate,
)
from paper_data_suite.evergreen_witness_acceptance import (
    WitnessAcceptanceError,
    build_parser,
    main,
    probe_witness_head,
)
from paper_data_suite.evergreen_witness_https import ProvisionedHttpsWitnessTransport

NOW = datetime(2026, 10, 19, 20, tzinfo=UTC)
INSTALL = "a" * 32
WITNESS = "remote_witness"


def _receipt() -> bytes:
    candidate = ObservedJournalPipCandidate(
        "b" * 32,
        1,
        "candidate/one",
        "wheels/one",
        "c" * 64,
        "d" * 64,
        (("quillan", "e" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )
    return make_untrusted_active_receipt(
        candidate,
        prepared_record=b"signed prepared",
        registry_envelope=b"root registry",
        lock_envelope=b"root lock",
        native_envelope=b"root native",
        generation=1,
        recorded_at=NOW,
        previous=None,
    )


@pytest.fixture
def ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], MonotonicCheckpointStore, Ed25519PrivateKey]:
    receipt = _receipt()
    receipt_file = tmp_path / "active-receipt.json"
    receipt_file.write_bytes(receipt)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_file = tmp_path / "witness-public.key"
    public_file.write_bytes(public)
    connection = sqlite3.connect(":memory:", isolation_level=None)

    def authorized(installation: str, operation: str, context: object) -> bool:
        return installation == INSTALL and context == "service-operator"

    store = MonotonicCheckpointStore(
        connection,
        witness_id=WITNESS,
        authorize=authorized,
        sign=private.sign,
    )
    assert (
        store.commit_receipt(INSTALL, receipt, context="service-operator").revision == 1
    )
    transport = ProvisionedHttpsWitnessTransport(
        "https://witness.example.org",
        tmp_path / "ca.pem",
        "f" * 64,
        tmp_path / "client.pem",
        tmp_path / "client.key",
    )

    # Only test-double transport; production S35 still enforces pinned mTLS.
    def answer(self: ProvisionedHttpsWitnessTransport, challenge: bytes) -> bytes:
        return store.answer_challenge(challenge, context="service-operator", now=NOW)

    monkeypatch.setattr(ProvisionedHttpsWitnessTransport, "__call__", answer)
    kwargs: dict[str, Any] = {
        "transport": transport,
        "installation_id": INSTALL,
        "receipt_file": receipt_file,
        "public_key_file": public_file,
        "pinned_public_key_sha256": hashlib.sha256(public).hexdigest(),
        "witness_id": WITNESS,
        "now": NOW,
    }
    return kwargs, store, private


def test_signed_head_from_real_store_passes_protocol_only(ready: Any) -> None:
    kwargs, _, _ = ready
    result = probe_witness_head(**kwargs)
    assert result.status == "SIGNED_HEAD_MATCHED_DEPLOYMENT_UNVERIFIED"
    assert result.generation == 1
    assert result.witness_revision == 1
    assert result.installation_id == INSTALL
    assert result.witness_id == WITNESS
    assert (
        result.receipt_sha256
        == hashlib.sha256(kwargs["receipt_file"].read_bytes()).hexdigest()
    )
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "independent_deployment_qualified")


def test_accepted_minimum_revision(ready: Any) -> None:
    kwargs, _, _ = ready
    assert (
        probe_witness_head(**kwargs, minimum_witness_revision=1).witness_revision == 1
    )


@pytest.mark.parametrize("revision", [2, 100])
def test_revision_rollback_fails_closed(ready: Any, revision: int) -> None:
    kwargs, _, _ = ready
    with pytest.raises(WitnessAcceptanceError, match="verification failed"):
        probe_witness_head(**kwargs, minimum_witness_revision=revision)


@pytest.mark.parametrize("revision", [0, -1, True, 2**53, "1"])
def test_invalid_minimum_rejected_prior_to_transport(ready: Any, revision: Any) -> None:
    kwargs, _, _ = ready
    with pytest.raises(WitnessAcceptanceError, match="revision"):
        probe_witness_head(**kwargs, minimum_witness_revision=revision)


def test_wrong_pin_rejected_before_any_network(ready: Any, monkeypatch: Any) -> None:
    kwargs, _, _ = ready

    def no_request(*args: Any, **kw: Any) -> Any:
        raise AssertionError("network must not run")

    monkeypatch.setattr(ProvisionedHttpsWitnessTransport, "__call__", no_request)
    with pytest.raises(WitnessAcceptanceError, match="does not match"):
        probe_witness_head(**{**kwargs, "pinned_public_key_sha256": "0" * 64})


@pytest.mark.parametrize("pin", ["F" * 64, "g" * 64, "1" * 63, 1, None])
def test_malformed_key_pin_rejected(ready: Any, pin: Any) -> None:
    kwargs, _, _ = ready
    with pytest.raises(WitnessAcceptanceError, match="pin"):
        probe_witness_head(**{**kwargs, "pinned_public_key_sha256": pin})


def test_wrong_witness_identity_rejected(ready: Any) -> None:
    kwargs, _, _ = ready
    with pytest.raises(WitnessAcceptanceError, match="verification failed"):
        probe_witness_head(**{**kwargs, "witness_id": "other_witness"})


def test_wrong_installation_rejected(ready: Any) -> None:
    kwargs, _, _ = ready
    with pytest.raises(WitnessAcceptanceError, match="verification failed"):
        probe_witness_head(**{**kwargs, "installation_id": "1" * 32})


def test_mutated_receipt_rejected(ready: Any) -> None:
    kwargs, _, _ = ready
    file = kwargs["receipt_file"]
    raw = file.read_bytes()
    file.write_bytes(raw.replace(b"candidate/one", b"candidate/two"))
    with pytest.raises(WitnessAcceptanceError, match="verification failed"):
        probe_witness_head(**kwargs)


def test_missing_file_fails_before_request(ready: Any) -> None:
    kwargs, _, _ = ready
    kwargs["receipt_file"].unlink()
    with pytest.raises(WitnessAcceptanceError, match="unable to read active receipt"):
        probe_witness_head(**kwargs)


def test_oversized_file_fails_closed(ready: Any) -> None:
    kwargs, _, _ = ready
    kwargs["receipt_file"].write_bytes(b"x" * 16385)
    with pytest.raises(WitnessAcceptanceError, match="oversized"):
        probe_witness_head(**kwargs)


def test_short_public_key_fails_closed(ready: Any) -> None:
    kwargs, _, _ = ready
    kwargs["public_key_file"].write_bytes(b"x")
    with pytest.raises(WitnessAcceptanceError, match="does not match"):
        probe_witness_head(**kwargs)


def test_directory_refused(ready: Any) -> None:
    kwargs, _, _ = ready
    with pytest.raises(WitnessAcceptanceError, match="unsafe"):
        probe_witness_head(**{**kwargs, "receipt_file": kwargs["receipt_file"].parent})


def test_symlink_file_refused(ready: Any, tmp_path: Path) -> None:
    kwargs, _, _ = ready
    path = tmp_path / "linked-receipt"
    try:
        path.symlink_to(kwargs["receipt_file"])
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlinks unavailable")
    with pytest.raises(WitnessAcceptanceError, match="unsafe"):
        probe_witness_head(**{**kwargs, "receipt_file": path})


def test_transport_exception_never_trusts_reply(ready: Any, monkeypatch: Any) -> None:
    kwargs, _, _ = ready

    def offline(*args: Any, **kw: Any) -> Any:
        raise ConnectionError("secret internal host path")

    monkeypatch.setattr(ProvisionedHttpsWitnessTransport, "__call__", offline)
    with pytest.raises(WitnessAcceptanceError, match="verification failed") as exc:
        probe_witness_head(**kwargs)
    assert "secret internal host path" not in str(exc.value)


def test_nontransport_object_refused(ready: Any) -> None:
    kwargs, _, _ = ready
    with pytest.raises(WitnessAcceptanceError, match="transport"):
        probe_witness_head(**{**kwargs, "transport": lambda data: data})


def test_naive_clock_refused(ready: Any) -> None:
    kwargs, _, _ = ready
    with pytest.raises(WitnessAcceptanceError, match="clock"):
        probe_witness_head(**{**kwargs, "now": datetime(2026, 10, 19)})


def test_cli_help_is_explicit_opt_in(capsys: Any) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "--client-key" in output
    assert "NOT activation qualification" in output


def test_cli_missing_inputs_cannot_contact_network(capsys: Any) -> None:
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
    assert "required" in capsys.readouterr().err


def test_cli_refusal_does_not_reveal_paths(
    ready: Any, monkeypatch: Any, capsys: Any
) -> None:
    kwargs, _, _ = ready
    pin = kwargs["pinned_public_key_sha256"]
    argv = [
        "--origin",
        "https://witness.example.org",
        "--ca-file",
        str(kwargs["receipt_file"]),
        "--ca-sha256",
        "f" * 64,
        "--client-cert",
        str(kwargs["receipt_file"]),
        "--client-key",
        str(kwargs["receipt_file"]),
        "--witness-key",
        str(kwargs["public_key_file"]),
        "--witness-key-sha256",
        "0" * 64,
        "--witness-id",
        WITNESS,
        "--installation-id",
        INSTALL,
        "--receipt",
        str(kwargs["receipt_file"]),
    ]
    assert main(argv) == 1
    output = capsys.readouterr().err
    assert "REFUSED" in output
    assert pin not in output
    assert str(kwargs["receipt_file"]) not in output


def test_cli_success_reports_only_protocol_observation(ready: Any, capsys: Any) -> None:
    kwargs, _, _ = ready
    argv = [
        "--origin",
        "https://witness.example.org",
        "--ca-file",
        str(kwargs["receipt_file"]),
        "--ca-sha256",
        "f" * 64,
        "--client-cert",
        str(kwargs["receipt_file"]),
        "--client-key",
        str(kwargs["receipt_file"]),
        "--witness-key",
        str(kwargs["public_key_file"]),
        "--witness-key-sha256",
        kwargs["pinned_public_key_sha256"],
        "--witness-id",
        WITNESS,
        "--installation-id",
        INSTALL,
        "--receipt",
        str(kwargs["receipt_file"]),
        "--minimum-revision",
        "1",
    ]
    assert main(argv, now=NOW) == 0
    output = capsys.readouterr().out
    assert "SIGNED_HEAD_MATCHED_DEPLOYMENT_UNVERIFIED" in output
    assert "NOT AUTHORIZED" in output
    assert "NOT VERIFIED" in output
    assert str(kwargs["receipt_file"]) not in output


def test_module_does_not_touch_live_suite_dispatch() -> None:
    import paper_data_suite.evergreen_witness_acceptance as module

    assert not hasattr(module, "launch_application")
    assert not hasattr(module, "commit_receipt")
    assert not hasattr(module, "update_active_slot")
    assert build_parser().prog.endswith("evergreen_witness_acceptance")
