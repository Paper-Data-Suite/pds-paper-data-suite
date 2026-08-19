from __future__ import annotations

import json
import subprocess
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_data_suite.compatibility import (
    ComponentCompatibility,
    EntryPointExpectation,
    ExternalPrerequisite,
    PythonCompatibility,
    ReleaseArtifact,
    ReleaseCompatibilityManifest,
    SuiteCompatibility,
)
from paper_data_suite.doctor import (
    DiagnosticCheck,
    DiagnosticStatus,
    DoctorReport,
    EntryPointObservation,
    collect_doctor_diagnostics,
    collect_entry_point_core_diagnostics,
    collect_environment_dependency_diagnostics,
    collect_reduced_provider_diagnostics,
    collect_runtime_package_diagnostics,
    collect_workspace_registry_diagnostics,
    combine_reports,
    render_doctor_report,
)


def _component(
    component_id: str,
    distribution: str,
    version: str,
    *,
    required: bool,
    prerequisite: ExternalPrerequisite | None = None,
    capabilities: tuple[str, ...] = (),
    entry_points: tuple[EntryPointExpectation, ...] | None = None,
) -> ComponentCompatibility:
    return ComponentCompatibility(
        component_id=component_id,
        display_name=component_id.title(),
        repository=f"Paper-Data-Suite/pds-{component_id}",
        distribution=distribution,
        import_name=component_id,
        required=required,
        compatibility_status="supported",
        version=version,
        requires_python=">=3.11",
        release=ReleaseArtifact(
            tag=f"v{version}",
            wheel=f"{distribution.replace('-', '_')}-{version}-py3-none-any.whl",
            sha256="0" * 64,
        ),
        capabilities=capabilities,
        entry_points=(
            entry_points
            if entry_points is not None
            else (
                EntryPointExpectation(
                    group="console_scripts",
                    name=component_id,
                    target=f"{component_id}.cli:main",
                ),
            )
        ),
        external_prerequisites=((prerequisite,) if prerequisite is not None else ()),
    )


def _poppler_prerequisite() -> ExternalPrerequisite:
    return ExternalPrerequisite(
        prerequisite_id="poppler_pdftoppm",
        kind="command",
        required=True,
        commands=("pdftoppm",),
        platforms=("windows", "linux"),
        purpose="PDF scan rasterization",
    )


def _manifest() -> ReleaseCompatibilityManifest:
    return ReleaseCompatibilityManifest(
        record_type="paper_data_suite_release_compatibility_manifest",
        contract_version="1",
        suite=SuiteCompatibility(
            distribution="paper-data-suite",
            version="0.1.0.dev0",
            release_status="development",
        ),
        python=PythonCompatibility(
            specifier=">=3.11,<3.15",
            tested_minors=("3.11", "3.12", "3.13", "3.14"),
        ),
        components=(
            _component(
                "core",
                "pds-core",
                "0.6.0",
                required=True,
                capabilities=("shared_core",),
            ),
            _component(
                "optional",
                "pds-optional",
                "1.2.3",
                required=False,
                prerequisite=_poppler_prerequisite(),
            ),
        ),
    )


def _lookup(versions: dict[str, str]):
    def lookup(distribution: str) -> str:
        try:
            return versions[distribution]
        except KeyError as error:
            raise metadata.PackageNotFoundError(distribution) from error

    return lookup


