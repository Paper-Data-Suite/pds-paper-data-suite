"""Suite #20D: pure synthetic attention acceptance against installed wheels.

Executed only by an explicit, disposable wheel-installed acceptance runner.
Never discovers, imports, diagnoses or invokes actual producer modules.
"""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import sys
from pathlib import Path

from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleAttentionSummary,
    ModuleOperationsNotice,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    ModuleOwnerActionRef,
    invoke_module_attention,
)
from pds_core.routing_models import ModuleWorkRef

from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.module_attention_label_policy import GENERIC_ATTENTION_LABEL
from paper_data_suite.module_attention_projection import (
    AttentionProjection,
    project_module_attention,
)
from paper_data_suite.module_attention_rendering import (
    filter_attention_projection,
    format_attention_display,
)
from paper_data_suite.module_operations_diagnosis import (
    ModuleOperationsProfileInventory,
    ModuleOperationsProfileRow,
)
from paper_data_suite.module_operations_inventory import (
    ModuleOperationsMetadataInventory,
    ModuleOperationsMetadataRow,
)

_PRIVATE = "PRIVATE_STUDENT_AND_NOTES_DO_NOT_DISPLAY_20D"
_OWNERS = tuple(c for c in APPROVED_COMPONENTS if c.launchable)
_IDS = tuple(c.component_id for c in _OWNERS)
_MARKERS = (
    "SUITE20_D_CORE_V1_PARTIAL_COVERAGE_VERIFIED",
    "SUITE20_D_PRIVACY_COUNTS_AND_OVERFLOW_VERIFIED",
    "SUITE20_D_OWNER_AND_FAILURE_ISOLATION_VERIFIED",
    "SUITE20_D_ALL_EVALUATED_EMPTY_VERIFIED",
    "SUITE20_D_NO_IMPLICIT_PROVIDER_EVALUATION_VERIFIED",
    "SUITE20_D_SYNTHETIC_ONLY_PRODUCERS_NOT_QUALIFIED",
)


def assert_isolated_wheel_imports() -> None:
    """Refuse a checkout/source-shadowed smoke, including global interpreter."""
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("installed_environment_required")
    root = Path(sys.prefix).resolve(strict=True)
    for distribution, version, module_name in (
        ("paper-data-suite", "0.1.0", "paper_data_suite"),
        ("pds-core", "0.6.6", "pds_core"),
    ):
        if metadata.version(distribution) != version:
            raise RuntimeError("unexpected_installed_version")
        module = importlib.import_module(module_name)
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise RuntimeError("invalid_installed_import")
        if not Path(module_file).resolve(strict=True).is_relative_to(root):
            raise RuntimeError("source_checkout_import_refused")
    if any(name == "scoreform" or name == "quillan" for name in sys.modules):
        raise RuntimeError("producer_module_import_refused")


def _synthetic_metadata() -> ModuleOperationsMetadataInventory:
    return ModuleOperationsMetadataInventory(
        applications=tuple(
            ModuleOperationsMetadataRow(
                component_id=component.component_id,
                display_name=component.display_name,
                expected_distribution=component.distribution,
                launch_state=None,
                metadata_state="declared_unvalidated",
            )
            for component in _OWNERS
        ),
        unapproved_candidates=0,
        inspection_available=True,
    )


def _synthetic_profiles() -> ModuleOperationsProfileInventory:
    return ModuleOperationsProfileInventory(
        applications=tuple(
            ModuleOperationsProfileRow(
                component_id=component.component_id,
                display_name=component.display_name,
                expected_distribution=component.distribution,
                launch_state=None,
                metadata_state="declared_unvalidated",
                profile_state="valid",
                readiness_declared=True,
                attention_declared=True,
            )
            for component in _OWNERS
        ),
        unapproved_diagnostics=0,
        diagnosis_available=True,
    )


def _state(projection: AttentionProjection, owner: str) -> str:
    row = projection.for_module(owner)
    assert row is not None
    return row.state


def _invoke(owner: str, report: ModuleAttentionReport) -> object:
    return invoke_module_attention(
        ModuleOperationsProfile(
            module_id=owner,
            supported_core_operations_contract_versions=frozenset({"1"}),
            attention_provider=lambda request: report,
        ),
        ModuleOperationsRequest(class_id="class_a"),
    )


