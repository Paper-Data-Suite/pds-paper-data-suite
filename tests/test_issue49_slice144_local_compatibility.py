"""Slice 144: pure offline compatibility tests (no installed-package mutation)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from paper_data_suite.evergreen_local_compatibility import (
    ComponentAssessment,
    ConsoleDeclaration,
    HistoricalEvidence,
    InstalledPackage,
    LocalInspectionError,
    Provenance,
    Readiness,
    assess_local_environment,
)
from paper_data_suite.evergreen_local_registry import (
    APPROVED_COMPONENTS,
    APPROVED_IDS,
)


def _installed(
    component_id: str, version: str, *, requires: tuple[str, ...] = ()
) -> InstalledPackage:
    definition = next(
        item for item in APPROVED_COMPONENTS if item.component_id == component_id
    )
    return InstalledPackage(
        definition.distribution,
        version,
        requires_python=">=3.11,<3.15",
        requires_dist=requires,
        entry_points=tuple(
            ConsoleDeclaration(entry.name, entry.target)
            for entry in definition.console_scripts
        ),
    )


def _core() -> InstalledPackage:
    return _installed("core", "0.6.6")


def _check(
    packages: tuple[InstalledPackage, ...], component_id: str
) -> ComponentAssessment:
    result = assess_local_environment(packages, python_version="3.13.7")
    component = result.for_component(component_id)
    assert component is not None
    return component


def test_registry_is_bounded_reviewable_and_includes_future_modules() -> None:
    assert APPROVED_IDS == frozenset(
        {"core", "scoreform", "quillan", "concord", "meridian", "vitrine", "portia"}
    )
    assert APPROVED_COMPONENTS[0].launchable is False
    assert len({c.component_id for c in APPROVED_COMPONENTS}) == 7
    assert len({c.distribution for c in APPROVED_COMPONENTS}) == 7
    for definition in APPROVED_COMPONENTS:
        assert definition.console_scripts
        assert len({e.name for e in definition.console_scripts}) == len(
            definition.console_scripts
        )
        assert all(":" in e.target for e in definition.console_scripts)
    for component_id in ("meridian", "portia"):
        component = next(
            c for c in APPROVED_COMPONENTS if c.component_id == component_id
        )
        assert component.historical_version is None


def test_newer_quillan_is_compatible_but_unqualified() -> None:
    result = _check(
        (_core(), _installed("quillan", "0.10.6", requires=("pds-core>=0.6.5,<0.7",))),
        "quillan",
    )
    assert result.readiness is Readiness.COMPATIBLE
    assert result.locally_compatible
    assert result.installed_version == "0.10.6"
    assert result.historical_evidence is (
        HistoricalEvidence.NOT_PREVIOUSLY_INTEGRATION_TESTED
    )
    assert result.provenance is Provenance.UNVERIFIED
    assert result.reason_codes == ("local_metadata_compatible",)


def test_historical_version_match_never_claims_wheel_authentication() -> None:
    result = _check((_core(), _installed("quillan", "0.9.0")), "quillan")
    assert result.historical_evidence is HistoricalEvidence.HISTORICAL_VERSION_MATCH
    assert result.provenance is Provenance.UNVERIFIED


@pytest.mark.parametrize(
    ("component_id", "current_version"),
    [
        ("scoreform", "0.13.0"),
        ("quillan", "0.10.6"),
        ("concord", "0.3.4"),
        ("meridian", "0.4.2"),
        ("vitrine", "0.4.0"),
        ("portia", "0.2.0"),
    ],
)
def test_approved_current_console_contracts(
    component_id: str, current_version: str
) -> None:
    result = _check((_core(), _installed(component_id, current_version)), component_id)
    assert result.readiness is Readiness.COMPATIBLE
    assert result.provenance is Provenance.UNVERIFIED


def test_unapproved_console_script_is_not_added_to_registry() -> None:
    package = InstalledPackage(
        "other-tool",
        "1.0.0",
        entry_points=(ConsoleDeclaration("other-tool", "other_tool.cli:main"),),
    )
    report = assess_local_environment((_core(), package), python_version="3.13.7")
    assert report.for_component("other-tool") is None


def test_missing_optional_module_is_distinct_from_broken_module() -> None:
    row = _check((_core(),), "quillan")
    assert row.readiness is Readiness.NOT_INSTALLED
    assert row.reason_codes == ("distribution_missing",)


def test_missing_core_blocks_otherwise_present_module() -> None:
    row = _check((_installed("quillan", "0.10.6"),), "quillan")
    assert row.readiness is Readiness.INCOMPATIBLE
    assert "core_not_compatible" in row.reason_codes


def test_newer_core_within_suite_public_range_is_accepted() -> None:
    row = _check((_core(),), "core")
    assert row.readiness is Readiness.COMPATIBLE
    assert row.historical_evidence is (
        HistoricalEvidence.NOT_PREVIOUSLY_INTEGRATION_TESTED
    )


def test_core_outside_suite_range_blocks_dependents() -> None:
    bad_core = _installed("core", "0.7.0")
    row = _check((bad_core, _installed("quillan", "0.10.6")), "quillan")
    assert row.readiness is Readiness.INCOMPATIBLE
    assert "core_not_compatible" in row.reason_codes
    assert "suite_core_range_incompatible" in _check((bad_core,), "core").reason_codes


def test_declared_core_requirement_must_match_current_installed_core() -> None:
    row = _check(
        (_core(), _installed("quillan", "0.10.6", requires=("pds-core>=0.6.7,<0.7",))),
        "quillan",
    )
    assert "dependency_version_incompatible" in row.reason_codes


def test_declared_runtime_dependency_missing_blocks_only_its_consumer() -> None:
    row = _check(
        (_core(), _installed("scoreform", "0.13.0", requires=("opencv-python>=4",))),
        "scoreform",
    )
    assert "dependency_missing" in row.reason_codes
    assert _check((_core(),), "core").readiness is Readiness.COMPATIBLE


def test_declared_python_requirement_is_enforced() -> None:
    newer = replace(_installed("quillan", "0.10.6"), requires_python=">=3.14")
    assert "python_incompatible" in _check((_core(), newer), "quillan").reason_codes


def test_missing_python_requirement_fails_closed_for_approved_module() -> None:
    newer = replace(_installed("quillan", "0.10.6"), requires_python=None)
    assert "python_requirement_missing" in (
        _check((_core(), newer), "quillan").reason_codes
    )


def test_editable_module_not_mistaken_for_official_wheel() -> None:
    newer = replace(_installed("quillan", "0.10.6"), editable=True)
    assert "editable_pds_install" in _check((_core(), newer), "quillan").reason_codes


def test_module_outside_current_python_environment_is_rejected() -> None:
    newer = replace(_installed("quillan", "0.10.6"), inside_environment=False)
    assert "distribution_outside_environment" in (
        _check((_core(), newer), "quillan").reason_codes
    )


def test_prerelease_and_local_versions_are_not_stable_official_releases() -> None:
    for version in ("0.11.0rc1", "0.11.0.dev5", "0.10.6+local"):
        row = _check((_core(), _installed("quillan", version)), "quillan")
        assert "nonstable_version_not_approved" in row.reason_codes


def test_wrong_console_script_target_is_refused() -> None:
    newer = replace(
        _installed("quillan", "0.10.6"),
        entry_points=(ConsoleDeclaration("quillan", "wrong.cli:main"),),
    )
    assert "console_script_target_mismatch" in (
        _check((_core(), newer), "quillan").reason_codes
    )


def test_missing_expected_console_script_is_refused() -> None:
    newer = replace(_installed("quillan", "0.10.6"), entry_points=())
    assert "console_script_missing" in _check((_core(), newer), "quillan").reason_codes


def test_foreign_owner_cannot_claim_approved_script() -> None:
    newer = replace(_installed("quillan", "0.10.6"), entry_points=())
    foreign = InstalledPackage(
        "foreign",
        "1.0",
        entry_points=(ConsoleDeclaration("quillan", "quillan.cli:main"),),
    )
    assert "console_script_foreign_owner" in (
        _check((_core(), newer, foreign), "quillan").reason_codes
    )


def test_duplicate_and_case_shadowed_script_are_refused() -> None:
    foreign = InstalledPackage(
        "foreign",
        "1.0",
        entry_points=(ConsoleDeclaration("QUILLAN", "quillan.cli:main"),),
    )
    row = _check((_core(), _installed("quillan", "0.10.6"), foreign), "quillan")
    assert "console_script_ambiguous" in row.reason_codes


def test_duplicate_distribution_identity_is_refused() -> None:
    row = _check(
        (_core(), _installed("quillan", "0.10.6"), _installed("quillan", "0.10.6")),
        "quillan",
    )
    assert "distribution_duplicate" in row.reason_codes


def test_invalid_dependency_requirement_is_refused() -> None:
    row = _check(
        (_core(), _installed("quillan", "0.10.6", requires=("not a requirement???",))),
        "quillan",
    )
    assert "dependency_requirement_invalid" in row.reason_codes


def test_direct_url_dependencies_not_approved_by_local_metadata() -> None:
    row = _check(
        (
            _core(),
            _installed(
                "quillan", "0.10.6", requires=("custom @ https://example.com/a.whl",)
            ),
        ),
        "quillan",
    )
    assert "direct_url_dependency_unsupported" in row.reason_codes


def test_optional_extra_is_evaluated_when_explicitly_requested() -> None:
    root = _installed("scoreform", "0.13.0", requires=("qrcode[pil]>=8",))
    qrcode = InstalledPackage(
        "qrcode", "8.2", requires_dist=('Pillow>=11; extra == "pil"',)
    )
    assert "dependency_missing" in (
        _check((_core(), root, qrcode), "scoreform").reason_codes
    )
    pillow = InstalledPackage("Pillow", "11.3")
    assert (
        _check((_core(), root, qrcode, pillow), "scoreform").readiness
        is Readiness.COMPATIBLE
    )


def test_unrequested_extra_is_not_assumed() -> None:
    root = _installed("scoreform", "0.13.0", requires=("qrcode>=8",))
    qrcode = InstalledPackage(
        "qrcode", "8.2", requires_dist=('Pillow>=11; extra == "pil"',)
    )
    assert (
        _check((_core(), root, qrcode), "scoreform").readiness
        is Readiness.COMPATIBLE
    )


def test_transitive_dependency_failure_blocks_consumer() -> None:
    root = _installed("quillan", "0.10.6", requires=("package-a>=1",))
    dep = InstalledPackage("package-a", "1.2", requires_dist=("package-b>=2",))
    row = _check((_core(), root, dep), "quillan")
    assert "dependency_missing" in row.reason_codes


def test_invalid_distribution_count_and_python_version_refuse() -> None:
    with pytest.raises(LocalInspectionError):
        assess_local_environment((_core(),), python_version="not-a-python-version")


def test_results_are_immutable_and_deterministic() -> None:
    packages = (_core(), _installed("quillan", "0.10.6"))
    assert assess_local_environment(
        packages, python_version="3.13.7"
    ) == assess_local_environment(packages, python_version="3.13.7")
    with pytest.raises(AttributeError):
        setattr(_check(packages, "quillan"), "installed_version", "0.9.0")



def test_case_changed_console_script_name_fails_even_without_competing_owner() -> None:
    newer = replace(
        _installed("quillan", "0.10.6"),
        entry_points=(ConsoleDeclaration("QUILLAN", "quillan.cli:main"),),
    )
    assert "console_script_name_mismatch" in (
        _check((_core(), newer), "quillan").reason_codes
    )


def test_malformed_core_version_is_reported_not_raised() -> None:
    row = _check((_installed("core", "not-a-version"),), "core")
    assert "version_invalid" in row.reason_codes
    assert "suite_core_range_incompatible" in row.reason_codes


def test_installed_metadata_adapter_is_read_only_and_uses_current_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from importlib import metadata

    import paper_data_suite.evergreen_local_compatibility as local

    environment = tmp_path / "active-env"
    site_packages = environment / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)

    class FakeDistribution:
        def __init__(self, identity: str, script: str, target: str) -> None:
            self.metadata = {"Name": identity, "Requires-Python": ">=3.11"}
            self.version = "0.6.6" if identity == "pds-core" else "0.10.6"
            self.requires = ["pds-core>=0.6.5,<0.7"] if identity == "quillan" else []
            self.entry_points = [metadata.EntryPoint(script, target, "console_scripts")]

        def locate_file(self, name: str) -> Path:
            assert name == ""
            return site_packages

        def read_text(self, name: str) -> str | None:
            assert name in {"WHEEL", "direct_url.json"}
            return "Wheel-Version: 1.0" if name == "WHEEL" else None

    fake = (
        FakeDistribution("pds-core", "core", "pds_core.core_menu:main"),
        FakeDistribution("quillan", "quillan", "quillan.cli:main"),
    )
    fake[0].entry_points.append(
        metadata.EntryPoint("pds-core", "pds_core.cli:main", "console_scripts")
    )
    monkeypatch.setattr(local.metadata, "distributions", lambda: iter(fake))
    monkeypatch.setattr(local.sys, "prefix", str(environment))
    observed = local.observe_active_packages()
    assert len(observed) == 2
    assert all(item.inside_environment for item in observed)
    assert _check(observed, "quillan").readiness is Readiness.COMPATIBLE
    assert not (tmp_path / "workspace").exists()


def test_adapter_marks_editable_direct_url_without_trusting_it() -> None:
    import paper_data_suite.evergreen_local_compatibility as local

    class FakeDist:
        def read_text(self, name: str) -> str | None:
            assert name == "direct_url.json"
            return '{"url":"file:///somewhere", "dir_info":{"editable":true}}'

    assert local._is_editable(FakeDist()) is True  # type: ignore[arg-type]