def _marker_text(*, version: str = "0.1.0.dev0", digest: str = "a" * 64) -> str:
    return json.dumps(
        {
            "record_type": "paper_data_suite_environment",
            "contract_version": "1",
            "suite_version": version,
            "compatibility_manifest_sha256": digest,
        }
    )


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    def run(
        args: object,
        *,
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout
        assert args == ("python", "-m", "pip", "check")
        return subprocess.CompletedProcess(
            ["python", "-m", "pip", "check"],
            returncode,
            stdout,
            stderr,
        )

    return run


def test_diagnostic_check_rejects_blank_contract_fields() -> None:
    with pytest.raises(ValueError, match="code"):
        DiagnosticCheck(
            section="Runtime",
            code=" ",
            status=DiagnosticStatus.PASS,
            summary="healthy",
        )


def test_report_counts_failures_and_warnings_and_derives_exit_code() -> None:
    report = DoctorReport(
        (
            DiagnosticCheck(
                section="Runtime",
                code="runtime.pass",
                status=DiagnosticStatus.PASS,
                summary="healthy",
            ),
            DiagnosticCheck(
                section="Runtime",
                code="runtime.warn",
                status=DiagnosticStatus.WARN,
                summary="attention",
            ),
        )
    )
    assert report.failure_count == 0
    assert report.warning_count == 1
    assert report.exit_code == 0

    failed = DoctorReport(
        report.checks
        + (
            DiagnosticCheck(
                section="Packages",
                code="package.fail",
                status=DiagnosticStatus.FAIL,
                summary="blocked",
            ),
        )
    )
    assert failed.failure_count == 1
    assert failed.warning_count == 1
    assert failed.exit_code == 1
    assert tuple(check.code for check in failed.for_section("Runtime")) == (
        "runtime.pass",
        "runtime.warn",
    )


def test_combine_reports_preserves_order_and_exit_semantics() -> None:
    first = DoctorReport(
        (
            DiagnosticCheck(
                section="One",
                code="one.pass",
                status=DiagnosticStatus.PASS,
                summary="healthy",
            ),
        )
    )
    second = DoctorReport(
        (
            DiagnosticCheck(
                section="Two",
                code="two.fail",
                status=DiagnosticStatus.FAIL,
                summary="blocked",
            ),
        )
    )

    combined = combine_reports(first, second)
    assert tuple(check.code for check in combined.checks) == ("one.pass", "two.fail")
    assert combined.exit_code == 1


def test_runtime_package_diagnostics_accept_exact_qualified_environment() -> None:
    report = collect_runtime_package_diagnostics(
        _manifest(),
        python_version=(3, 11, 9),
        python_executable=r"C:\PDS\.venv\Scripts\python.exe",
        version_lookup=_lookup(
            {
                "paper-data-suite": "0.1.0.dev0",
                "pds-core": "0.6.0",
                "pds-optional": "1.2.3",
            }
        ),
    )

    assert report.exit_code == 0
    assert tuple((check.code, check.status) for check in report.checks) == (
        ("python.qualified", DiagnosticStatus.PASS),
        ("suite.version_match", DiagnosticStatus.PASS),
        ("package.version_match", DiagnosticStatus.PASS),
        ("package.version_match", DiagnosticStatus.PASS),
    )
    assert r"C:\PDS\.venv\Scripts\python.exe" in (report.checks[0].detail or "")


def test_runtime_package_diagnostics_fail_unqualified_python() -> None:
    report = collect_runtime_package_diagnostics(
        _manifest(),
        python_version=(3, 15, 0),
        python_executable="python",
        version_lookup=_lookup(
            {
                "paper-data-suite": "0.1.0.dev0",
                "pds-core": "0.6.0",
            }
        ),
    )

    check = report.checks[0]
    assert check.code == "python.unsupported"
    assert check.status is DiagnosticStatus.FAIL
    assert "3.11, 3.12, 3.13, 3.14" in (check.detail or "")
    assert report.exit_code == 1


def test_runtime_package_diagnostics_fail_when_suite_metadata_missing() -> None:
    report = collect_runtime_package_diagnostics(
        _manifest(),
        python_version=(3, 11, 0),
        python_executable="python",
        version_lookup=_lookup({"pds-core": "0.6.0"}),
    )

    check = report.checks[1]
    assert check.code == "suite.distribution_missing"
    assert check.status is DiagnosticStatus.FAIL
    assert "0.1.0.dev0" in (check.detail or "")


def test_runtime_package_diagnostics_fail_suite_version_mismatch() -> None:
    report = collect_runtime_package_diagnostics(
        _manifest(),
        python_version=(3, 11, 0),
        python_executable="python",
        version_lookup=_lookup(
            {
                "paper-data-suite": "9.9.9",
                "pds-core": "0.6.0",
            }
        ),
    )

    check = report.checks[1]
    assert check.code == "suite.version_mismatch"
    assert check.status is DiagnosticStatus.FAIL
    assert "9.9.9" in check.summary
    assert "0.1.0.dev0" in check.summary


def test_runtime_package_diagnostics_fail_required_component_absence() -> None:
    report = collect_runtime_package_diagnostics(
        _manifest(),
        python_version=(3, 11, 0),
        python_executable="python",
        version_lookup=_lookup({"paper-data-suite": "0.1.0.dev0"}),
    )

    core = report.checks[2]
    optional = report.checks[3]
    assert core.component_id == "core"
    assert core.code == "package.required_missing"
    assert core.status is DiagnosticStatus.FAIL
    assert optional.code == "package.optional_absent"
    assert optional.status is DiagnosticStatus.SKIP


def test_runtime_package_diagnostics_skip_optional_component_absence() -> None:
    report = collect_runtime_package_diagnostics(
        _manifest(),
        python_version=(3, 11, 0),
        python_executable="python",
        version_lookup=_lookup(
            {
                "paper-data-suite": "0.1.0.dev0",
                "pds-core": "0.6.0",
            }
        ),
    )

    optional = report.checks[3]
    assert optional.component_id == "optional"
    assert optional.code == "package.optional_absent"
    assert optional.status is DiagnosticStatus.SKIP
    assert report.exit_code == 0


def test_runtime_package_diagnostics_fail_component_version_mismatch() -> None:
    report = collect_runtime_package_diagnostics(
        _manifest(),
        python_version=(3, 11, 0),
        python_executable="python",
        version_lookup=_lookup(
            {
                "paper-data-suite": "0.1.0.dev0",
                "pds-core": "0.6.1",
                "pds-optional": "2.0.0",
            }
        ),
    )

    core = report.checks[2]
    optional = report.checks[3]
    assert core.code == "package.version_mismatch"
    assert core.status is DiagnosticStatus.FAIL
    assert "0.6.1" in core.summary
    assert "0.6.0" in core.summary
    assert optional.code == "package.version_mismatch"
    assert optional.status is DiagnosticStatus.FAIL
    assert report.failure_count == 2


def test_runtime_package_diagnostics_do_not_import_optional_components() -> None:
    observed: list[str] = []

    def lookup(distribution: str) -> str:
        observed.append(distribution)
        if distribution == "paper-data-suite":
            return "0.1.0.dev0"
        if distribution == "pds-core":
            return "0.6.0"
        raise metadata.PackageNotFoundError(distribution)

    collect_runtime_package_diagnostics(
        _manifest(),
        python_version=(3, 11, 0),
        python_executable="python",
        version_lookup=lookup,
    )

    assert observed == ["paper-data-suite", "pds-core", "pds-optional"]


def test_environment_dependency_diagnostics_accept_matching_marker_and_pip(
    tmp_path: Path,
) -> None:
    marker = tmp_path / ".pds-suite-environment.json"
    marker.write_text(_marker_text(), encoding="utf-8")

    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="win32",
        version_lookup=_lookup(
            {
                "pds-core": "0.6.0",
                "pds-optional": "1.2.3",
            }
        ),
        manifest_digest_lookup=lambda: "a" * 64,
        command_lookup=lambda command: rf"C:\Tools\{command}.exe",
        command_runner=_completed(0, "No broken requirements found.\n"),
    )

    assert tuple((check.code, check.status) for check in report.checks) == (
        ("suite.marker_match", DiagnosticStatus.PASS),
        ("dependencies.consistent", DiagnosticStatus.PASS),
        ("external.command_available", DiagnosticStatus.PASS),
    )
    assert marker.read_text(encoding="utf-8") == _marker_text()


