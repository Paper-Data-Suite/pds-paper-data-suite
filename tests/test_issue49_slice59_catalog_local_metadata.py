"""Slice 59: local metadata correlation remains diagnostic, never launch proof."""

from __future__ import annotations

from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice58_catalog_preview as prior

from paper_data_suite import cli
from paper_data_suite.evergreen_catalog_local_metadata import (
    LocalCatalogMetadataError,
    LocalMetadataFinding,
    compare_local_catalog_metadata,
    render_local_catalog_metadata,
)
from paper_data_suite.evergreen_catalog_preview import (
    CatalogPreviewError,
    inspect_offline_catalog_preview,
)


def _lookup(**values: Any) -> Any:
    def version(distribution: str) -> str:
        item = values.get(distribution)
        if item is None:
            raise metadata.PackageNotFoundError(distribution)
        if isinstance(item, Exception):
            raise item
        return str(item)

    return version


def test_matching_release_is_still_only_metadata() -> None:
    report = compare_local_catalog_metadata(
        prior.fixture_snapshot(),
        version_lookup=_lookup(**{"pds-quillan": "0.8.0"}),
    )
    assert [row.component_id for row in report.rows] == ["quillan", "scoreform"]
    assert report.rows[0].finding is LocalMetadataFinding.SIGNED_VERSION_MATCH
    assert report.rows[0].signed_wheel_sha256 == "b" * 64
    assert report.rows[1].finding is LocalMetadataFinding.NOT_REPORTED
    assert "NO_INSTALLED_BYTE" in report.authority
    rendered = render_local_catalog_metadata(
        prior.fixture_snapshot(),
        version_lookup=_lookup(**{"pds-quillan": "0.8.0"}),
    )
    assert "BYTES NOT CHECKED" in rendered
    assert "Launch eligibility: NOT VERIFIED" in rendered
    assert "pds launch quillan" not in rendered


@pytest.mark.parametrize(
    "value,finding",
    [
        ("0.7.0", LocalMetadataFinding.SIGNED_VERSION_REVOKED),
        ("99.0.0", LocalMetadataFinding.VERSION_NOT_IN_SIGNED_RELEASES),
        (None, LocalMetadataFinding.NOT_REPORTED),
        (RuntimeError("metadata failure"), LocalMetadataFinding.METADATA_UNREADABLE),
    ],
)
def test_distinguishes_unverified_metadata_cases(
    value: Any, finding: LocalMetadataFinding
) -> None:
    report = compare_local_catalog_metadata(
        prior.fixture_snapshot(), version_lookup=_lookup(**{"pds-quillan": value})
    )
    assert report.rows[0].finding is finding


def test_registered_component_without_publisher_release_document() -> None:
    report = compare_local_catalog_metadata(
        prior.fixture_snapshot(),
        version_lookup=_lookup(**{"pds-scoreform": "0.1.0"}),
    )
    assert report.rows[1].finding is LocalMetadataFinding.SIGNED_RELEASE_DOCUMENT_ABSENT
    assert report.rows[1].signed_wheel_sha256 is None


def test_bad_reported_version_redacted() -> None:
    report = compare_local_catalog_metadata(
        prior.fixture_snapshot(),
        version_lookup=lambda _distribution: "0.8.0\nLaunch eligible",
    )
    assert all(
        row.finding is LocalMetadataFinding.METADATA_UNREADABLE for row in report.rows
    )
    assert all(row.reported_version is None for row in report.rows)


def test_bad_snapshot_and_reader_fail_closed() -> None:
    with pytest.raises(LocalCatalogMetadataError):
        compare_local_catalog_metadata(object())  # type: ignore[arg-type]
    with pytest.raises(LocalCatalogMetadataError):
        compare_local_catalog_metadata(
            prior.fixture_snapshot(),
            version_lookup=None,  # type: ignore[arg-type]
        )


