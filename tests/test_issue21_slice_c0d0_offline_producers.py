"""Suite #21 C0/D0: Quillan and Concord offline release evidence witnesses.

No producer entry points or factories are loaded. Real wheel bytes remain
the responsibility of the already-qualified #16 inspector.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from paper_data_suite.component_inspection import EntryPointObservation
from scripts import issue21_other_producers_offline_preflight as cli
from scripts import issue21_scoreform_offline_preflight as core_probe
from scripts.issue16_official_wheel_acceptance import (
    OfficialWheel,
    WheelEvidence,
)

OWNERS = ("quillan", "concord")
GROUP = "paper_data_suite.module_operations"


def _spec(owner: str) -> OfficialWheel:
    return core_probe._RELEASE_BY_COMPONENT[owner]


def _entry(owner: str) -> EntryPointObservation:
    spec = _spec(owner)
    assert spec.entry_point is not None and spec.target is not None
    return EntryPointObservation(
        group=GROUP,
        name=spec.entry_point,
        target=spec.target,
        distribution=spec.distribution,
        distribution_version=spec.version,
    )


def _synthetic_wheel(
    _wheelhouse: Path, spec: OfficialWheel
) -> WheelEvidence:
    return WheelEvidence(
        component=spec.component,
        version=spec.version,
        sha256=spec.digest,
        status="verified_metadata",
    )


def _version(distribution: str) -> str:
    return next(
        spec.version for spec in core_probe._RELEASE_BY_COMPONENT.values()
        if spec.distribution == distribution
    )


def _run(
    root: Path, owner: str, *,
    reader: Callable[[], Iterable[EntryPointObservation]] | None = None,
    wheel_inspector: Callable[[Path, OfficialWheel], WheelEvidence] = (
        _synthetic_wheel
    ),
    version_lookup: Callable[[str], str] = _version,
) -> core_probe.ModuleOfflineEvidence:
    if reader is None:
        reader = lambda: (_entry(owner),)
    return core_probe.inspect_named_producer_offline_release(
        root,
        owner_id=owner,
        wheel_inspector=wheel_inspector,
        version_lookup=version_lookup,
        entrypoint_reader=reader,
    )


def _digest_state(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(
        (
            path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob("*") if path.is_file()
    ))


@pytest.mark.parametrize("owner", OWNERS)
def test_exact_core_plus_selected_owner_wheels_are_inspected_only(
    tmp_path: Path, owner: str
) -> None:
    observed: list[str] = []

    def inspect(path: Path, spec: OfficialWheel) -> WheelEvidence:
        assert path == tmp_path
        observed.append(spec.component)
        return _synthetic_wheel(path, spec)

    witness = tmp_path / "synthetic_offline_witness.txt"
    witness.write_bytes(b"Synthetic evidence: no student information")
    before = _digest_state(tmp_path)
    assert before
    result = _run(tmp_path, owner, wheel_inspector=inspect)
    assert result.code == "metadata_consistent_not_admitted"
    assert result.metadata_consistent
    assert result.examined == ("core", owner)
    assert observed == ["core", owner]
    assert before == _digest_state(tmp_path)
    assert str(tmp_path) not in repr(result)


@pytest.mark.parametrize("owner", OWNERS)
def test_only_owner_selected_identity_must_be_unambiguous(
    tmp_path: Path, owner: str
) -> None:
    unselected = "concord" if owner == "quillan" else "quillan"
    other = _entry(unselected)
    result = _run(
        tmp_path, owner, reader=lambda: (_entry(owner), other)
    )
    assert result.code == "metadata_consistent_not_admitted"
    assert result.examined == ("core", owner)


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("bad_spec", ("core", "owner"))
def test_bad_published_wheel_refused_without_installed_metadata(
    tmp_path: Path, owner: str, bad_spec: str
) -> None:
    inspected: list[str] = []
    versions: list[str] = []

    def inspect(path: Path, spec: OfficialWheel) -> WheelEvidence:
        inspected.append(spec.component)
        row = _synthetic_wheel(path, spec)
        if spec.component == (owner if bad_spec == "owner" else "core"):
            return WheelEvidence(
                component=row.component,
                version=row.version,
                sha256=row.sha256,
                status="digest_mismatch",
            )
        return row

    def version(name: str) -> str:
        versions.append(name)
        return _version(name)

    result = _run(
        tmp_path, owner, wheel_inspector=inspect,
        version_lookup=version,
    )
    assert result.code == "wheel_evidence_unverified"
    assert versions == []
    assert inspected


@pytest.mark.parametrize("owner", OWNERS)
def test_wrong_installed_producer_version_refused(
    tmp_path: Path, owner: str
) -> None:
    def version(distribution: str) -> str:
        if distribution == _spec(owner).distribution:
            return "0.0.0"
        return _version(distribution)

    assert _run(
        tmp_path, owner, version_lookup=version
    ).code == "installed_version_mismatch"


@pytest.mark.parametrize("owner", OWNERS)
def test_foreign_and_duplicate_entrypoint_declarations_refused(
    tmp_path: Path, owner: str
) -> None:
    original = _entry(owner)
    foreign = EntryPointObservation(
        group=original.group, name=original.name,
        target=original.target, distribution="foreign-private-producer",
        distribution_version=original.distribution_version,
    )
    for rows in (
        (),
        (foreign,),
        (original, original),
        (original, foreign),
    ):
        result = _run(tmp_path, owner, reader=lambda rows=rows: rows)
        assert result.code == "entry_point_unqualified"
        assert "foreign-private-producer" not in repr(result)


@pytest.mark.parametrize("owner", OWNERS)
def test_wrong_target_or_metadata_reader_crash_refused(
    tmp_path: Path, owner: str
) -> None:
    original = _entry(owner)
    changed = EntryPointObservation(
        group=original.group, name=original.name,
        target="foreign.secret:run", distribution=original.distribution,
        distribution_version=original.distribution_version,
    )
    assert _run(
        tmp_path, owner, reader=lambda: (changed,)
    ).code == "entry_point_unqualified"

    def broken() -> tuple[EntryPointObservation, ...]:
        raise RuntimeError("PRIVATE_STUDENT_TRACEBACK")

    result = _run(tmp_path, owner, reader=broken)
    assert result.code == "installed_metadata_unavailable"
    assert "PRIVATE_STUDENT_TRACEBACK" not in repr(result)


def test_unapproved_owner_is_refused_before_any_io(tmp_path: Path) -> None:
    attempts: list[str] = []

    def forbidden(path: Path, spec: OfficialWheel) -> WheelEvidence:
        attempts.append(spec.component)
        return _synthetic_wheel(path, spec)

    result = _run(
        tmp_path, "portia", wheel_inspector=forbidden
    )
    assert result.code == "owner_unapproved"
    assert result.examined == ()
    assert attempts == []


@pytest.mark.parametrize("owner", OWNERS)
def test_offline_checks_do_not_import_any_producer_module(
    tmp_path: Path, owner: str
) -> None:
    names = ("scoreform", "quillan", "concord")
    before = {
        name for name in sys.modules
        if name.split(".", 1)[0] in names
    }
    assert _run(tmp_path, owner).metadata_consistent
    after = {
        name for name in sys.modules
        if name.split(".", 1)[0] in names
    }
    assert before == after


@pytest.mark.parametrize("owner", OWNERS)
def test_cli_prints_only_static_nonadmission_code(
    tmp_path: Path, owner: str, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = core_probe.inspect_named_producer_offline_release

    def synthetic(
        path: Path, *, owner_id: str
    ) -> core_probe.ModuleOfflineEvidence:
        return original(
            path, owner_id=owner_id,
            wheel_inspector=_synthetic_wheel,
            version_lookup=_version,
            entrypoint_reader=lambda: (_entry(owner_id),),
        )

    monkeypatch.setattr(
        cli, "inspect_named_producer_offline_release", synthetic
    )
    assert cli.main([
        "--owner", owner, "--wheelhouse", str(tmp_path)
    ]) == 0
    output = capsys.readouterr().out
    assert output == (
        f"PDS21_C0D0_OFFLINE_{owner.upper()} "
        "metadata_consistent_not_admitted\n"
    )
    assert str(tmp_path) not in output


@pytest.mark.parametrize("owner", OWNERS)
def test_cli_missing_wheelhouse_refuses_without_paths(
    tmp_path: Path, owner: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "missing"
    assert cli.main([
        "--owner", owner, "--wheelhouse", str(path)
    ]) == 1
    output = capsys.readouterr().out
    assert output == f"PDS21_C0D0_OFFLINE_{owner.upper()} wheelhouse_unavailable\n"
    assert str(path) not in output
