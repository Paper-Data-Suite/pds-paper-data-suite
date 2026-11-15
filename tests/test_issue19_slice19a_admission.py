"""Suite #19A: bounded preview-only candidate admission; never producer execution."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from paper_data_suite.evergreen_local_compatibility import (
    ComponentAssessment,
    HistoricalEvidence,
    LocalCompatibilityReport,
    Provenance,
    Readiness,
)
from paper_data_suite.returned_paper_admission import (
    PaperAdmissionError,
    PaperAdmissionV1,
    ProducerAdmissionV1,
    inspect_paper_admission,
)


def _row(component_id: str, distribution: str, version: str | None,
         readiness: Readiness = Readiness.COMPATIBLE) -> ComponentAssessment:
    return ComponentAssessment(
        component_id=component_id,
        distribution=distribution,
        installed_version=version,
        readiness=readiness,
        historical_evidence=HistoricalEvidence.NOT_PREVIOUSLY_INTEGRATION_TESTED,
        provenance=Provenance.UNVERIFIED,
        reason_codes=("local_metadata_compatible",),
    )


def _report(*, core: ComponentAssessment | None = None,
            scoreform: ComponentAssessment | None = None,
            quillan: ComponentAssessment | None = None) -> LocalCompatibilityReport:
    return LocalCompatibilityReport((
        core if core is not None else _row("core", "pds-core", "0.6.6"),
        scoreform if scoreform is not None else _row(
            "scoreform", "scoreform", "0.13.0"
        ),
        quillan if quillan is not None else _row("quillan", "quillan", "0.10.6"),
    ))


def _inspect(
    report: LocalCompatibilityReport | None = None, *,
    platform_tag: str = "win32", python_version: tuple[int, int] = (3, 11),
) -> PaperAdmissionV1:
    # Override runtime to make the fixture independent of the test host.
    return inspect_paper_admission(
        report=report if report is not None else _report(),
        platform_tag=platform_tag, python_version=python_version,
    )


def test_all_exact_versions_are_candidates_not_execution_permission() -> None:
    result = _inspect()
    assert result.processing_status == "preview_only"
    assert result.core_state == "exact_release_candidate"
    assert result.exact_release_candidates == ("scoreform", "quillan")
    assert result.qualified_modules == frozenset()
    assert not result.producers[0].may_dispatch
    assert not result.producers[1].may_dispatch


@pytest.mark.parametrize("platform_tag", ["linux", "win32"])
def test_both_qualified_platforms_are_candidates(platform_tag: str) -> None:
    assert _inspect(platform_tag=platform_tag).exact_release_candidates == (
        "scoreform", "quillan"
    )
    assert not _inspect(platform_tag=platform_tag).qualified_modules


@pytest.mark.parametrize("platform_tag,python_version", [
    ("darwin", (3, 11)), ("cygwin", (3, 11)), ("win32", (3, 12)),
    ("linux", (3, 13)), ("linux", (3, 14)), ("win32", (3, 10)),
])
def test_unqualified_os_or_python_is_preview_only_with_reason(
    platform_tag: str, python_version: tuple[int, int],
) -> None:
    result = _inspect(platform_tag=platform_tag, python_version=python_version)
    assert result.core_state == "runtime_unqualified"
    assert all(row.state == "runtime_unqualified" for row in result.producers)
    assert result.qualified_modules == frozenset()


def test_future_scoreform_version_never_inherits_prior_exact_qualification() -> None:
    scoreform = _row("scoreform", "scoreform", "0.13.1")
    result = _inspect(_report(scoreform=scoreform))
    assert result.producers[0].state == "version_unqualified"
    assert result.producers[1].state == "exact_release_candidate"
    assert result.exact_release_candidates == ("quillan",)
    assert not result.qualified_modules


def test_future_core_version_is_not_silent_admission() -> None:
    result = _inspect(_report(core=_row("core", "pds-core", "0.6.7")))
    assert result.core_state == "version_unqualified"
    assert all(row.state == "core_unqualified" for row in result.producers)


def test_absent_core_blocks_both_producers_without_invented_profile() -> None:
    result = _inspect(_report(
        core=_row("core", "pds-core", None, Readiness.NOT_INSTALLED)
    ))
    assert result.core_state == "not_installed"
    assert all(row.state == "core_unqualified" for row in result.producers)


def test_missing_optional_quillan_isolated_from_scoreform_candidate() -> None:
    result = _inspect(_report(
        quillan=_row("quillan", "quillan", None, Readiness.NOT_INSTALLED)
    ))
    assert result.producers[0].state == "exact_release_candidate"
    assert result.producers[1].state == "not_installed"
    assert not result.qualified_modules


def test_incompatible_scoreform_does_not_hide_quillan_candidate() -> None:
    result = _inspect(_report(
        scoreform=_row("scoreform", "scoreform", "0.13.0", Readiness.INCOMPATIBLE)
    ))
    assert result.producers[0].state == "incompatible"
    assert result.producers[1].state == "exact_release_candidate"


def test_spoofed_distribution_not_candidate() -> None:
    result = _inspect(_report(quillan=_row("quillan", "foreign-quillan", "0.10.6")))
    assert result.producers[1].state == "metadata_unavailable"
    assert result.exact_release_candidates == ("scoreform",)


def test_duplicate_approved_component_rows_are_ambiguous_and_refused() -> None:
    base = _report()
    duplicated = LocalCompatibilityReport(base.components + (base.components[2],))
    result = _inspect(duplicated)
    assert result.producers[1].state == "metadata_unavailable"
    assert not result.qualified_modules


def test_missing_registered_core_row_fails_preview_only() -> None:
    base = _report()
    result = _inspect(LocalCompatibilityReport(base.components[1:]))
    assert result.core_state == "metadata_unavailable"
    assert all(row.state == "core_unqualified" for row in result.producers)


def test_valid_installed_version_alone_does_not_clear_unverified_provenance() -> None:
    result = _inspect()
    assert not result.qualified_modules
    assert all(not p.may_dispatch for p in result.producers)


def test_contract_is_immutable_and_rejects_any_injected_dispatch_grant() -> None:
    result = _inspect()
    with pytest.raises(FrozenInstanceError):
        result.core_state = "incompatible"  # type: ignore[misc]
    with pytest.raises(PaperAdmissionError):
        replace(result, qualified_modules=frozenset({"quillan"}))
    with pytest.raises(PaperAdmissionError):
        replace(result, processing_status="ready")  # type: ignore[arg-type]
    with pytest.raises(PaperAdmissionError):
        replace(result.producers[0], may_dispatch=True)  # type: ignore[arg-type]


def test_unapproved_producer_cannot_be_fabricated() -> None:
    with pytest.raises(PaperAdmissionError):
        ProducerAdmissionV1(
            "portia", "0.2.0", "exact_release_candidate", "0.2.0"
        )  # type: ignore[arg-type]


@pytest.mark.parametrize("platform_tag,python_version", [
    ("", (3, 11)), ("x" * 33, (3, 11)),
    ("win32", (3,)), ("linux", (3, True)), ("linux", (3, -1)),
])
def test_invalid_runtime_shape_is_refused(
    platform_tag: str, python_version: tuple[int, ...],
) -> None:
    with pytest.raises(PaperAdmissionError):
        inspect_paper_admission(
            report=_report(), platform_tag=platform_tag,
            python_version=python_version,  # type: ignore[arg-type]
        )


def test_wrong_input_report_type_is_refused() -> None:
    with pytest.raises(PaperAdmissionError):
        inspect_paper_admission(report="not a report")  # type: ignore[arg-type]


def test_assessment_does_not_import_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    from paper_data_suite import returned_paper_admission as admission

    original_import = builtins.__import__

    def blocked_handler_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith(("scoreform", "quillan", "pds_core.module_dispatch")):
            raise AssertionError("producer/Core handler import prohibited in 19A")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_handler_import)
    result = admission.inspect_paper_admission(
        report=_report(), platform_tag="linux", python_version=(3, 11)
    )
    assert result.exact_release_candidates == ("scoreform", "quillan")
    assert not result.qualified_modules