def test_metadata_reader_only_sees_signed_registry_distributions() -> None:
    observed: list[str] = []

    def lookup(distribution: str) -> str:
        observed.append(distribution)
        raise metadata.PackageNotFoundError(distribution)

    compare_local_catalog_metadata(prior.fixture_snapshot(), version_lookup=lookup)
    assert observed == ["pds-quillan", "pds-scoreform"]


def test_preview_opt_in_correlation_with_real_loader_boundary(tmp_path: Path) -> None:
    cache, policy, digest = prior.paths(tmp_path)
    with (
        patch(
            (
                "paper_data_suite.evergreen_catalog_preview."
                "load_digest_pinned_trust_policy"
            ),
            return_value=type("Pinned", (), {"keyring": object()})(),
        ),
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_catalog_cache",
            return_value=prior.fixture_snapshot(),
        ),
        patch(
            "paper_data_suite.evergreen_catalog_local_metadata.metadata.version",
            side_effect=metadata.PackageNotFoundError("not installed"),
        ),
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("subprocess.run", side_effect=AssertionError("execution")),
        patch("os.replace", side_effect=AssertionError("mutation")),
    ):
        output = inspect_offline_catalog_preview(
            catalog_cache=cache,
            trust_policy=policy,
            pinned_policy_sha256=digest,
            now=prior.NOW,
            compare_local_metadata=True,
        )
    assert "offline signed release catalog" in output
    assert "Local interpreter package metadata" in output
    assert "no package version reported" in output


def test_default_preview_does_not_read_local_metadata(tmp_path: Path) -> None:
    cache, policy, digest = prior.paths(tmp_path)
    with (
        patch(
            (
                "paper_data_suite.evergreen_catalog_preview."
                "load_digest_pinned_trust_policy"
            ),
            return_value=type("Pinned", (), {"keyring": object()})(),
        ),
        patch(
            "paper_data_suite.evergreen_catalog_preview.load_catalog_cache",
            return_value=prior.fixture_snapshot(),
        ),
        patch(
            (
                "paper_data_suite.evergreen_catalog_local_metadata."
                "render_local_catalog_metadata"
            ),
            side_effect=AssertionError("no metadata read"),
        ),
    ):
        output = inspect_offline_catalog_preview(
            catalog_cache=cache,
            trust_policy=policy,
            pinned_policy_sha256=digest,
            now=prior.NOW,
        )
    assert "Local interpreter package metadata" not in output


def test_cli_flag_requires_full_authenticated_catalog_triplet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli._run_modules(compare_local_metadata=True) == 2
    assert "requires --catalog-cache" in capsys.readouterr().err
    parsed = cli.build_parser().parse_args(["modules", "--compare-local-metadata"])
    assert parsed.compare_local_metadata is True
    assert cli.build_parser().parse_args(["modules"]).compare_local_metadata is False


def test_cli_dispatches_local_compare_only_on_explicit_opt_in(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(
            cli, "inspect_offline_catalog_preview", return_value="compare result\n"
        ) as preview,
        patch.object(
            cli, "_resolved_inventory", side_effect=AssertionError("legacy path")
        ),
    ):
        assert (
            cli.main(
                [
                    "modules",
                    "--catalog-cache",
                    "cache",
                    "--trust-policy",
                    "policy",
                    "--trust-sha256",
                    "a" * 64,
                    "--compare-local-metadata",
                ]
            )
            == 0
        )
    assert capsys.readouterr().out == "compare result\n"
    assert preview.call_args.kwargs["compare_local_metadata"] is True
    assert isinstance(preview.call_args.kwargs["now"], datetime)


def test_cli_invalid_catalog_does_not_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(
            cli,
            "inspect_offline_catalog_preview",
            side_effect=CatalogPreviewError("invalid signature"),
        ),
        patch.object(
            cli, "_resolved_inventory", side_effect=AssertionError("legacy fallback")
        ),
    ):
        assert (
            cli.main(
                [
                    "modules",
                    "--catalog-cache",
                    "cache",
                    "--trust-policy",
                    "policy",
                    "--trust-sha256",
                    "a" * 64,
                    "--compare-local-metadata",
                ]
            )
            == 1
        )
    assert "refused" in capsys.readouterr().err