def test_environment_dependency_diagnostics_warn_when_marker_missing(
    tmp_path: Path,
) -> None:
    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="win32",
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        command_runner=_completed(0),
    )

    marker = report.checks[0]
    prerequisite = report.checks[2]
    assert marker.code == "suite.marker_missing"
    assert marker.status is DiagnosticStatus.WARN
    assert prerequisite.code == "external.not_required"
    assert prerequisite.status is DiagnosticStatus.SKIP
    assert report.exit_code == 0
    assert tuple(tmp_path.iterdir()) == ()


def test_environment_dependency_diagnostics_fail_invalid_marker(tmp_path: Path) -> None:
    (tmp_path / ".pds-suite-environment.json").write_text("{", encoding="utf-8")

    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="darwin",
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        command_runner=_completed(0),
    )

    marker = report.checks[0]
    assert marker.code == "suite.marker_invalid"
    assert marker.status is DiagnosticStatus.FAIL
    assert report.exit_code == 1


def test_environment_dependency_diagnostics_fail_marker_composition_mismatch(
    tmp_path: Path,
) -> None:
    (tmp_path / ".pds-suite-environment.json").write_text(
        _marker_text(version="9.9.9", digest="b" * 64),
        encoding="utf-8",
    )

    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="darwin",
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        manifest_digest_lookup=lambda: "a" * 64,
        command_runner=_completed(0),
    )

    marker = report.checks[0]
    assert marker.code == "suite.marker_mismatch"
    assert marker.status is DiagnosticStatus.FAIL
    assert "suite version" in (marker.detail or "")
    assert "digest" in (marker.detail or "")


def test_environment_dependency_diagnostics_report_pip_check_failure(
    tmp_path: Path,
) -> None:
    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="darwin",
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        command_runner=_completed(
            1,
            stderr=(
                "broken-one requires dependency-x\n"
                "broken-two requires dependency-y\n"
            ),
        ),
    )

    dependency = report.checks[1]
    assert dependency.code == "dependencies.inconsistent"
    assert dependency.status is DiagnosticStatus.FAIL
    assert "broken-one" in (dependency.detail or "")
    assert "broken-two" in (dependency.detail or "")


def test_environment_dependency_diagnostics_bound_pip_check_output(
    tmp_path: Path,
) -> None:
    output = "\n".join(f"failure-{index}-" + "x" * 200 for index in range(10))
    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="darwin",
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        command_runner=_completed(1, stderr=output),
    )

    detail = report.checks[1].detail or ""
    assert len(detail) <= 500
    assert detail.endswith("...")


def test_environment_dependency_diagnostics_report_pip_timeout(
    tmp_path: Path,
) -> None:
    def timeout_runner(
        args: object,
        *,
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check
        raise subprocess.TimeoutExpired(args, timeout)

    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="darwin",
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        command_runner=timeout_runner,
        pip_check_timeout_seconds=3.0,
    )

    dependency = report.checks[1]
    assert dependency.code == "dependencies.pip_check_timeout"
    assert dependency.status is DiagnosticStatus.FAIL
    assert "3 seconds" in (dependency.detail or "")


