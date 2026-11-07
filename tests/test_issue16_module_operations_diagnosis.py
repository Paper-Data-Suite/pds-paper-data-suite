"""Suite #16 Slice 2: opt-in Core profile diagnosis is not capability execution."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Iterable

import pytest

from paper_data_suite.applications import ApplicationLaunchStatus
from paper_data_suite.module_operations_diagnosis import (
    collect_module_operations_profile_diagnosis,
)
from paper_data_suite.module_operations_inventory import (
    ModuleOperationsMetadataInventory,
    collect_module_operations_metadata,
)


class Metadata(SimpleNamespace):
    def __init__(
        self,
        name: str = "scoreform",
        owner: str | None = "scoreform",
        *,
        kind: str = "module_operations",
        group: str = "paper_data_suite.module_operations",
    ) -> None:
        super().__init__(
            provider_kind=kind,
            entry_point_group=group,
            entry_point_name=name,
            entry_point_target=f"{name}.pds_operations:get_module_operations_profile",
            distribution_name=owner,
        )


def _census(*entries: Metadata) -> ModuleOperationsMetadataInventory:
    return collect_module_operations_metadata(inspect=lambda: entries)


def _result(
    name: str = "scoreform",
    owner: str | None = "scoreform",
    *,
    code: str = "provider.valid",
    readiness: object = lambda req: None,
    attention: object = lambda req: None,
) -> SimpleNamespace:
    stage = "valid" if code == "provider.valid" else "load"
    profile = SimpleNamespace(
        module_id=name,
        supported_core_operations_contract_versions=frozenset({"1"}),
        readiness_provider=readiness,
        attention_provider=attention,
    )
    return SimpleNamespace(
        metadata=Metadata(name, owner),
        code=code,
        stage=stage,
        declared_identity=name,
        registry_conflict=code == "provider.identity_conflict",
        profile_validation="passed" if code == "provider.valid" else "not_attempted",
        core_compatibility="passed" if code == "provider.valid" else "not_attempted",
        load_attempted=True,
        load_succeeded=True,
        provider_call_attempted=True,
        provider_call_succeeded=True,
        validated_profile=profile if code == "provider.valid" else None,
        message="hidden private student information must never be presented",
    )


def _diagnose(
    census: ModuleOperationsMetadataInventory,
    *results: object,
):
    return collect_module_operations_profile_diagnosis(
        metadata_inventory=census,
        diagnose=lambda: results,  # type: ignore[arg-type]
    )


def test_six_rows_in_registry_order_and_absent_remains_absent() -> None:
    result = _diagnose(_census())
    assert [x.component_id for x in result.applications] == [
        "scoreform", "quillan", "concord", "meridian", "vitrine", "portia"
    ]
    assert result.diagnosis_available
    assert all(x.profile_state == "not_declared" for x in result.applications)
    assert result.for_component("core") is None


def test_approved_valid_profile_only_declares_capabilities() -> None:
    result = _diagnose(_census(Metadata()), _result())
    row = result.for_component("scoreform")
    assert row is not None
    assert row.profile_state == "valid"
    assert row.readiness_declared is True and row.attention_declared is True
    assert not row.readiness_evaluated and not row.attention_evaluated
    assert not row.provenance_qualified
    assert "student" not in repr(result)
    assert "pds_operations" not in repr(result)


def test_missing_one_capability_is_not_a_provider_failure() -> None:
    row = _diagnose(
        _census(Metadata()), _result(attention=None)
    ).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "valid"
    assert row.readiness_declared is True
    assert row.attention_declared is False
    assert not row.attention_evaluated


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("provider.entry_point_name_invalid", "entry_point_name_invalid"),
        ("provider.load_failed", "load_failed"),
        ("provider.not_callable", "not_callable"),
        ("provider.call_failed", "call_failed"),
        ("provider.profile_invalid", "profile_invalid"),
        ("provider.identity_mismatch", "identity_mismatch"),
        ("provider.core_incompatible", "core_incompatible"),
        ("provider.identity_conflict", "identity_conflict"),
    ],
)
def test_core_error_codes_are_isolated_and_not_silenced(
    code: str, expected: str
) -> None:
    result = _diagnose(_census(Metadata()), _result(code=code))
    row = result.for_component("scoreform")
    assert row is not None
    assert row.profile_state == expected
    assert row.readiness_declared is None
    assert row.attention_declared is None
    peer = result.for_component("quillan")
    assert peer is not None and peer.profile_state == "not_declared"



def test_broken_neighbor_does_not_suppress_healthy_provider() -> None:
    census = _census(Metadata("scoreform", "scoreform"), Metadata("quillan", "quillan"))
    observed = _diagnose(
        census,
        _result("scoreform", "scoreform"),
        _result("quillan", "quillan", code="provider.load_failed"),
    )
    scoreform = observed.for_component("scoreform")
    quillan = observed.for_component("quillan")
    assert scoreform is not None and scoreform.profile_state == "valid"
    assert quillan is not None and quillan.profile_state == "load_failed"
    assert quillan.readiness_declared is None


def test_wrong_distribution_not_promoted_even_if_core_reports_valid() -> None:
    row = _diagnose(
        _census(Metadata()), _result(owner="rogue-wheel")
    ).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "owner_mismatch"
    assert row.readiness_declared is None


def test_metadata_owner_mismatch_is_not_overridden_by_valid_diagnosis() -> None:
    row = _diagnose(
        _census(Metadata(owner="foreign")), _result()
    ).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "metadata_unqualified"


def test_metadata_duplicate_is_not_promoted() -> None:
    row = _diagnose(
        _census(Metadata(), Metadata()), _result()
    ).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "metadata_unqualified"


def test_core_conflicting_duplicate_cannot_become_valid() -> None:
    row = _diagnose(
        _census(Metadata(), Metadata()), _result(code="provider.identity_conflict")
    ).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "identity_conflict"
    assert row.readiness_declared is None


def test_duplicate_diagnostic_rows_are_ambiguous() -> None:
    row = _diagnose(
        _census(Metadata()), _result(), _result()
    ).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "ambiguous"


def test_diagnosis_missing_is_not_same_as_no_metadata() -> None:
    row = _diagnose(_census(Metadata())).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "diagnosis_missing"


def test_unapproved_result_never_joins_approved_inventory() -> None:
    observed = _diagnose(
        _census(Metadata()),
        _result(),
        _result("surprise", "surprise"),
    )
    assert observed.unapproved_diagnostics == 1
    assert observed.for_component("surprise") is None


def test_bad_core_report_and_missing_identity_fail_closed() -> None:
    bad = _result()
    bad.code = "provider.future_unknown"
    row = _diagnose(_census(Metadata()), bad).for_component("scoreform")
    assert row is not None and row.profile_state == "invalid_diagnostic"
    bad = _result()
    bad.validated_profile.module_id = "portia"
    row = _diagnose(_census(Metadata()), bad).for_component("scoreform")
    assert row is not None and row.profile_state == "invalid_diagnostic"
    bad = _result()
    bad.stage = "metadata"
    row = _diagnose(_census(Metadata()), bad).for_component("scoreform")
    assert row is not None and row.profile_state == "invalid_diagnostic"


def test_metadata_group_or_kind_mismatch_is_refused() -> None:
    wrong = _result()
    wrong.metadata.entry_point_group = "other"
    row = _diagnose(_census(Metadata()), wrong).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "invalid_diagnostic"
    wrong = _result()
    wrong.metadata.provider_kind = "routing_module"
    row = _diagnose(_census(Metadata()), wrong).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "invalid_diagnostic"


def test_broken_diagnosis_does_not_expose_exception_or_erase_metadata() -> None:
    def broken() -> Iterable[object]:
        raise OSError("student name and private review: secret")

    census = _census(Metadata())
    observed = collect_module_operations_profile_diagnosis(
        metadata_inventory=census, diagnose=broken  # type: ignore[arg-type]
    )
    assert not observed.diagnosis_available
    row = observed.for_component("scoreform")
    assert row is not None
    assert row.metadata_state == "declared_unvalidated"
    assert row.profile_state == "diagnosis_unavailable"
    assert "secret" not in repr(observed)


def test_unbounded_diagnostics_fail_closed() -> None:
    observed = collect_module_operations_profile_diagnosis(
        metadata_inventory=_census(Metadata()),
        diagnose=lambda: [_result()] * 513,
    )
    assert not observed.diagnosis_available
    row = observed.for_component("scoreform")
    assert row is not None and row.profile_state == "diagnosis_unavailable"


def test_profiles_are_not_invoked_for_readiness_or_attention() -> None:
    calls: list[str] = []

    def forbidden(_: object) -> None:
        calls.append("capability invoked")
        raise AssertionError("never run")

    row = _diagnose(
        _census(Metadata()), _result(readiness=forbidden, attention=forbidden)
    ).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "valid"
    assert row.readiness_declared and row.attention_declared
    assert not calls


def test_profile_valid_cannot_authorize_a_launcher() -> None:
    census = _census(Metadata())
    applications = tuple(
        replace(row, launch_state=ApplicationLaunchStatus.INCOMPATIBLE)
        if row.component_id == "scoreform" else row
        for row in census.applications
    )
    census = replace(census, applications=applications)
    row = _diagnose(census, _result()).for_component("scoreform")
    assert row is not None
    assert row.profile_state == "valid"
    assert row.launch_state is ApplicationLaunchStatus.INCOMPATIBLE
    assert not row.provenance_qualified


def test_default_deep_path_requests_only_core_operations_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.module_operations_diagnosis as module

    calls: list[str] = []

    def diagnose(*, provider_kind: str) -> tuple[SimpleNamespace, ...]:
        calls.append(provider_kind)
        return (_result(),)

    def importer(name: str) -> object:
        calls.append(name)
        return SimpleNamespace(diagnose_core_providers=diagnose)

    monkeypatch.setattr(module, "import_module", importer)
    observed = collect_module_operations_profile_diagnosis(
        metadata_inventory=_census(Metadata())
    )
    row = observed.for_component("scoreform")
    assert row is not None and row.profile_state == "valid"
    assert calls == ["pds_core.provider_diagnostics", "module_operations"]


def test_unavailable_metadata_prevents_executable_diagnosis() -> None:
    def failed_metadata() -> Iterable[Metadata]:
        raise OSError("private traceback")

    census = collect_module_operations_metadata(inspect=failed_metadata)
    assert not census.inspection_available
    observed = collect_module_operations_profile_diagnosis(
        metadata_inventory=census,
        diagnose=lambda: pytest.fail("must not execute provider factories"),
    )
    assert not observed.diagnosis_available
    assert all(
        row.profile_state == "metadata_unqualified"
        for row in observed.applications
    )


def test_invalid_input_never_triggers_diagnosis() -> None:
    with pytest.raises(TypeError):
        collect_module_operations_profile_diagnosis(
            metadata_inventory=object(),  # type: ignore[arg-type]
            diagnose=lambda: pytest.fail("must not run"),
        )
