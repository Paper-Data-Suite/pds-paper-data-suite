"""Slice 61: opt-in signed staged candidate CLI, never active launch authority."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice58_catalog_preview as previous

import paper_data_suite.evergreen_staged_catalog_cli as module
from paper_data_suite import cli
from paper_data_suite.evergreen_catalog_stage_correlation import (
    CatalogStageCorrelation,
    CatalogStageCorrelationError,
    CatalogStagedWheel,
)
from paper_data_suite.evergreen_staged_catalog_cli import (
    StagedCatalogCliError,
    inspect_offline_staged_catalog_audit,
    render_staged_catalog_audit,
)

NOW = datetime(2026, 10, 24, 23, tzinfo=UTC)
D = "a" * 64


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "evidence"
    modules = root / "modules"
    modules.mkdir(parents=True)
    for name in (
        "prepared.json",
        "registry-envelope.json",
        "lock-envelope.json",
        "native-envelope.json",
    ):
        (root / name).write_bytes(name.encode())
    (modules / "quillan.json").write_bytes(b"publisher-signature")
    stage = tmp_path / "stage"
    stage.mkdir()
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    policy = tmp_path / "trust.json"
    policy.write_bytes(b"root policy")
    cache = tmp_path / "catalog.json"
    cache.write_bytes(b"cache")
    digest = hashlib.sha256(policy.read_bytes()).hexdigest()
    snapshot = previous.fixture_snapshot()
    signing = SimpleNamespace(keyring=object())
    report = CatalogStageCorrelation(
        "f" * 32,
        "a" * 64,
        "1" * 64,
        "2" * 64,
        (CatalogStagedWheel("quillan", "pds-quillan", "0.8.0", "b" * 64, "d" * 64),),
    )
    calls: list[str] = []

    def trust_policy(data: bytes, *, pinned_sha256: str) -> Any:
        calls.append("policy")
        assert data == policy.read_bytes() and pinned_sha256 == digest
        return signing

    def load_cache(path: Path, *, trust: Any, now: datetime) -> Any:
        calls.append("cache")
        assert path == cache and trust is signing.keyring and now == NOW
        return snapshot

    def audit(snap: Any, location: Path, files: Path, **kwargs: Any) -> Any:
        calls.append("audit")
        assert snap is snapshot and location == stage and files == wheels
        assert kwargs["module_envelopes"] == {"quillan": b"publisher-signature"}
        assert kwargs["registry_envelope"] == b"registry-envelope.json"
        assert kwargs["lock_envelope"] == b"lock-envelope.json"
        assert kwargs["native_envelope"] == b"native-envelope.json"
        assert kwargs["prepared_record"] == b"prepared.json"
        assert kwargs["trust"] is signing.keyring
        return report

    monkeypatch.setattr(module, "load_digest_pinned_trust_policy", trust_policy)
    monkeypatch.setattr(module, "load_catalog_cache", load_cache)
    monkeypatch.setattr(
        module,
        "parse_unverified_prepared_record",
        lambda raw: SimpleNamespace(
            wheels=(SimpleNamespace(distribution="pds-quillan"),)
        ),
    )
    monkeypatch.setattr(module, "inspect_catalog_bound_staged_bytes", audit)
    return {
        "args": {
            "catalog_cache": cache,
            "trust_policy": policy,
            "pinned_policy_sha256": digest,
            "evidence_directory": root,
            "stage_root": stage,
            "wheelhouse": wheels,
            "now": NOW,
        },
        "root": root,
        "modules": modules,
        "calls": calls,
        "result": report,
        "cache": cache,
        "policy": policy,
    }


def run(ready: dict[str, Any], **changes: Any) -> str:
    return inspect_offline_staged_catalog_audit(**{**ready["args"], **changes})


def test_bounded_signed_staged_diagnostic_does_not_touch_files(
    ready: dict[str, Any], tmp_path: Path
) -> None:
    before = {
        f.relative_to(tmp_path): f.read_bytes()
        for f in tmp_path.rglob("*")
        if f.is_file()
    }
    with (
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("subprocess.run", side_effect=AssertionError("execution")),
    ):
        result = run(ready)
    assert "STAGED CANDIDATE ONLY" in result
    assert "Launch, update and activation authority: NONE" in result
    assert "pds-quillan" in result
    assert "0.8.0" in result
    assert "NOT ACTIVE" in result
    assert "No network access" in result
    assert "pds launch" not in result
    assert ready["calls"] == ["policy", "cache", "audit"]
    assert before == {
        f.relative_to(tmp_path): f.read_bytes()
        for f in tmp_path.rglob("*")
        if f.is_file()
    }


def test_render_refuses_unverified_object() -> None:
    with pytest.raises(StagedCatalogCliError, match="correlation"):
        render_staged_catalog_audit(SimpleNamespace())  # type: ignore[arg-type]


@pytest.mark.parametrize("pin", ["", "f" * 63, "z" * 64, "A" * 64, None])
def test_invalid_pin_refuses_before_signatures(ready: dict[str, Any], pin: Any) -> None:
    with pytest.raises(StagedCatalogCliError, match="independent SHA-256"):
        run(ready, pinned_policy_sha256=pin)
    assert ready["calls"] == []


def test_extra_evidence_file_refuses(ready: dict[str, Any]) -> None:
    (ready["root"] / "extra.txt").write_bytes(b"oops")
    with pytest.raises(StagedCatalogCliError, match="unexpected"):
        run(ready)
    assert ready["calls"] == []


def test_missing_module_document_refuses(ready: dict[str, Any]) -> None:
    (ready["modules"] / "quillan.json").unlink()
    with pytest.raises(StagedCatalogCliError, match="module evidence files"):
        run(ready)
    assert ready["calls"] == ["policy", "cache"]


def test_extra_module_document_refuses(ready: dict[str, Any]) -> None:
    (ready["modules"] / "scoreform.json").write_bytes(b"unexpected")
    with pytest.raises(StagedCatalogCliError, match="module evidence files"):
        run(ready)


def test_no_registered_wheel_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "parse_unverified_prepared_record",
        lambda raw: SimpleNamespace(
            wheels=(SimpleNamespace(distribution="ordinary-dependency"),)
        ),
    )
    with pytest.raises(StagedCatalogCliError, match="no selected"):
        run(ready)


def test_unsafe_symlink_input_refuses(ready: dict[str, Any], tmp_path: Path) -> None:
    alias = tmp_path / "linked-evidence"
    try:
        alias.symlink_to(ready["root"], target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(StagedCatalogCliError, match="unsafe evidence"):
        run(ready, evidence_directory=alias)


def test_unsafe_symlink_module_refuses(ready: dict[str, Any]) -> None:
    old = ready["modules"] / "quillan.json"
    old.unlink()
    try:
        old.symlink_to(ready["policy"])
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(StagedCatalogCliError, match="unsafe or unreadable module"):
        run(ready)


def test_oversized_evidence_refuses(ready: dict[str, Any]) -> None:
    (ready["root"] / "native-envelope.json").write_bytes(b"x" * (32 * 1024 + 1))
    with pytest.raises(StagedCatalogCliError, match="native"):
        run(ready)
    assert "audit" not in ready["calls"]


def test_physical_audit_failure_is_not_ignored(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise CatalogStageCorrelationError("changed native bytes")

    monkeypatch.setattr(module, "inspect_catalog_bound_staged_bytes", fail)
    with pytest.raises(StagedCatalogCliError, match="could not be verified"):
        run(ready)


def test_catalog_cache_absent_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "load_catalog_cache", lambda *a, **k: None)
    with pytest.raises(StagedCatalogCliError, match="absent"):
        run(ready)


def test_parser_is_explicit_and_default_unchanged() -> None:
    args = cli.build_parser().parse_args(["modules"])
    assert args.audit_staged_evidence is None
    assert args.audit_stage_root is None
    assert args.audit_wheelhouse is None
    audit = cli.build_parser().parse_args(
        [
            "modules",
            "--catalog-cache",
            "cache",
            "--trust-policy",
            "policy",
            "--trust-sha256",
            "a" * 64,
            "--audit-staged-evidence",
            "evidence",
            "--audit-stage-root",
            "stage",
            "--audit-wheelhouse",
            "wheels",
        ]
    )
    assert audit.audit_staged_evidence == Path("evidence")
    assert audit.audit_stage_root == Path("stage")
    assert audit.audit_wheelhouse == Path("wheels")


@pytest.mark.parametrize("missing", ["evidence", "root", "wheelhouse", "trust"])
def test_incomplete_cli_request_fails_before_inspection(
    capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    values: dict[str, Any] = {
        "catalog_cache": Path("cache"),
        "trust_policy": Path("policy"),
        "trust_sha256": "a" * 64,
        "audit_staged_evidence": Path("evidence"),
        "audit_stage_root": Path("stage"),
        "audit_wheelhouse": Path("wheels"),
    }
    if missing == "evidence":
        values["audit_staged_evidence"] = None
    elif missing == "root":
        values["audit_stage_root"] = None
    elif missing == "wheelhouse":
        values["audit_wheelhouse"] = None
    else:
        values["trust_sha256"] = None
    with (
        patch.object(
            cli,
            "inspect_offline_staged_catalog_audit",
            side_effect=AssertionError("must not audit"),
        ),
        patch.object(
            cli, "_resolved_inventory", side_effect=AssertionError("no fallback")
        ),
    ):
        assert cli._run_modules(**values) == 2
    assert "requires" in capsys.readouterr().err


def test_compare_local_metadata_and_staged_audit_are_mutually_exclusive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        cli._run_modules(
            catalog_cache=Path("cache"),
            trust_policy=Path("policy"),
            trust_sha256="a" * 64,
            compare_local_metadata=True,
            audit_staged_evidence=Path("evidence"),
            audit_stage_root=Path("stage"),
            audit_wheelhouse=Path("wheels"),
        )
        == 2
    )
    assert "cannot be combined" in capsys.readouterr().err


def test_explicit_cli_dispatch_without_legacy_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(
            cli, "inspect_offline_staged_catalog_audit", return_value="stage only\n"
        ) as audit,
        patch.object(
            cli,
            "inspect_offline_catalog_preview",
            side_effect=AssertionError("wrong mode"),
        ),
        patch.object(
            cli, "_resolved_inventory", side_effect=AssertionError("fallback")
        ),
    ):
        rc = cli.main(
            (
                "modules",
                "--catalog-cache",
                "cache",
                "--trust-policy",
                "policy",
                "--trust-sha256",
                "a" * 64,
                "--audit-staged-evidence",
                "evidence",
                "--audit-stage-root",
                "stage",
                "--audit-wheelhouse",
                "wheels",
            )
        )
    assert rc == 0
    assert capsys.readouterr().out == "stage only\n"
    assert audit.call_args.kwargs["evidence_directory"] == Path("evidence")
    assert audit.call_args.kwargs["stage_root"] == Path("stage")


def test_cli_refusal_does_not_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.object(
        cli,
        "inspect_offline_staged_catalog_audit",
        side_effect=StagedCatalogCliError("invalid publisher"),
    ):
        assert (
            cli._run_modules(
                catalog_cache=Path("cache"),
                trust_policy=Path("policy"),
                trust_sha256="a" * 64,
                audit_staged_evidence=Path("evidence"),
                audit_stage_root=Path("stage"),
                audit_wheelhouse=Path("wheels"),
            )
            == 1
        )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid publisher" in captured.err