def test_external_prerequisite_missing_is_failure_for_qualified_consumer(
    tmp_path: Path,
) -> None:
    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="linux",
        version_lookup=_lookup(
            {
                "pds-core": "0.6.0",
                "pds-optional": "1.2.3",
            }
        ),
        command_lookup=lambda command: None,
        command_runner=_completed(0),
    )

    prerequisite = report.checks[2]
    assert prerequisite.code == "external.command_missing"
    assert prerequisite.status is DiagnosticStatus.FAIL
    assert "Optional" in prerequisite.summary
    assert "pdftoppm" in (prerequisite.detail or "")


def test_external_prerequisite_skips_mismatched_optional_consumer(
    tmp_path: Path,
) -> None:
    lookups: list[str] = []

    def command_lookup(command: str) -> str | None:
        lookups.append(command)
        return None

    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="win32",
        version_lookup=_lookup(
            {
                "pds-core": "0.6.0",
                "pds-optional": "9.9.9",
            }
        ),
        command_lookup=command_lookup,
        command_runner=_completed(0),
    )

    prerequisite = report.checks[2]
    assert prerequisite.code == "external.not_required"
    assert prerequisite.status is DiagnosticStatus.SKIP
    assert lookups == []


def test_external_prerequisite_is_platform_scoped(tmp_path: Path) -> None:
    report = collect_environment_dependency_diagnostics(
        _manifest(),
        environment_root=tmp_path,
        python_executable="python",
        platform="darwin",
        version_lookup=_lookup(
            {
                "pds-core": "0.6.0",
                "pds-optional": "1.2.3",
            }
        ),
        command_lookup=lambda command: pytest.fail(
            f"unexpected command lookup: {command}"
        ),
        command_runner=_completed(0),
    )

    assert len(report.checks) == 2


def _entry_point(
    component_id: str,
    distribution: str,
    version: str,
    *,
    target: str | None = None,
) -> EntryPointObservation:
    return EntryPointObservation(
        group="console_scripts",
        name=component_id,
        target=target or f"{component_id}.cli:main",
        distribution=distribution,
        distribution_version=version,
    )


def _core_importer(*, missing: str | None = None, failing: str | None = None):
    attributes = {
        "pds_core.workspace": "inspect_workspace_root",
        "pds_core.school_years": "get_active_school_year",
        "pds_core.registry_audit": "get_academic_registry_status",
    }

    def importer(module_name: str) -> object:
        if module_name == failing:
            raise ImportError(f"cannot import {module_name}")
        attribute = attributes[module_name]
        if module_name == missing:
            return SimpleNamespace()
        return SimpleNamespace(**{attribute: lambda: None})

    return importer


def test_entry_point_core_diagnostics_accept_exact_metadata_and_core_contracts(
) -> None:
    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup(
            {
                "pds-core": "0.6.0",
                "pds-optional": "1.2.3",
            }
        ),
        entry_point_inventory_lookup=lambda: (
            _entry_point("optional", "pds-optional", "1.2.3"),
            _entry_point("core", "pds-core", "0.6.0"),
        ),
        module_importer=_core_importer(),
    )

    assert tuple((check.code, check.status) for check in report.checks) == (
        ("entry_point.match", DiagnosticStatus.PASS),
        ("entry_point.match", DiagnosticStatus.PASS),
        ("core.contract_available", DiagnosticStatus.PASS),
        ("core.contract_available", DiagnosticStatus.PASS),
        ("core.contract_available", DiagnosticStatus.PASS),
    )
    assert report.exit_code == 0


def test_entry_point_core_diagnostics_skip_unqualified_optional_component() -> None:
    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        entry_point_inventory_lookup=lambda: (
            _entry_point("core", "pds-core", "0.6.0"),
        ),
        module_importer=_core_importer(),
    )

    optional = report.checks[1]
    assert optional.component_id == "optional"
    assert optional.code == "entry_point.component_unqualified"
    assert optional.status is DiagnosticStatus.SKIP
    assert report.exit_code == 0


def test_entry_point_core_diagnostics_fail_missing_expected_entry_point() -> None:
    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup(
            {"pds-core": "0.6.0", "pds-optional": "1.2.3"}
        ),
        entry_point_inventory_lookup=lambda: (
            _entry_point("core", "pds-core", "0.6.0"),
        ),
        module_importer=_core_importer(),
    )

    check = report.checks[1]
    assert check.component_id == "optional"
    assert check.code == "entry_point.missing"
    assert check.status is DiagnosticStatus.FAIL


def test_entry_point_core_diagnostics_fail_target_mismatch() -> None:
    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup(
            {"pds-core": "0.6.0", "pds-optional": "1.2.3"}
        ),
        entry_point_inventory_lookup=lambda: (
            _entry_point("core", "pds-core", "0.6.0"),
            _entry_point(
                "optional",
                "pds-optional",
                "1.2.3",
                target="optional.bad:main",
            ),
        ),
        module_importer=_core_importer(),
    )

    check = report.checks[1]
    assert check.code == "entry_point.target_mismatch"
    assert check.status is DiagnosticStatus.FAIL
    assert "optional.bad:main" in (check.detail or "")


