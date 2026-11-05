"""Slice 146: truthful operational doctor and compatible Core setup gate."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import paper_data_suite.evergreen_local_doctor as local_doctor
from paper_data_suite.doctor import DiagnosticCheck, DiagnosticStatus, DoctorReport
from paper_data_suite.evergreen_local_compatibility import (
    ComponentAssessment,
    HistoricalEvidence,
    LocalCompatibilityReport,
    Provenance,
    Readiness,
)
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.workspace_setup import (
    CoreWorkspaceQualificationError,
    CoreWorkspaceServiceError,
    load_core_workspace_services,
)


def _row(
    component_id: str,
    version: str | None,
    *,
    readiness: Readiness = Readiness.COMPATIBLE,
    historical: HistoricalEvidence = (
        HistoricalEvidence.NOT_PREVIOUSLY_INTEGRATION_TESTED
    ),
    reasons: tuple[str, ...] = ("local_metadata_compatible",),
) -> ComponentAssessment:
    definition = next(
        x for x in APPROVED_COMPONENTS if x.component_id == component_id
    )
    return ComponentAssessment(
        component_id=component_id,
        distribution=definition.distribution,
        installed_version=version,
        readiness=readiness,
        historical_evidence=historical,
        provenance=Provenance.UNVERIFIED,
        reason_codes=reasons,
    )


def _report(*overrides: ComponentAssessment) -> LocalCompatibilityReport:
    supplied = {x.component_id: x for x in overrides}
    return LocalCompatibilityReport(tuple(
        supplied.get(x.component_id) or _row(
            x.component_id, None, readiness=Readiness.NOT_INSTALLED,
            reasons=("not_installed",),
        ) for x in APPROVED_COMPONENTS
    ))


def test_newer_core_quillan_are_reported_compatible_but_not_attested() -> None:
    report = local_doctor.collect_local_package_diagnostics(_report(
        _row("core", "0.6.6"), _row("quillan", "0.10.6"),
    ))
    assert report.exit_code == 0
    assert any(
        c.component_id == "quillan"
        and c.code == "package.locally_compatible"
        and "0.10.6" in c.summary
        for c in report.checks
    )
    assert any(
        c.component_id == "core"
        and c.code == "integration.not_previously_tested"
        for c in report.checks
    )
    assert any(
        c.component_id == "quillan"
        and c.code == "package.provenance_unverified"
        and c.status is DiagnosticStatus.WARN
        for c in report.checks
    )
    assert any(c.code == "package.optional_missing" for c in report.checks)


def test_missing_core_is_failure_but_missing_optional_is_not() -> None:
    result = local_doctor.collect_local_package_diagnostics(_report())
    assert result.failure_count == 1
    assert result.exit_code == 1
    assert result.checks[0].code == "package.required_missing"
    assert all(
        check.status is DiagnosticStatus.SKIP
        for check in result.checks[1:]
    )


def test_incompatible_optional_fails_separately_from_good_core() -> None:
    report = local_doctor.collect_local_package_diagnostics(_report(
        _row("core", "0.6.6"),
        _row(
            "concord", "0.3.4", readiness=Readiness.INCOMPATIBLE,
            reasons=("console_script_foreign_owner",),
        ),
    ))
    assert any(
        c.code == "package.incompatible" and c.component_id == "concord"
        and "console_script_foreign_owner" in (c.detail or "")
        for c in report.checks
    )
    assert any(
        c.code == "package.locally_compatible" and c.component_id == "core"
        for c in report.checks
    )


def test_historical_version_does_not_prove_authenticity() -> None:
    report = local_doctor.collect_local_package_diagnostics(_report(
        _row(
            "core", "0.6.3",
            historical=HistoricalEvidence.HISTORICAL_VERSION_MATCH,
        ),
    ))
    assert not any(
        c.code == "integration.not_previously_tested"
        and c.component_id == "core"
        for c in report.checks
    )
    assert any(
        c.code == "package.provenance_unverified"
        and c.component_id == "core" for c in report.checks
    )


def test_missing_report_row_fails_closed() -> None:
    with pytest.raises(Exception, match="assessment is missing"):
        local_doctor.collect_local_package_diagnostics(
            LocalCompatibilityReport((_row("core", "0.6.6"),))
        )


def test_core_public_callables_are_checked_without_version_pin() -> None:
    attributes: dict[str, dict[str, object]] = {}
    for module_name, name, _purpose in local_doctor._CORE_PUBLIC_CONTRACTS:
        attributes.setdefault(module_name, {})[name] = lambda: None
    names = {key: SimpleNamespace(**value) for key, value in attributes.items()}
    result = local_doctor._core_public_contract_checks(
        module_importer=lambda name: names[name]
    )
    assert result.exit_code == 0
    assert all(x.code == "core.contract_available" for x in result.checks)
    missing = local_doctor._core_public_contract_checks(
        module_importer=lambda name: SimpleNamespace()
    )
    assert missing.exit_code == 1


def test_newer_core_workspace_loader_accepts_existing_public_contracts() -> None:
    observed: list[str] = []
    module = SimpleNamespace(
        inspect_workspace_root=lambda explicit_root=None: None,
        ensure_workspace_root=lambda path, create=True: Path(path),
        save_workspace_root=lambda path: Path(path),
        clear_saved_workspace_root=lambda: False,
    )

    def importer(name: str) -> object:
        observed.append(name)
        return module

    loaded = load_core_workspace_services(
        version_lookup=lambda distribution: "0.6.6",
        module_importer=importer,
    )
    assert callable(loaded.inspect_workspace_root)
    assert observed == ["pds_core.workspace"]


def test_core_outside_supported_range_is_blocked_before_import() -> None:
    def fail(name: str) -> object:
        raise AssertionError(f"must not import {name}")

    with pytest.raises(CoreWorkspaceQualificationError, match="runtime range"):
        load_core_workspace_services(
            version_lookup=lambda distribution: "0.7.0",
            module_importer=fail,
        )


def test_newer_core_missing_public_callable_is_not_falsely_accepted() -> None:
    with pytest.raises(CoreWorkspaceServiceError, match="clear_saved_workspace_root"):
        load_core_workspace_services(
            version_lookup=lambda distribution: "0.6.6",
            module_importer=lambda name: SimpleNamespace(
                inspect_workspace_root=lambda: None,
                ensure_workspace_root=lambda path: Path(path),
                save_workspace_root=lambda path: Path(path),
            ),
        )


def test_operational_doctor_preserves_workspace_context_and_avoids_exact_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, object]] = []
    marker = DiagnosticCheck(
        section="Suite", code="suite.marker_mismatch",
        status=DiagnosticStatus.FAIL, summary="Legacy marker differs.",
    )
    monkeypatch.setattr(local_doctor, "load_release_compatibility_manifest", object)
    monkeypatch.setattr(
        local_doctor, "_environment_marker_check", lambda *a, **k: marker
    )
    monkeypatch.setattr(local_doctor, "_python_check", lambda *a, **k: DiagnosticCheck(
        section="Runtime", code="python.valid", status=DiagnosticStatus.PASS,
        summary="Runtime supported.",
    ))
    monkeypatch.setattr(local_doctor, "_suite_identity_check", lambda: DiagnosticCheck(
        section="Suite", code="suite.valid", status=DiagnosticStatus.PASS,
        summary="Suite installed.",
    ))
    monkeypatch.setattr(
        local_doctor, "_python_dependency_check", lambda **kwargs: DiagnosticCheck(
            section="Dependencies", code="pip.valid", status=DiagnosticStatus.PASS,
            summary="Dependencies supported.",
        ),
    )
    monkeypatch.setattr(
        local_doctor, "_core_public_contract_checks", lambda: DoctorReport(()),
    )
    monkeypatch.setattr(
        local_doctor, "_external_command_checks", lambda report: DoctorReport(()),
    )

    def workspace_collector(
        manifest: object, *, workspace: object, allow_compatible_core: bool,
    ) -> DoctorReport:
        observed.append(("workspace", workspace))
        assert allow_compatible_core
        return DoctorReport(())

    def providers_collector(
        manifest: object, *, allow_compatible_core: bool,
    ) -> DoctorReport:
        observed.append(("providers", allow_compatible_core))
        return DoctorReport(())

    monkeypatch.setattr(
        local_doctor, "collect_workspace_registry_diagnostics", workspace_collector,
    )
    monkeypatch.setattr(
        local_doctor, "collect_core_provider_diagnostics", providers_collector,
    )
    report = local_doctor.collect_version_tolerant_doctor_diagnostics(
        report=_report(_row("core", "0.6.6")),
        workspace=Path("D:/PDS classroom"),
    )
    assert observed == [
        ("workspace", Path("D:/PDS classroom")), ("providers", True),
    ]
    assert any(c.code == "suite.historical_marker_stale" for c in report.checks)
    assert report.exit_code == 0


def test_operational_doctor_skips_core_services_when_core_incompatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_doctor, "load_release_compatibility_manifest", object)
    missing_marker = DiagnosticCheck(
        section="Suite", code="suite.marker_missing", status=DiagnosticStatus.WARN,
        summary="No marker.",
    )
    monkeypatch.setattr(
        local_doctor, "_environment_marker_check",
        lambda *args, **kwargs: missing_marker,
    )
    monkeypatch.setattr(local_doctor, "_python_check", lambda *a, **k: DiagnosticCheck(
        section="Runtime", code="python.valid", status=DiagnosticStatus.PASS,
        summary="Runtime valid.",
    ))
    monkeypatch.setattr(local_doctor, "_suite_identity_check", lambda: DiagnosticCheck(
        section="Suite", code="suite.valid", status=DiagnosticStatus.PASS,
        summary="Suite valid.",
    ))
    pip_check = DiagnosticCheck(
        section="Dependencies", code="pip.valid", status=DiagnosticStatus.PASS,
        summary="Dependencies valid.",
    )
    monkeypatch.setattr(
        local_doctor, "_python_dependency_check", lambda **kwargs: pip_check
    )
    monkeypatch.setattr(
        local_doctor, "_external_command_checks", lambda report: DoctorReport(()),
    )
    monkeypatch.setattr(
        local_doctor, "collect_workspace_registry_diagnostics",
        lambda *a, **k: pytest.fail("workspace must not be accessed"),
    )
    monkeypatch.setattr(
        local_doctor, "collect_core_provider_diagnostics",
        lambda *a, **k: pytest.fail("providers must not be accessed"),
    )
    report = local_doctor.collect_version_tolerant_doctor_diagnostics(
        report=_report(),
    )
    assert report.exit_code == 1
    assert any(c.code == "core.contracts_unavailable" for c in report.checks)


def test_doctor_cli_bounds_local_metadata_inspection_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli
    from paper_data_suite.evergreen_local_compatibility import LocalInspectionError

    def fail(*, workspace: object = None) -> DoctorReport:
        del workspace
        raise LocalInspectionError("installed metadata unavailable")

    monkeypatch.setattr(cli, "collect_doctor_diagnostics", fail)
    assert cli.main(("doctor",)) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "Doctor inspection failed" in output.err
    assert "installed metadata unavailable" in output.err
