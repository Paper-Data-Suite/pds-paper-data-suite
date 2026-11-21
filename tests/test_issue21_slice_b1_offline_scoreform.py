"""Suite #21 B1 negative matrix: wheel bytes/metadata gate never loads code."""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from paper_data_suite.component_inspection import EntryPointObservation
from scripts import issue21_scoreform_offline_preflight as probe
from scripts.issue16_official_wheel_acceptance import OfficialWheel, WheelEvidence

_GROUP = "paper_data_suite.module_operations"


def _entry(
    *,
    name: str = "scoreform",
    owner: str = "scoreform",
    version: str = "0.13.0",
    target: str = "scoreform.pds_operations:get_module_operations_profile",
) -> EntryPointObservation:
    return EntryPointObservation(
        group=_GROUP, name=name, target=target,
        distribution=owner, distribution_version=version,
    )


def _fake_wheel(
    _directory: Path, spec: OfficialWheel
) -> WheelEvidence:
    return WheelEvidence(
        component=spec.component, version=spec.version,
        sha256=spec.digest, status="verified_metadata",
    )


def _version(name: str) -> str:
    return next(
        spec.version for spec in probe._BY_OWNER.values()
        if spec.distribution == name
    )


def _go(
    root: Path,
    *,
    wheel_inspector: Callable[[Path, OfficialWheel], WheelEvidence] = _fake_wheel,
    version_lookup: Callable[[str], str] = _version,
    entries: tuple[EntryPointObservation, ...] = (_entry(),),
) -> probe.ScoreFormOfflineEvidence:
    return probe.inspect_scoreform_offline_release(
        root, wheel_inspector=wheel_inspector,
        version_lookup=version_lookup,
        entrypoint_reader=lambda: entries,
    )


def _snapshot(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(
        (
            f.relative_to(root).as_posix(),
            hashlib.sha256(f.read_bytes()).hexdigest(),
        )
        for f in root.rglob("*") if f.is_file()
    ))


def test_source_level_offline_evidence_is_not_admission(tmp_path: Path) -> None:
    calls: list[str] = []

    def inspect(path: Path, spec: OfficialWheel) -> WheelEvidence:
        calls.append(spec.component)
        assert path == tmp_path
        return _fake_wheel(path, spec)

    original = _snapshot(tmp_path)
    result = _go(tmp_path, wheel_inspector=inspect)
    assert result.code == "metadata_consistent_not_admitted"
    assert result.metadata_consistent
    assert result.examined == ("core", "scoreform")
    assert calls == ["core", "scoreform"]
    assert "profile" not in repr(result)
    assert original == _snapshot(tmp_path)


def test_missing_or_relative_wheelhouse_fails_before_any_inspector(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def forbidden(path: Path, spec: OfficialWheel) -> WheelEvidence:
        calls.append(spec.component)
        return _fake_wheel(path, spec)

    for path in (Path("relative"), tmp_path / "missing", Path(tmp_path.anchor)):
        result = _go(path, wheel_inspector=forbidden)
        assert result.code == "wheelhouse_unavailable"
    assert calls == []


def test_symlinked_wheelhouse_fails_closed_when_supported(
    tmp_path: Path,
) -> None:
    link = tmp_path / "foreign_wheelhouse_link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit directory symlink fixture")
    assert _go(link).code == "wheelhouse_unavailable"


@pytest.mark.parametrize(
    "which,status",
    [
        ("core", "digest_mismatch"),
        ("scoreform", "digest_mismatch"),
        ("scoreform", "entry_point_mismatch"),
        ("scoreform", "not_supplied"),
    ],
)
def test_any_unverified_official_wheel_prevents_progress(
    tmp_path: Path, which: str, status: str,
) -> None:
    def inspect(path: Path, spec: OfficialWheel) -> WheelEvidence:
        base = _fake_wheel(path, spec)
        if spec.component == which:
            return WheelEvidence(
                component=base.component,
                version=base.version,
                sha256=base.sha256,
                status=status,  # type: ignore[arg-type]
            )
        return base

    result = _go(tmp_path, wheel_inspector=inspect)
    assert result.code == "wheel_evidence_unverified"
    assert not result.metadata_consistent


def test_wrong_wheel_evidence_identity_even_with_success_code_refused(
    tmp_path: Path,
) -> None:
    def inspect(path: Path, spec: OfficialWheel) -> WheelEvidence:
        result = _fake_wheel(path, spec)
        if spec.component == "scoreform":
            return WheelEvidence(
                component="foreign_provider", version=result.version,
                sha256=result.sha256, status=result.status,
            )
        return result

    assert _go(
        tmp_path, wheel_inspector=inspect
    ).code == "wheel_evidence_unverified"


