"""Slice 58: explicit, offline signed catalog diagnostics; no launch authority."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from paper_data_suite import cli
from paper_data_suite.evergreen_catalog_contracts import (
    AuthorizedModuleClaim,
    ExactArtifactClaim,
    IntegrationClaims,
    MetadataWindow,
    ModuleReleaseClaims,
    RegistryClaims,
    ReleaseClaim,
)
from paper_data_suite.evergreen_catalog_preview import (
    CatalogPreviewError,
    inspect_offline_catalog_preview,
    render_catalog_preview,
)
from paper_data_suite.evergreen_catalog_state import CatalogSnapshot, CatalogStateError
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    VerifiedIntegrationDocument,
    VerifiedModuleDocument,
    VerifiedRegistryDocument,
)
from paper_data_suite.evergreen_trust_provisioning import TrustProvisioningError

NOW = datetime(2026, 10, 24, 16, tzinfo=UTC)
DIGEST = "a" * 64


def fixture_snapshot() -> CatalogSnapshot:
    window = MetadataWindow(2, NOW - timedelta(days=1), NOW + timedelta(days=3))
    modules = (
        AuthorizedModuleClaim(
            "quillan", "Paper-Data-Suite/pds-quillan", "pds-quillan", ("quillan-key",)
        ),
        AuthorizedModuleClaim(
            "scoreform",
            "Paper-Data-Suite/pds-scoreform",
            "pds-scoreform",
            ("scoreform-key",),
        ),
    )
    registry = VerifiedRegistryDocument(
        RegistryClaims(window, modules, ("integration-key",)),
        DIGEST,
        ("root-key",),
        RevisionCheckpoint(2, DIGEST),
        DIGEST,
    )
    versions = (
        ReleaseClaim(
            "0.8.0",
            "v0.8.0",
            "quillan-0.8.0-py3-none-any.whl",
            "b" * 64,
            ">=3.11",
            (),
            "quillan",
            "quillan.cli:main",
            False,
        ),
        ReleaseClaim(
            "0.7.0",
            "v0.7.0",
            "quillan-0.7.0-py3-none-any.whl",
            "c" * 64,
            ">=3.11",
            (),
            "quillan",
            "quillan.cli:main",
            True,
        ),
    )
    release = VerifiedModuleDocument(
        ModuleReleaseClaims(
            window, "quillan", "Paper-Data-Suite/pds-quillan", "pds-quillan", versions
        ),
        DIGEST,
        "d" * 64,
        ("quillan-key",),
        RevisionCheckpoint(2, "d" * 64),
    )
    integration = VerifiedIntegrationDocument(
        IntegrationClaims(
            window,
            "quillan-scoreform-grading",
            "e" * 64,
            "passed",
            (ExactArtifactClaim("quillan", "b" * 64),),
            ("3.11",),
            ("win_amd64",),
        ),
        DIGEST,
        "e" * 64,
        ("integration-key",),
        RevisionCheckpoint(2, "e" * 64),
    )
    return CatalogSnapshot(registry, (release,), (integration,), NOW)


def test_preview_formats_verified_claims_without_installed_assertions() -> None:
    report = render_catalog_preview(fixture_snapshot())
    assert "offline signed release catalog" in report
    assert "quillan" in report and "scoreform" in report
    assert "0.8.0 — SIGNED CLAIM ONLY" in report
    assert "0.7.0 — REVOKED" in report
    assert "No current signed release document" in report
    assert "signed result=passed; installed composition NOT VERIFIED" in report
    assert "Launch eligibility: NOT ASSESSED" in report
    assert "Update readiness: NOT ASSESSED" in report
    assert "No network access" in report
    assert "pds launch quillan" not in report
    assert "available for launch" not in report


def test_preview_is_deterministic_and_ordered() -> None:
    snapshot = fixture_snapshot()
    first = render_catalog_preview(snapshot)
    assert first == render_catalog_preview(snapshot)
    assert first.index("  quillan") < first.index("  scoreform")
    assert first.index("0.7.0 — REVOKED") < first.index("0.8.0 — SIGNED CLAIM ONLY")


def test_preview_requires_snapshot_type() -> None:
    with pytest.raises(CatalogPreviewError):
        render_catalog_preview(SimpleNamespace())  # type: ignore[arg-type]


def test_preview_without_integration_reports_none() -> None:
    snapshot = fixture_snapshot()
    new = CatalogSnapshot(snapshot.registry, snapshot.modules, (), snapshot.accepted_at)
    assert "None in this cache" in render_catalog_preview(new)


def paths(tmp_path: Path) -> tuple[Path, Path, str]:
    policy = tmp_path / "pinned-policy.json"
    policy.write_bytes(b"signed-public-key-policy-placeholder")
    cache = tmp_path / "catalog.json"
    cache.write_bytes(b"signed-cache-placeholder")
    return cache, policy, hashlib.sha256(policy.read_bytes()).hexdigest()


def test_offline_adapter_calls_only_verified_loaders(tmp_path: Path) -> None:
    cache, policy, digest = paths(tmp_path)
    keyring = object()
    with (
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_digest_pinned_trust_policy",
            return_value=SimpleNamespace(keyring=keyring),
        ) as load_key,
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_catalog_cache",
            return_value=fixture_snapshot(),
        ) as load_cache,
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("subprocess.run", side_effect=AssertionError("process")),
    ):
        output = inspect_offline_catalog_preview(
            catalog_cache=cache,
            trust_policy=policy,
            pinned_policy_sha256=digest,
            now=NOW,
        )
    assert "0.8.0" in output
    load_key.assert_called_once_with(policy.read_bytes(), pinned_sha256=digest)
    load_cache.assert_called_once_with(cache, trust=keyring, now=NOW)


@pytest.mark.parametrize("bad", ["", "A" * 64, "f" * 63, "z" * 64, None, 1])
def test_bad_pins_refuse_before_read(tmp_path: Path, bad: Any) -> None:
    cache, policy, _ = paths(tmp_path)
    with patch(
        "paper_data_suite.evergreen_catalog_preview.load_catalog_cache",
        side_effect=AssertionError("not called"),
    ):
        with pytest.raises(CatalogPreviewError, match="SHA-256"):
            inspect_offline_catalog_preview(
                catalog_cache=cache,
                trust_policy=policy,
                pinned_policy_sha256=bad,
                now=NOW,
            )


@pytest.mark.parametrize("when", [datetime(2026, 10, 24, 16), None])
def test_naive_clock_rejected(tmp_path: Path, when: Any) -> None:
    cache, policy, digest = paths(tmp_path)
    with pytest.raises(CatalogPreviewError, match="timezone-aware"):
        inspect_offline_catalog_preview(
            catalog_cache=cache,
            trust_policy=policy,
            pinned_policy_sha256=digest,
            now=when,
        )


@pytest.mark.parametrize("source", ["policy", "cache"])
def test_unsafe_symlink_refused(tmp_path: Path, source: str) -> None:
    cache, policy, digest = paths(tmp_path)
    selected = policy if source == "policy" else cache
    symlink = tmp_path / "link.json"
    try:
        symlink.symlink_to(selected)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(CatalogPreviewError, match="unsafe"):
        inspect_offline_catalog_preview(
            catalog_cache=symlink if source == "cache" else cache,
            trust_policy=symlink if source == "policy" else policy,
            pinned_policy_sha256=digest,
            now=NOW,
        )


def test_missing_and_oversize_files_fail_closed(tmp_path: Path) -> None:
    cache, policy, digest = paths(tmp_path)
    policy.unlink()
    with pytest.raises(CatalogPreviewError, match="unavailable"):
        inspect_offline_catalog_preview(
            catalog_cache=cache,
            trust_policy=policy,
            pinned_policy_sha256=digest,
            now=NOW,
        )
    policy.write_bytes(b"a" * (24 * 1024 + 1))
    with pytest.raises(CatalogPreviewError, match="size"):
        inspect_offline_catalog_preview(
            catalog_cache=cache,
            trust_policy=policy,
            pinned_policy_sha256=digest,
            now=NOW,
        )


def test_failed_trust_policy_and_catalog_do_not_fallback(tmp_path: Path) -> None:
    cache, policy, digest = paths(tmp_path)
    with patch(
        "paper_data_suite.evergreen_catalog_preview.load_digest_pinned_trust_policy",
        side_effect=TrustProvisioningError("wrong pin"),
    ):
        with pytest.raises(CatalogPreviewError, match="could not be authenticated"):
            inspect_offline_catalog_preview(
                catalog_cache=cache,
                trust_policy=policy,
                pinned_policy_sha256=digest,
                now=NOW,
            )
    with (
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_digest_pinned_trust_policy",
            return_value=SimpleNamespace(keyring=object()),
        ),
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_catalog_cache",
            side_effect=CatalogStateError("expired"),
        ),
    ):
        with pytest.raises(CatalogPreviewError, match="could not be authenticated"):
            inspect_offline_catalog_preview(
                catalog_cache=cache,
                trust_policy=policy,
                pinned_policy_sha256=digest,
                now=NOW,
            )


def test_absent_cache_snapshot_refuses(tmp_path: Path) -> None:
    cache, policy, digest = paths(tmp_path)
    with (
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_digest_pinned_trust_policy",
            return_value=SimpleNamespace(keyring=object()),
        ),
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_catalog_cache",
            return_value=None,
        ),
    ):
        with pytest.raises(CatalogPreviewError, match="missing"):
            inspect_offline_catalog_preview(
                catalog_cache=cache,
                trust_policy=policy,
                pinned_policy_sha256=digest,
                now=NOW,
            )


def test_default_modules_parser_remains_backward_compatible() -> None:
    parsed = cli.build_parser().parse_args(["modules"])
    assert parsed.catalog_cache is None
    assert parsed.trust_policy is None
    assert parsed.trust_sha256 is None
    assert parsed.command == "modules"


def test_modules_catalog_parser_accepts_explicit_triplet() -> None:
    args = cli.build_parser().parse_args(
        [
            "modules",
            "--catalog-cache",
            "cache.json",
            "--trust-policy",
            "policy.json",
            "--trust-sha256",
            DIGEST,
        ]
    )
    assert args.catalog_cache == Path("cache.json")
    assert args.trust_policy == Path("policy.json")
    assert args.trust_sha256 == DIGEST


@pytest.mark.parametrize("option", ["catalog_cache", "trust_policy", "trust_sha256"])
def test_partial_cli_trust_flags_refuse_without_fallback(
    capsys: pytest.CaptureFixture[str], option: str
) -> None:
    kwargs = {option: Path("something") if option != "trust_sha256" else DIGEST}
    with (
        patch.object(
            cli, "_resolved_inventory", side_effect=AssertionError("legacy fallback")
        ),
        patch.object(
            cli,
            "inspect_offline_catalog_preview",
            side_effect=AssertionError("no partial read"),
        ),
    ):
        assert cli._run_modules(**kwargs) == 2
    assert "requires --catalog-cache" in capsys.readouterr().err


def test_explicit_cli_preview_does_not_call_legacy_inventory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(cli, "_resolved_inventory", side_effect=AssertionError("legacy")),
        patch.object(
            cli, "inspect_offline_catalog_preview", return_value="diagnostic preview\n"
        ) as preview,
    ):
        assert (
            cli._run_modules(
                catalog_cache=Path("cache"),
                trust_policy=Path("policy"),
                trust_sha256=DIGEST,
            )
            == 0
        )
    assert capsys.readouterr().out == "diagnostic preview\n"
    assert preview.call_args.kwargs["pinned_policy_sha256"] == DIGEST
    assert isinstance(preview.call_args.kwargs["now"], datetime)


def test_invalid_cli_cache_refuses_without_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(cli, "_resolved_inventory", side_effect=AssertionError("legacy")),
        patch.object(
            cli,
            "inspect_offline_catalog_preview",
            side_effect=CatalogPreviewError("invalid signature"),
        ),
    ):
        assert (
            cli._run_modules(
                catalog_cache=Path("cache"),
                trust_policy=Path("policy"),
                trust_sha256=DIGEST,
            )
            == 1
        )
    result = capsys.readouterr()
    assert "refused" in result.err
    assert result.out == ""


def test_main_routes_explicit_catalog_preview(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(
            cli,
            "inspect_offline_catalog_preview",
            return_value="verified metadata only\n",
        ),
        patch.object(cli, "_resolved_inventory", side_effect=AssertionError("legacy")),
    ):
        assert (
            cli.main(
                [
                    "modules",
                    "--catalog-cache",
                    "cache.json",
                    "--trust-policy",
                    "policy.json",
                    "--trust-sha256",
                    DIGEST,
                ]
            )
            == 0
        )
    assert capsys.readouterr().out == "verified metadata only\n"


def test_no_mutating_operations_on_preview(tmp_path: Path) -> None:
    cache, policy, digest = paths(tmp_path)
    original = (cache.read_bytes(), policy.read_bytes())
    with (
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_digest_pinned_trust_policy",
            return_value=SimpleNamespace(keyring=object()),
        ),
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_catalog_cache",
            return_value=fixture_snapshot(),
        ),
        patch("os.replace", side_effect=AssertionError("mutation")),
        patch("subprocess.run", side_effect=AssertionError("execution")),
    ):
        inspect_offline_catalog_preview(
            catalog_cache=cache,
            trust_policy=policy,
            pinned_policy_sha256=digest,
            now=NOW,
        )
    assert (cache.read_bytes(), policy.read_bytes()) == original