def run_synthetic_witnesses() -> tuple[str, ...]:
    """Execute only Core's neutral API with in-memory fictional callbacks."""
    assert len(_OWNERS) == 6 and len(set(_IDS)) == 6
    metadata_inventory = _synthetic_metadata()
    profiles = _synthetic_profiles()
    request = ModuleOperationsRequest(class_id="class_a")
    selected = (
        ModuleAttentionSummary(
            code="review", label=_PRIVATE, count=None, class_id="class_a",
            work_ref=ModuleWorkRef(
                module_id="scoreform", class_id="class_a", work_id="work_20d"
            ),
            action=ModuleOwnerActionRef(
                module_id="scoreform", action_id="open_work_20d"
            ),
        ),
        ModuleAttentionSummary(
            code="review", label=_PRIVATE, count=0, class_id="class_a"
        ),
        ModuleAttentionSummary(
            code="private_category_20d", label=_PRIVATE, count=9, class_id="class_a"
        ),
    )
    positive = _invoke(
        "scoreform",
        ModuleAttentionReport(
            evaluation="evaluated", summaries=selected,
            notices=(ModuleOperationsNotice(code="notice", summary=_PRIVATE),),
        ),
    )
    unavailable = _invoke(
        "quillan", ModuleAttentionReport(evaluation="unavailable")
    )

    def fail(_: ModuleOperationsRequest) -> ModuleAttentionReport:
        raise ValueError(_PRIVATE)

    failed = invoke_module_attention(
        ModuleOperationsProfile(
            module_id="concord",
            supported_core_operations_contract_versions=frozenset({"1"}),
            attention_provider=fail,
        ),
        request,
    )
    partial = project_module_attention(
        metadata_inventory=metadata_inventory,
        profile_inventory=profiles,
        request=request,
        invocation_results=(positive, unavailable, failed),
    )
    assert len(partial.modules) == 6
    assert partial.coverage == "partial" and partial.evaluated_modules == 1
    assert _state(partial, "scoreform") == "evaluated_items"
    assert _state(partial, "quillan") == "evaluation_unavailable"
    assert _state(partial, "concord") == "provider_failed"
    assert _state(partial, "meridian") == "not_evaluated"
    visible = filter_attention_projection(
        partial, module_id="scoreform", class_id="class_a",
        code="review", per_module_limit=1,
    )
    row = visible.rows[0]
    assert row.reported_items == 3 and row.matching_items == 2
    assert row.hidden_matching_items == 1
    assert row.items[0].owner_count is None
    assert row.items[0].category_label == GENERIC_ATTENTION_LABEL
    output = format_attention_display(visible)
    assert "Coverage: 1/6" in output
    assert "count not supplied" in output and "1 additional matching" in output
    assert "owner count: 9" not in output
    for private in (_PRIVATE, "class_a", "work_20d", "open_work_20d",
        "private_category_20d",
    ):
        assert private not in output and private not in repr(visible)
    unfiltered = format_attention_display(filter_attention_projection(partial))
    assert "owner count: 0" in unfiltered
    assert "owner count: 9" in unfiltered
    assert "Module attention item" in unfiltered
    assert _PRIVATE not in unfiltered and "open_work_20d" not in unfiltered

    foreign_action = ModuleAttentionReport(
        evaluation="evaluated",
        summaries=(ModuleAttentionSummary(
            code="review", label="Synthetic", class_id="class_a",
            action=ModuleOwnerActionRef(module_id="portia", action_id="foreign"),
        ),),
    )
    wrong = _invoke("scoreform", foreign_action)
    rejected = project_module_attention(
        metadata_inventory=metadata_inventory,
        profile_inventory=profiles,
        request=request,
        invocation_results=(wrong,),
    )
    assert _state(rejected, "scoreform") == "result_invalid"
    assert rejected.coverage == "none_evaluated"

    empty_results = tuple(
        _invoke(owner, ModuleAttentionReport(evaluation="evaluated"))
        for owner in _IDS
    )
    complete = project_module_attention(
        metadata_inventory=metadata_inventory,
        profile_inventory=profiles,
        request=request,
        invocation_results=empty_results,
    )
    assert complete.coverage == "complete" and complete.evaluated_modules == 6
    assert all(row.state == "evaluated_empty" for row in complete.modules)
    assert "All clear" not in format_attention_display(
        filter_attention_projection(complete)
    )
    unknown = project_module_attention(
        metadata_inventory=metadata_inventory,
        profile_inventory=None,
        request=request,
    )
    assert unknown.coverage == "none_evaluated"
    assert all(row.state == "profile_not_checked" for row in unknown.modules)
    assert "no items reported" not in format_attention_display(
        filter_attention_projection(unknown)
    )
    assert "scoreform" not in sys.modules
    assert "quillan" not in sys.modules
    return _MARKERS


def main() -> int:
    assert_isolated_wheel_imports()
    print("SUITE20_D_INSTALLED_CORE_AND_SUITE_WHEELS_VERIFIED")
    for marker in run_synthetic_witnesses():
        print(marker)
    print("SUITE20_D_INSTALLED_PURE_ATTENTION_ACCEPTANCE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