def test_entry_point_core_diagnostics_fail_wrong_owner() -> None:
    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup(
            {"pds-core": "0.6.0", "pds-optional": "1.2.3"}
        ),
        entry_point_inventory_lookup=lambda: (
            _entry_point("core", "pds-core", "0.6.0"),
            _entry_point("optional", "other-package", "4.5.6"),
        ),
        module_importer=_core_importer(),
    )

    check = report.checks[1]
    assert check.code == "entry_point.owner_mismatch"
    assert check.status is DiagnosticStatus.FAIL
    assert "other-package" in (check.detail or "")


def test_entry_point_core_diagnostics_fail_foreign_conflict() -> None:
    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup(
            {"pds-core": "0.6.0", "pds-optional": "1.2.3"}
        ),
        entry_point_inventory_lookup=lambda: (
            _entry_point("core", "pds-core", "0.6.0"),
            _entry_point("optional", "pds_optional", "1.2.3"),
            _entry_point("optional", "other-package", "4.5.6"),
        ),
        module_importer=_core_importer(),
    )

    check = report.checks[1]
    assert check.code == "entry_point.conflict"
    assert check.status is DiagnosticStatus.FAIL


def test_entry_point_core_diagnostics_fail_duplicate_owner_definition() -> None:
    optional = _entry_point("optional", "pds-optional", "1.2.3")
    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup(
            {"pds-core": "0.6.0", "pds-optional": "1.2.3"}
        ),
        entry_point_inventory_lookup=lambda: (
            _entry_point("core", "pds-core", "0.6.0"),
            optional,
            optional,
        ),
        module_importer=_core_importer(),
    )

    check = report.checks[1]
    assert check.code == "entry_point.duplicate"
    assert check.status is DiagnosticStatus.FAIL


def test_entry_point_inventory_failure_does_not_block_core_contract_checks() -> None:
    def unavailable() -> tuple[EntryPointObservation, ...]:
        raise RuntimeError("metadata unavailable")

    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        entry_point_inventory_lookup=unavailable,
        module_importer=_core_importer(),
    )

    assert report.checks[0].code == "entry_point.inventory_unavailable"
    assert tuple(check.code for check in report.checks[1:]) == (
        "core.contract_available",
        "core.contract_available",
        "core.contract_available",
    )


def test_core_contract_checks_skip_when_core_version_is_not_qualified() -> None:
    imported: list[str] = []

    def importer(module_name: str) -> object:
        imported.append(module_name)
        return SimpleNamespace()

    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.1"}),
        entry_point_inventory_lookup=lambda: (),
        module_importer=importer,
    )

    core = report.for_section("Core")
    assert len(core) == 1
    assert core[0].code == "core.contracts_skipped"
    assert core[0].status is DiagnosticStatus.SKIP
    assert imported == []


def test_core_contract_checks_isolate_missing_and_failed_public_contracts() -> None:
    def importer(module_name: str) -> object:
        if module_name == "pds_core.registry_audit":
            raise ImportError("registry import failed")
        if module_name == "pds_core.school_years":
            return SimpleNamespace()
        return SimpleNamespace(inspect_workspace_root=lambda: None)

    report = collect_entry_point_core_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        entry_point_inventory_lookup=lambda: (
            _entry_point("core", "pds-core", "0.6.0"),
        ),
        module_importer=importer,
    )

    core = report.for_section("Core")
    assert tuple((check.code, check.status) for check in core) == (
        ("core.contract_available", DiagnosticStatus.PASS),
        ("core.contract_missing", DiagnosticStatus.FAIL),
        ("core.contract_import_failed", DiagnosticStatus.FAIL),
    )
    assert report.failure_count == 2



def _workspace_services(
    *,
    status: SimpleNamespace,
    school_year: str | None = "2026-2027",
    registry: SimpleNamespace | None = None,
    observed_workspace: list[object] | None = None,
    observed_verify: list[bool] | None = None,
):
    registry_status = registry or SimpleNamespace(
        canonical_valid=True,
        contracts_compatible=True,
        catalog_state="ready",
        catalog_sources_current=True,
        lock_count=0,
        temporary_artifact_count=0,
        findings=(),
    )

    def inspect_workspace_root(workspace=None):
        if observed_workspace is not None:
            observed_workspace.append(workspace)
        return status

    def get_active_school_year(root):
        assert Path(root) == Path(status.root)
        return school_year

    def get_academic_registry_status(root, *, verify_manifests=False):
        assert Path(root) == Path(status.root)
        if observed_verify is not None:
            observed_verify.append(verify_manifests)
        return registry_status

    return SimpleNamespace(
        inspect_workspace_root=inspect_workspace_root,
        get_active_school_year=get_active_school_year,
        get_academic_registry_status=get_academic_registry_status,
    )


