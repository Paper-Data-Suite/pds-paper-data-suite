"""Offline exact-wheel evidence is not an installed operational capability."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.issue16_official_wheel_acceptance import (
    GROUP,
    OFFICIAL_WHEELS,
    OfficialWheel,
    inspect_official_wheel,
    inspect_wheelhouse,
    run_disposable_profile_smoke,
)


def _fixture(
    root: Path, *, metadata_name: str = "scoreform",
    include_entry: bool = True, target: str | None = None,
) -> OfficialWheel:
    spec = OFFICIAL_WHEELS[1]
    dest = root / spec.filename
    with zipfile.ZipFile(dest, "w") as archive:
        directory = "scoreform-0.13.0.dist-info/"
        archive.writestr(
            directory + "METADATA",
            "Metadata-Version: 2.1\nName: " + metadata_name +
            "\nVersion: 0.13.0\n",
        )
        if include_entry:
            name = target if target is not None else spec.target
            archive.writestr(
                directory + "entry_points.txt",
                f"[{GROUP}]\nscoreform = {name}\n",
            )
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    return replace(spec, digest=digest)


def test_fixed_public_asset_catalog_has_core_and_six_distinct_modules() -> None:
    assert [x.component for x in OFFICIAL_WHEELS] == [
        "core", "scoreform", "quillan", "concord", "meridian", "vitrine",
        "portia",
    ]
    assert all(len(x.digest) == 64 for x in OFFICIAL_WHEELS)
    assert all(x.url.startswith("https://github.com/Paper-Data-Suite/")
               for x in OFFICIAL_WHEELS)
    assert all(x.target is not None for x in OFFICIAL_WHEELS[1:])
    assert OFFICIAL_WHEELS[0].entry_point is None


def test_absent_official_assets_remain_unqualified(tmp_path: Path) -> None:
    results = inspect_wheelhouse(tmp_path)
    assert len(results) == 7
    assert all(x.status == "not_supplied" for x in results)


def test_valid_fixture_proves_only_digest_and_metadata(tmp_path: Path) -> None:
    spec = _fixture(tmp_path)
    evidence = inspect_official_wheel(tmp_path, spec)
    assert evidence.status == "verified_metadata"
    assert evidence.sha256 == spec.digest
    assert "ready" not in repr(evidence)


def test_sha_mismatch_refused_before_any_entry_point_parsing(
    tmp_path: Path,
) -> None:
    spec = _fixture(tmp_path)
    bad = replace(spec, digest="0" * 64)
    assert inspect_official_wheel(tmp_path, bad).status == "digest_mismatch"


def test_wrong_embedded_distribution_identity_is_refused(tmp_path: Path) -> None:
    spec = _fixture(tmp_path, metadata_name="other-project")
    assert inspect_official_wheel(tmp_path, spec).status == "invalid_metadata"


def test_missing_entry_point_is_not_qualified(tmp_path: Path) -> None:
    spec = _fixture(tmp_path, include_entry=False)
    assert inspect_official_wheel(tmp_path, spec).status == "entry_point_missing"


def test_unexpected_entry_point_target_is_not_qualified(tmp_path: Path) -> None:
    spec = _fixture(tmp_path, target="other.module:main")
    assert inspect_official_wheel(tmp_path, spec).status == "entry_point_mismatch"


def test_invalid_zip_is_not_qualified(tmp_path: Path) -> None:
    spec = OFFICIAL_WHEELS[1]
    path = tmp_path / spec.filename
    path.write_bytes(b"invalid zip")
    exact = replace(spec, digest=hashlib.sha256(path.read_bytes()).hexdigest())
    assert inspect_official_wheel(tmp_path, exact).status == "invalid_archive"


def test_disposable_smoke_requires_all_exact_wheels_before_any_pip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import issue16_official_wheel_acceptance as probe

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("must not create environment or execute profile without wheels")

    monkeypatch.setattr(probe.venv.EnvBuilder, "create", forbidden)
    with pytest.raises(ValueError, match="all seven"):
        run_disposable_profile_smoke(tmp_path)


def test_local_metadata_is_never_a_launcher_or_readiness_approval(
    tmp_path: Path,
) -> None:
    spec = _fixture(tmp_path)
    record = inspect_official_wheel(tmp_path, spec)
    assert record.status == "verified_metadata"
    assert not hasattr(record, "launch_state")
    assert not hasattr(record, "readiness_evaluated")
    assert not hasattr(record, "attention_evaluated")


def test_cli_missing_wheels_is_read_only_and_strict_when_requested(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.issue16_official_wheel_acceptance import main

    assert main(["--wheelhouse", str(tmp_path)]) == 0
    assert main(["--wheelhouse", str(tmp_path), "--require-complete"]) == 1
    output = capsys.readouterr().out
    assert "not_supplied" in output
    assert "not_observed" not in output