def test_wheel_reader_crash_is_static_and_private_safe(
    tmp_path: Path,
) -> None:
    def broken(path: Path, spec: OfficialWheel) -> WheelEvidence:
        raise RuntimeError("SECRET_PRIVATE_STUDENT_PATH")

    result = _go(tmp_path, wheel_inspector=broken)
    assert result.code == "wheel_evidence_unverified"
    assert "SECRET" not in repr(result)
    assert str(tmp_path) not in repr(result)


@pytest.mark.parametrize("owner", ["pds-core", "scoreform"])
def test_different_installed_versions_do_not_count_as_release_proof(
    tmp_path: Path, owner: str,
) -> None:
    def changed(distribution: str) -> str:
        if distribution == owner:
            return "99.0.0"
        return _version(distribution)

    result = _go(tmp_path, version_lookup=changed)
    assert result.code == "installed_version_mismatch"


def test_uninstalled_dependency_is_a_distinct_static_refusal(
    tmp_path: Path,
) -> None:
    from importlib.metadata import PackageNotFoundError

    def missing(name: str) -> str:
        raise PackageNotFoundError(name)

    assert _go(
        tmp_path, version_lookup=missing
    ).code == "installed_version_mismatch"


def test_version_reader_exception_is_redacted(tmp_path: Path) -> None:
    def bad(name: str) -> str:
        raise OSError("PRIVATE_CREDENTIAL_PATH")

    result = _go(tmp_path, version_lookup=bad)
    assert result.code == "installed_metadata_unavailable"
    assert "PRIVATE" not in repr(result)


@pytest.mark.parametrize(
    "entries",
    [
        (),
        (_entry(name="ScoreForm"),),
        (_entry(owner="foreign-distribution"),),
        (_entry(version="0.12.0"),),
        (_entry(target="scoreform.evil:load"),),
        (_entry(), _entry()),
        (_entry(), _entry(owner="foreign-distribution")),
    ],
)
def test_unapproved_duplicate_or_wrong_owner_entrypoint_refused(
    tmp_path: Path, entries: tuple[EntryPointObservation, ...],
) -> None:
    result = _go(tmp_path, entries=entries)
    assert result.code == "entry_point_unqualified"
    assert "foreign" not in repr(result)


def test_unrelated_foreign_entrypoints_do_not_get_loaded(
    tmp_path: Path,
) -> None:
    unrelated = _entry(name="unapproved", target="foreign:secret")
    result = _go(tmp_path, entries=(_entry(), unrelated))
    assert result.code == "metadata_consistent_not_admitted"


def test_huge_entrypoint_census_refused_without_imports(
    tmp_path: Path,
) -> None:
    result = probe.inspect_scoreform_offline_release(
        tmp_path,
        wheel_inspector=_fake_wheel,
        version_lookup=_version,
        entrypoint_reader=lambda: (_entry() for _ in range(258)),
    )
    assert result.code == "installed_metadata_unavailable"


def test_entrypoint_inventory_failure_does_not_leak_exception(
    tmp_path: Path,
) -> None:
    def broken() -> tuple[EntryPointObservation, ...]:
        raise RuntimeError("PRIVATE_STUDENT_DATA")

    result = probe.inspect_scoreform_offline_release(
        tmp_path,
        wheel_inspector=_fake_wheel,
        version_lookup=_version,
        entrypoint_reader=broken,
    )
    assert result.code == "installed_metadata_unavailable"
    assert "PRIVATE" not in repr(result)


def test_no_producer_package_imported_by_probe(tmp_path: Path) -> None:
    prefixes = ("scoreform", "quillan", "concord")
    before = {
        name for name in sys.modules
        if name.split(".", 1)[0] in prefixes
    }
    assert _go(tmp_path).metadata_consistent
    after = {
        name for name in sys.modules
        if name.split(".", 1)[0] in prefixes
    }
    assert after == before


def test_cli_prints_static_nonadmission_status_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        probe, "inspect_scoreform_offline_release",
        lambda path: _go(path),
    )
    assert probe.main(["--wheelhouse", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert output == (
        "PDS21_B1_OFFLINE_SCORE_FORM metadata_consistent_not_admitted\n"
    )
    assert str(tmp_path) not in output


def test_cli_refusal_returns_nonzero_without_private_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "nonexistent_wheelhouse"
    assert probe.main(["--wheelhouse", str(missing)]) == 1
    output = capsys.readouterr().out
    assert "wheelhouse_unavailable" in output
    assert str(missing) not in output