def _workspace_status(
    root: Path,
    *,
    exists: bool = True,
    is_dir: bool = True,
    is_writable: bool = True,
    source: str = "explicit",
) -> SimpleNamespace:
    return SimpleNamespace(
        root=root,
        source=source,
        exists=exists,
        is_dir=is_dir,
        is_writable=is_writable,
    )


def test_workspace_registry_diagnostics_use_explicit_override_read_only(
    tmp_path: Path,
) -> None:
    observed_workspace: list[object] = []
    observed_verify: list[bool] = []
    status = _workspace_status(tmp_path)
    services = _workspace_services(
        status=status,
        observed_workspace=observed_workspace,
        observed_verify=observed_verify,
    )
    before = tuple(tmp_path.iterdir())

    report = collect_workspace_registry_diagnostics(
        _manifest(),
        workspace=tmp_path,
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        services=services,
    )

    assert observed_workspace == [tmp_path]
    assert observed_verify == [False]
    assert tuple(tmp_path.iterdir()) == before
    assert tuple((check.code, check.status) for check in report.checks) == (
        ("workspace.accessible", DiagnosticStatus.PASS),
        ("school_year.active", DiagnosticStatus.PASS),
        ("registry.canonical_valid", DiagnosticStatus.PASS),
        ("registry.contracts_compatible", DiagnosticStatus.PASS),
        ("registry.catalog_ready", DiagnosticStatus.PASS),
        ("registry.coordination_clear", DiagnosticStatus.PASS),
        ("registry.findings_clear", DiagnosticStatus.PASS),
    )


def test_workspace_registry_diagnostics_skip_when_core_is_unqualified() -> None:
    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.1"}),
        module_importer=lambda name: pytest.fail(f"unexpected import: {name}"),
    )

    assert tuple(check.status for check in report.checks) == (
        DiagnosticStatus.SKIP,
        DiagnosticStatus.SKIP,
        DiagnosticStatus.SKIP,
    )
    assert report.checks[0].code == "workspace.core_unqualified"


def test_workspace_registry_diagnostics_warn_missing_workspace(tmp_path: Path) -> None:
    status = _workspace_status(
        tmp_path / "missing",
        exists=False,
        is_dir=False,
        is_writable=True,
        source="default",
    )
    calls: list[str] = []

    def school_year(root):
        calls.append("school")
        return "2026-2027"

    def registry(root, *, verify_manifests=False):
        calls.append("registry")
        raise AssertionError("registry should not run")

    services = SimpleNamespace(
        inspect_workspace_root=lambda workspace=None: status,
        get_active_school_year=school_year,
        get_academic_registry_status=registry,
    )
    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        services=services,
    )

    assert report.checks[0].code == "workspace.not_configured"
    assert report.checks[0].status is DiagnosticStatus.WARN
    assert tuple(check.status for check in report.checks[1:]) == (
        DiagnosticStatus.SKIP,
        DiagnosticStatus.SKIP,
    )
    assert calls == []
    assert report.exit_code == 0


@pytest.mark.parametrize(
    ("is_dir", "is_writable", "code"),
    [
        (False, False, "workspace.not_directory"),
        (True, False, "workspace.not_writable"),
    ],
)
def test_workspace_registry_diagnostics_fail_inaccessible_workspace(
    tmp_path: Path,
    is_dir: bool,
    is_writable: bool,
    code: str,
) -> None:
    status = _workspace_status(
        tmp_path,
        is_dir=is_dir,
        is_writable=is_writable,
    )
    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        services=_workspace_services(status=status),
    )

    assert report.checks[0].code == code
    assert report.checks[0].status is DiagnosticStatus.FAIL
    assert report.checks[1].status is DiagnosticStatus.SKIP
    assert report.checks[2].status is DiagnosticStatus.SKIP


def test_workspace_registry_diagnostics_isolate_school_year_failure(
    tmp_path: Path,
) -> None:
    status = _workspace_status(tmp_path)
    registry_calls: list[bool] = []

    def school_year(root):
        raise ValueError("invalid school year state")

    healthy_registry = SimpleNamespace(
        canonical_valid=True,
        contracts_compatible=True,
        catalog_state="ready",
        catalog_sources_current=True,
        lock_count=0,
        temporary_artifact_count=0,
        findings=(),
    )

    def registry(root, *, verify_manifests=False):
        registry_calls.append(verify_manifests)
        return healthy_registry

    services = SimpleNamespace(
        inspect_workspace_root=lambda workspace=None: status,
        get_active_school_year=school_year,
        get_academic_registry_status=registry,
    )
    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        services=services,
    )

    assert report.checks[1].code == "school_year.state_invalid"
    assert report.checks[1].status is DiagnosticStatus.FAIL
    assert registry_calls == [False]
    assert report.checks[2].status is DiagnosticStatus.PASS


