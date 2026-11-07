"""Core v1 invocation outcomes are separate from Suite #16 profile diagnosis.

Pure, fictional fixtures. No producer imports, persistence, or workspace reads.
"""

from __future__ import annotations

import pytest
from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleAttentionSummary,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    ModuleOwnerActionRef,
    ModuleReadinessReport,
    invoke_module_attention,
    invoke_module_readiness,
)


def _profile(*, readiness=None, attention=None) -> ModuleOperationsProfile:
    return ModuleOperationsProfile(
        module_id="scoreform",
        supported_core_operations_contract_versions=frozenset({"1"}),
        readiness_provider=readiness,
        attention_provider=attention,
    )


@pytest.mark.parametrize("ready", [True, False])
def test_evaluated_ready_state_is_not_provider_error(ready: bool) -> None:
    def inspect(request: ModuleOperationsRequest) -> ModuleReadinessReport:
        return ModuleReadinessReport(evaluation="evaluated", ready=ready)

    result = invoke_module_readiness(
        _profile(readiness=inspect), ModuleOperationsRequest()
    )
    assert result.code == "module_operations.evaluated"
    assert result.report is not None and result.report.ready is ready


def test_unavailable_is_not_not_ready() -> None:
    result = invoke_module_readiness(
        _profile(
            readiness=lambda r: ModuleReadinessReport(
                evaluation="unavailable", ready=None
            )
        ),
        ModuleOperationsRequest(),
    )
    assert result.code == "module_operations.evaluation_unavailable"
    assert result.report is not None and result.report.ready is None


def test_empty_evaluated_attention_differs_from_unknown() -> None:
    good = invoke_module_attention(
        _profile(attention=lambda r: ModuleAttentionReport(evaluation="evaluated")),
        ModuleOperationsRequest(),
    )
    unknown = invoke_module_attention(
        _profile(attention=lambda r: ModuleAttentionReport(evaluation="unavailable")),
        ModuleOperationsRequest(),
    )
    assert good.code == "module_operations.evaluated"
    assert good.report is not None and good.report.summaries == ()
    assert unknown.code == "module_operations.evaluation_unavailable"
    assert unknown.report is not None and unknown.report.summaries == ()


def test_absent_capability_does_not_call_sibling() -> None:
    called = []
    result = invoke_module_attention(
        _profile(readiness=lambda r: called.append("readiness")),
        ModuleOperationsRequest(),
    )
    assert result.code == "module_operations.capability_absent"
    assert called == []


def test_failed_callback_does_not_become_zero_attention() -> None:
    def crash(request: ModuleOperationsRequest) -> ModuleAttentionReport:
        raise RuntimeError("private fictional student record must not escape")

    result = invoke_module_attention(
        _profile(attention=crash), ModuleOperationsRequest()
    )
    assert result.code == "module_operations.provider_failed"
    assert result.report is None
    assert "student" not in repr(result)


def test_invalid_callback_output_is_rejected() -> None:
    result = invoke_module_attention(
        _profile(attention=lambda r: object()), ModuleOperationsRequest(),
    )
    assert result.code == "module_operations.result_invalid"
    assert result.report is None


def test_foreign_owner_action_ref_is_inert_and_refused() -> None:
    def foreign(request: ModuleOperationsRequest) -> ModuleAttentionReport:
        return ModuleAttentionReport(
            evaluation="evaluated",
            summaries=(ModuleAttentionSummary(
                code="review", label="Synthetic review",
                action=ModuleOwnerActionRef(module_id="portia", action_id="open"),
            ),),
        )

    result = invoke_module_attention(
        _profile(attention=foreign), ModuleOperationsRequest()
    )
    assert result.code == "module_operations.result_invalid"
    assert result.report is None


def test_wrong_class_context_is_refused() -> None:
    def wrong_class(request: ModuleOperationsRequest) -> ModuleAttentionReport:
        return ModuleAttentionReport(
            evaluation="evaluated",
            summaries=(ModuleAttentionSummary(
                code="review", label="Synthetic review", class_id="class_b",
            ),),
        )

    result = invoke_module_attention(
        _profile(attention=wrong_class),
        ModuleOperationsRequest(class_id="class_a"),
    )
    assert result.code == "module_operations.result_invalid"
