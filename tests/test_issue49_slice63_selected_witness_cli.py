"""Slice 63: explicit network witness diagnostics never grant launch authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice58_catalog_preview as earlier

import paper_data_suite.evergreen_selected_witness_cli as module
from paper_data_suite import cli
from paper_data_suite.evergreen_catalog_stage_correlation import CatalogStagedWheel
from paper_data_suite.evergreen_selected_witness_cli import (
    SelectedWitnessCliError,
    inspect_selected_witness_catalog_audit,
    render_selected_witness_audit,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageError,
    WitnessSelectedStageObservation,
)

NOW = datetime(2026, 10, 25, 19, tzinfo=UTC)
TX = "f" * 32
PIN = "a" * 64


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    software = tmp_path / "software"
    classroom = tmp_path / "classroom"
    software.mkdir()
    classroom.mkdir()
    evidence = tmp_path / "evidence"
    publishers = evidence / "modules"
    publishers.mkdir(parents=True)
    for name in (
        "prepared.json",
        "registry-envelope.json",
        "lock-envelope.json",
        "native-envelope.json",
    ):
        (evidence / name).write_bytes(name.encode("ascii"))
    (publishers / "quillan.json").write_bytes(b"publisher")
    policy = tmp_path / "policy.json"
    policy.write_bytes(b"pinned policy")
    cache = tmp_path / "catalog.json"
    cache.write_bytes(b"signed cache")
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(b"signed receipt")
    public = tmp_path / "witness.raw"
    public.write_bytes(b"K" * 32)
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"CA CERTIFICATE")
    cert = tmp_path / "client.pem"
    cert.write_bytes(b"CLIENT CERTIFICATE")
    secret = tmp_path / "private.pem"
    secret.write_bytes(b"PRIVATE KEY")
    config = tmp_path / "witness-config.json"
    values: dict[str, object] = {
        "schema_version": 1,
        "software_root": str(software),
        "classroom_workspace": str(classroom),
        "receipt_file": str(receipt),
        "evidence_directory": str(evidence),
        "installation_id": "a" * 32,
        "witness_id": "independent_witness",
        "witness_origin": "https://witness.example.org",
        "witness_ca_file": str(ca),
        "witness_ca_sha256": hashlib.sha256(ca.read_bytes()).hexdigest(),
        "client_certificate_file": str(cert),
        "client_private_key_file": str(secret),
        "witness_public_key_file": str(public),
        "witness_public_key_sha256": hashlib.sha256(public.read_bytes()).hexdigest(),
    }
    config.write_text(json.dumps(values), encoding="utf-8")
    observed = WitnessSelectedStageObservation(
        TX,
        2,
        8,
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        (CatalogStagedWheel("quillan", "pds-quillan", "0.8.0", "5" * 64, "6" * 64),),
    )
    calls: list[str] = []
    snapshot = earlier.fixture_snapshot()
    signing = SimpleNamespace(keyring=object())

    def load_policy(raw: bytes, *, pinned_sha256: str) -> Any:
        calls.append("policy")
        assert raw == policy.read_bytes() and pinned_sha256 == PIN
        return signing

    def load_cache(path: Path, *, trust: Any, now: datetime) -> Any:
        calls.append("cache")
        assert path == cache and trust is signing.keyring and now == NOW
        return snapshot

    def transport(**kwargs: Any) -> Any:
        calls.append("transport")
        assert kwargs["origin"] == "https://witness.example.org"
        assert kwargs["ca_certificate"] == ca
        assert kwargs["pinned_ca_sha256"] == values["witness_ca_sha256"]
        return SimpleNamespace(**kwargs)

    def inspect(snap: Any, root: Path, **kwargs: Any) -> Any:
        calls.append("audit")
        assert snap is snapshot and root == software
        assert kwargs["classroom_workspace"] == classroom
        assert kwargs["receipt_bytes"] == receipt.read_bytes()
        assert kwargs["pinned_witness_public_key"] == b"K" * 32
        assert kwargs["module_envelopes"] == {"quillan": b"publisher"}
        assert kwargs["trust"] is signing.keyring and kwargs["now"] == NOW
        assert kwargs["installation_id"] == "a" * 32
        assert kwargs["expected_witness_id"] == "independent_witness"
        assert kwargs["prepared_record"] == b"prepared.json"
        return observed

    monkeypatch.setattr(module, "load_digest_pinned_trust_policy", load_policy)
    monkeypatch.setattr(module, "load_catalog_cache", load_cache)
    monkeypatch.setattr(
        module,
        "parse_unverified_prepared_record",
        lambda raw: SimpleNamespace(
            wheels=(SimpleNamespace(distribution="pds-quillan"),)
        ),
    )
    monkeypatch.setattr(module, "ProvisionedHttpsWitnessTransport", transport)
    monkeypatch.setattr(module, "inspect_witness_pinned_selected_staged_bytes", inspect)
    return {
        "args": {
            "catalog_cache": cache,
            "trust_policy": policy,
            "pinned_policy_sha256": PIN,
            "configuration": config,
            "now": NOW,
        },
        "tmp": tmp_path,
        "config": config,
        "values": values,
        "calls": calls,
        "observed": observed,
        "ca": ca,
        "public": public,
        "evidence": evidence,
        "policy": policy,
    }


def run(ready: dict[str, Any], **changes: Any) -> str:
    return inspect_selected_witness_catalog_audit(**{**ready["args"], **changes})


def write_config(ready: dict[str, Any], **changes: Any) -> None:
    ready["values"].update(changes)
    ready["config"].write_text(json.dumps(ready["values"]), encoding="utf-8")


def test_diagnostic_success_is_read_only_and_explicit(ready: dict[str, Any]) -> None:
    root = ready["tmp"]
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    with patch("subprocess.run", side_effect=AssertionError("package execution")):
        report = run(ready)
    after = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert before == after
    assert ready["calls"] == ["policy", "cache", "transport", "audit"]
    assert "ACTIVE AUTHORITY NOT ESTABLISHED" in report
    assert "Launch, update, rollback and receipt-write authority: NONE" in report
    assert "Witness revision: 8" in report
    assert "pds-quillan" in report
    assert "local write" in report
    assert "pds launch quillan" not in report
    assert "PRIVATE KEY" not in report


def test_render_requires_actual_observation() -> None:
    with pytest.raises(SelectedWitnessCliError):
        render_selected_witness_audit(SimpleNamespace())  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [None, datetime(2026, 10, 25, 19), "2026-10-25"])
def test_clock_must_be_aware(ready: dict[str, Any], bad: Any) -> None:
    with pytest.raises(SelectedWitnessCliError, match="aware clock"):
        run(ready, now=bad)
    assert ready["calls"] == []


@pytest.mark.parametrize("bad", ["", "A" * 64, "z" * 64, "a" * 63, None])
def test_bad_catalog_pin_refused(ready: dict[str, Any], bad: Any) -> None:
    with pytest.raises(SelectedWitnessCliError, match="pin"):
        run(ready, pinned_policy_sha256=bad)
    assert ready["calls"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"installation_id": "invalid"},
        {"witness_id": "Bad!"},
        {"witness_ca_sha256": "a" * 63},
        {"witness_public_key_sha256": "z" * 64},
        {"software_root": "./relative"},
        {"client_private_key_file": "relative-key.pem"},
    ],
)
def test_config_rejects_invalid_fields_before_network(
    ready: dict[str, Any], change: dict[str, object]
) -> None:
    write_config(ready, **change)
    with pytest.raises(SelectedWitnessCliError):
        run(ready)
    assert "transport" not in ready["calls"]


def test_unknown_config_field_refuses(ready: dict[str, Any]) -> None:
    write_config(ready, unrecognized="unexpected")
    with pytest.raises(SelectedWitnessCliError, match="unknown or missing"):
        run(ready)
    assert ready["calls"] == []


def test_duplicate_config_field_refuses(ready: dict[str, Any]) -> None:
    text = ready["config"].read_text()
    ready["config"].write_text(
        text.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
    )
    with pytest.raises(SelectedWitnessCliError, match="duplicate"):
        run(ready)


def test_oversize_config_refuses(ready: dict[str, Any]) -> None:
    ready["config"].write_bytes(b"x" * (8 * 1024 + 1))
    with pytest.raises(SelectedWitnessCliError):
        run(ready)
    assert ready["calls"] == []


def test_symlink_config_refuses(ready: dict[str, Any]) -> None:
    link = ready["tmp"] / "symlink-config.json"
    try:
        link.symlink_to(ready["config"])
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(SelectedWitnessCliError):
        run(ready, configuration=link)
    assert ready["calls"] == []


def test_witness_key_pin_mismatch_refuses_before_network(ready: dict[str, Any]) -> None:
    ready["public"].write_bytes(b"z" * 32)
    with pytest.raises(SelectedWitnessCliError, match="witness public key"):
        run(ready)
    assert "transport" not in ready["calls"]


def test_tls_ca_pin_mismatch_refuses_before_network(ready: dict[str, Any]) -> None:
    ready["ca"].write_bytes(b"substituted CA")
    with pytest.raises(SelectedWitnessCliError, match="TLS CA digest"):
        run(ready)
    assert "transport" not in ready["calls"]


def test_unexpected_evidence_entry_refuses(ready: dict[str, Any]) -> None:
    (ready["evidence"] / "extra").write_text("not permitted")
    with pytest.raises(SelectedWitnessCliError, match="unexpected"):
        run(ready)
    assert ready["calls"] == []


def test_missing_publisher_refuses_before_network(ready: dict[str, Any]) -> None:
    (ready["evidence"] / "modules" / "quillan.json").unlink()
    with pytest.raises(SelectedWitnessCliError, match="publisher evidence"):
        run(ready)
    assert "transport" not in ready["calls"]


def test_missing_signed_catalog_refuses_without_network(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "load_catalog_cache", lambda *a, **kw: None)
    with pytest.raises(SelectedWitnessCliError, match="absent"):
        run(ready)
    assert "transport" not in ready["calls"]


def test_no_registered_wheels_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "parse_unverified_prepared_record",
        lambda raw: SimpleNamespace(
            wheels=(SimpleNamespace(distribution="not-registered"),)
        ),
    )
    with pytest.raises(SelectedWitnessCliError, match="no registered"):
        run(ready)
    assert "transport" not in ready["calls"]


def test_witness_verification_failure_never_falls_back(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "inspect_witness_pinned_selected_staged_bytes",
        lambda *a, **kw: (_ for _ in ()).throw(WitnessSelectedStageError("refused")),
    )
    with pytest.raises(SelectedWitnessCliError, match="verification refused"):
        run(ready)
    assert ready["calls"][-1] == "transport"


def test_default_modules_parser_unchanged() -> None:
    args = cli.build_parser().parse_args(["modules"])
    assert args.audit_witness_selected is None
    assert args.audit_staged_evidence is None
    assert args.compare_local_metadata is False


def test_explicit_parser_accepts_config() -> None:
    args = cli.build_parser().parse_args(
        ["modules", "--audit-witness-selected", "witness.json"]
    )
    assert args.audit_witness_selected == Path("witness.json")


@pytest.mark.parametrize("missing", ["catalog_cache", "trust_policy", "trust_sha256"])
def test_partial_cli_refuses_without_network(
    capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    kwargs: dict[str, Any] = {
        "catalog_cache": Path("cache"),
        "trust_policy": Path("policy"),
        "trust_sha256": PIN,
        "audit_witness_selected": Path("config"),
    }
    kwargs[missing] = None
    with (
        patch.object(
            cli,
            "inspect_selected_witness_catalog_audit",
            side_effect=AssertionError("network"),
        ),
        patch.object(
            cli, "_resolved_inventory", side_effect=AssertionError("fallback")
        ),
    ):
        assert cli._run_modules(**kwargs) == 2
    assert "requires" in capsys.readouterr().err


@pytest.mark.parametrize("conflict", ["compare", "stage"])
def test_mutually_exclusive_modes(
    capsys: pytest.CaptureFixture[str], conflict: str
) -> None:
    kwargs: dict[str, Any] = {
        "catalog_cache": Path("cache"),
        "trust_policy": Path("policy"),
        "trust_sha256": PIN,
        "audit_witness_selected": Path("config"),
    }
    if conflict == "compare":
        kwargs["compare_local_metadata"] = True
    else:
        kwargs["audit_staged_evidence"] = Path("evidence")
        kwargs["audit_stage_root"] = Path("stage")
        kwargs["audit_wheelhouse"] = Path("wheels")
    assert cli._run_modules(**kwargs) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_cli_dispatch_without_legacy_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(
            cli,
            "inspect_selected_witness_catalog_audit",
            return_value="witness diagnostic\n",
        ) as audit,
        patch.object(
            cli,
            "inspect_offline_catalog_preview",
            side_effect=AssertionError("catalog"),
        ),
        patch.object(cli, "_resolved_inventory", side_effect=AssertionError("legacy")),
    ):
        result = cli.main(
            (
                "modules",
                "--catalog-cache",
                "cache",
                "--trust-policy",
                "policy",
                "--trust-sha256",
                PIN,
                "--audit-witness-selected",
                "config",
            )
        )
    assert result == 0
    assert capsys.readouterr().out == "witness diagnostic\n"
    assert audit.call_args.kwargs["configuration"] == Path("config")


def test_cli_refusal_exits_one_without_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(
            cli,
            "inspect_selected_witness_catalog_audit",
            side_effect=SelectedWitnessCliError("unsafe witness"),
        ),
        patch.object(cli, "_resolved_inventory", side_effect=AssertionError("legacy")),
    ):
        assert (
            cli._run_modules(
                catalog_cache=Path("cache"),
                trust_policy=Path("policy"),
                trust_sha256=PIN,
                audit_witness_selected=Path("config"),
            )
            == 1
        )
    captured = capsys.readouterr()
    assert captured.out == "" and "unsafe witness" in captured.err


def test_render_module_table_is_observational(ready: dict[str, Any]) -> None:
    other = replace(ready["observed"], modules=())
    text = render_selected_witness_audit(other)
    assert "Launch, update, rollback and receipt-write authority: NONE" in text
    assert "pds launch" not in text