def test_workspace_registry_diagnostics_warn_no_active_school_year(
    tmp_path: Path,
) -> None:
    status = _workspace_status(tmp_path)
    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        services=_workspace_services(status=status, school_year=None),
    )

    assert report.checks[1].code == "school_year.not_active"
    assert report.checks[1].status is DiagnosticStatus.WARN
    assert report.exit_code == 0


def test_workspace_registry_diagnostics_surface_registry_health(
    tmp_path: Path,
) -> None:
    status = _workspace_status(tmp_path)
    registry = SimpleNamespace(
        canonical_valid=False,
        contracts_compatible=False,
        catalog_state="invalid",
        catalog_sources_current=False,
        lock_count=2,
        temporary_artifact_count=1,
        findings=(
            SimpleNamespace(severity="error", code="catalog.snapshot_mismatch"),
            SimpleNamespace(severity="warning", code="locks.present"),
        ),
    )
    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        services=_workspace_services(status=status, registry=registry),
    )

    registry_checks = report.for_section("Core registry")
    assert tuple((check.code, check.status) for check in registry_checks) == (
        ("registry.canonical_invalid", DiagnosticStatus.FAIL),
        ("registry.contracts_incompatible", DiagnosticStatus.FAIL),
        ("registry.catalog_unhealthy", DiagnosticStatus.FAIL),
        ("registry.coordination_present", DiagnosticStatus.WARN),
        ("registry.findings_error", DiagnosticStatus.FAIL),
    )
    assert "catalog.snapshot_mismatch" in (registry_checks[-1].detail or "")
    assert report.exit_code == 1


def test_workspace_registry_diagnostics_warn_missing_catalog(tmp_path: Path) -> None:
    status = _workspace_status(tmp_path)
    registry = SimpleNamespace(
        canonical_valid=True,
        contracts_compatible=None,
        catalog_state="missing",
        catalog_sources_current=None,
        lock_count=0,
        temporary_artifact_count=0,
        findings=(),
    )
    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        services=_workspace_services(status=status, registry=registry),
    )

    registry_checks = report.for_section("Core registry")
    assert registry_checks[1].code == "registry.contracts_not_reported"
    assert registry_checks[1].status is DiagnosticStatus.SKIP
    assert registry_checks[2].code == "registry.catalog_missing"
    assert registry_checks[2].status is DiagnosticStatus.WARN
    assert report.exit_code == 0


def test_workspace_registry_diagnostics_isolate_registry_failure(
    tmp_path: Path,
) -> None:
    status = _workspace_status(tmp_path)

    def registry(root, *, verify_manifests=False):
        assert verify_manifests is False
        raise RuntimeError("registry unavailable")

    services = SimpleNamespace(
        inspect_workspace_root=lambda workspace=None: status,
        get_active_school_year=lambda root: "2026-2027",
        get_academic_registry_status=registry,
    )
    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        services=services,
    )

    assert report.checks[0].status is DiagnosticStatus.PASS
    assert report.checks[1].status is DiagnosticStatus.PASS
    assert report.checks[2].code == "registry.inspection_failed"
    assert report.checks[2].status is DiagnosticStatus.FAIL


def test_workspace_registry_diagnostics_fail_missing_core_service() -> None:
    def importer(module_name: str) -> object:
        if module_name == "pds_core.workspace":
            return SimpleNamespace()
        return SimpleNamespace(
            get_active_school_year=lambda root: None,
            get_academic_registry_status=lambda root, verify_manifests=False: None,
        )

    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        module_importer=importer,
    )

    assert report.checks[0].code == "workspace.core_service_unavailable"
    assert report.checks[0].status is DiagnosticStatus.FAIL
    assert report.checks[1].status is DiagnosticStatus.SKIP
    assert report.checks[2].status is DiagnosticStatus.SKIP


def test_workspace_registry_diagnostics_load_public_core_services(
    tmp_path: Path,
) -> None:
    status = _workspace_status(tmp_path, source="saved_config")
    imports: list[str] = []

    def importer(module_name: str) -> object:
        imports.append(module_name)
        if module_name == "pds_core.workspace":
            return SimpleNamespace(
                inspect_workspace_root=lambda workspace=None: status
            )
        if module_name == "pds_core.school_years":
            return SimpleNamespace(
                get_active_school_year=lambda root: "2026-2027"
            )
        if module_name == "pds_core.registry_audit":
            return SimpleNamespace(
                get_academic_registry_status=lambda root, verify_manifests=False: (
                    SimpleNamespace(
                        canonical_valid=True,
                        contracts_compatible=True,
                        catalog_state="ready",
                        catalog_sources_current=True,
                        lock_count=0,
                        temporary_artifact_count=0,
                        findings=(),
                    )
                )
            )
        raise AssertionError(module_name)

    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        module_importer=importer,
    )

    assert imports == [
        "pds_core.workspace",
        "pds_core.school_years",
        "pds_core.registry_audit",
    ]
    assert report.checks[0].status is DiagnosticStatus.PASS
    assert report.exit_code == 0


def test_workspace_registry_diagnostics_isolate_workspace_inspection_failure(
) -> None:
    def inspect(workspace=None):
        raise ValueError("workspace config is invalid")

    services = SimpleNamespace(
        inspect_workspace_root=inspect,
        get_active_school_year=lambda root: pytest.fail("unexpected school-year read"),
        get_academic_registry_status=lambda root, verify_manifests=False: (
            pytest.fail("unexpected registry read")
        ),
    )
    report = collect_workspace_registry_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
        services=services,
    )

    assert report.checks[0].code == "workspace.inspection_failed"
    assert report.checks[0].status is DiagnosticStatus.FAIL
    assert report.checks[1].status is DiagnosticStatus.SKIP
    assert report.checks[2].status is DiagnosticStatus.SKIP


def test_reduced_provider_diagnostics_are_explicit_skips() -> None:
    report = collect_reduced_provider_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.0"}),
    )

    assert tuple((check.code, check.status) for check in report.checks) == (
        ("providers.reduced_fidelity", DiagnosticStatus.SKIP),
        ("module.readiness_unavailable", DiagnosticStatus.SKIP),
    )
    assert report.exit_code == 0
    assert "module-private state is not inspected" in (report.checks[1].detail or "")


def test_reduced_provider_diagnostics_do_not_claim_health_without_exact_core() -> None:
    report = collect_reduced_provider_diagnostics(
        _manifest(),
        version_lookup=_lookup({"pds-core": "0.6.1"}),
    )

    assert all(check.status is DiagnosticStatus.SKIP for check in report.checks)
    assert "exact suite-qualified Core" in (report.checks[0].detail or "")


def test_collect_doctor_diagnostics_combines_supported_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.doctor as doctor

    manifest = _manifest()
    monkeypatch.setattr(doctor, "load_release_compatibility_manifest", lambda: manifest)

    def report(code: str, section: str) -> DoctorReport:
        return DoctorReport(
            (
                DiagnosticCheck(
                    section=section,
                    code=code,
                    status=DiagnosticStatus.PASS,
                    summary=code,
                ),
            )
        )

    monkeypatch.setattr(
        doctor,
        "collect_runtime_package_diagnostics",
        lambda active: report("runtime", "Runtime"),
    )
    monkeypatch.setattr(
        doctor,
        "collect_environment_dependency_diagnostics",
        lambda active: report("environment", "Suite"),
    )
    monkeypatch.setattr(
        doctor,
        "collect_entry_point_core_diagnostics",
        lambda active: report("entry", "Entry points"),
    )

    observed_workspace: list[object] = []

    def workspace_report(active: object, *, workspace: object = None) -> DoctorReport:
        observed_workspace.append(workspace)
        return report("workspace", "Workspace")

    monkeypatch.setattr(
        doctor,
        "collect_workspace_registry_diagnostics",
        workspace_report,
    )
    monkeypatch.setattr(
        doctor,
        "collect_reduced_provider_diagnostics",
        lambda active: report("providers", "Providers"),
    )

    combined = collect_doctor_diagnostics(workspace=Path("teacher-workspace"))
    assert tuple(check.code for check in combined.checks) == (
        "runtime",
        "environment",
        "entry",
        "workspace",
        "providers",
    )
    assert observed_workspace == [Path("teacher-workspace")]


def test_render_doctor_report_groups_sections_and_remediation() -> None:
    report = DoctorReport(
        (
            DiagnosticCheck(
                section="Packages",
                code="package.fail",
                status=DiagnosticStatus.FAIL,
                summary="Package is incompatible.",
                detail="Expected 1.0; observed 2.0.",
                remediation="Install the qualified package.",
            ),
            DiagnosticCheck(
                section="Runtime",
                code="python.pass",
                status=DiagnosticStatus.PASS,
                summary="Python is qualified.",
            ),
            DiagnosticCheck(
                section="Modules",
                code="module.skip",
                status=DiagnosticStatus.SKIP,
                summary="Readiness is unavailable.",
            ),
        )
    )

    rendered = render_doctor_report(report)
    assert rendered.startswith("Paper Data Suite doctor\n\nRuntime\n")
    assert rendered.index("Runtime\n") < rendered.index("Packages\n")
    assert "  FAIL  Package is incompatible." in rendered
    assert "        Expected 1.0; observed 2.0." in rendered
    assert "        Fix: Install the qualified package." in rendered
    assert "Overall\n  FAIL  1 blocker, 0 warnings." in rendered


def test_render_doctor_report_warns_without_failure() -> None:
    report = DoctorReport(
        (
            DiagnosticCheck(
                section="Suite",
                code="suite.warn",
                status=DiagnosticStatus.WARN,
                summary="Marker is missing.",
            ),
        )
    )
    assert "Overall\n  WARN  No blockers; 1 warning." in render_doctor_report(report)
