"""Slice 6B2 pure route-order and approval-invariant regression tests.

Native PDFium/ZXing and actual producer acceptance run in the separate
SHA-verified published-wheel environment; these tests do not fake that gate.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from paper_data_suite.returned_paper_preview_contract import (
    PagePreview,
    SourcePreview,
)


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    import sys

    path = (
        Path(__file__).resolve().parent.parent
        / "scripts/issue18_native_mixed_pdf_rehearsal.py"
    )
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("issue18_native_probe", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def _observations(
    a: str = "scoreform", b: str = "quillan"
) -> tuple[SourcePreview, ...]:
    return (SourcePreview(
        1, "observed", (
            PagePreview(1, "candidate_unverified", a),
            PagePreview(2, "candidate_unverified", b),
        ), "a" * 64,
    ),)


def test_exact_two_native_pages_are_distinct_and_ordered(
    probe: ModuleType,
) -> None:
    assert probe._exact_preview(_observations())


@pytest.mark.parametrize(
    "observations",
    [
        (),
        ("not-an-observation",),
        (SourcePreview(1, "source_decode_failed"),),
        (SourcePreview(1, "observed", (
            PagePreview(1, "candidate_unverified", "scoreform"),
        ), "b" * 64),),
        (SourcePreview(1, "observed", (
            PagePreview(1, "candidate_unverified", "quillan"),
            PagePreview(2, "candidate_unverified", "scoreform"),
        ), "c" * 64),),
        (SourcePreview(1, "observed", (
            PagePreview(1, "candidate_unverified", "scoreform"),
            PagePreview(2, "missing_qr"),
        ), "d" * 64),),
        (SourcePreview(1, "observed", (
            PagePreview(1, "candidate_unverified", "scoreform"),
            PagePreview(2, "candidate_unverified", "scoreform"),
        ), "e" * 64),),
        (SourcePreview(1, "observed", (
            PagePreview(1, "candidate_unverified", "scoreform"),
            PagePreview(2, "candidate_unverified", "quillan"),
        ), "f" * 64), SourcePreview(2, "source_unavailable")),
    ],
)
def test_unexpected_native_observations_are_refused(
    probe: ModuleType, observations: object
) -> None:
    assert not probe._exact_preview(observations)


def test_retention_cancel_is_bound_to_current_challenge(
    probe: ModuleType,
) -> None:
    review = SimpleNamespace(plan_digest="digest", challenge="challenge")
    decision = probe._cancel_retention(review)
    assert decision.decision == "cancel"
    assert decision.plan_digest == "digest"
    assert decision.challenge == "challenge"


def test_dispatch_approval_requires_explicit_write_disclosure(
    probe: ModuleType,
) -> None:
    good = SimpleNamespace(
        plan_digest="digest", challenge="challenge",
        producer_handlers_may_write=True,
    )
    approved = probe._authorize_dispatch(good)
    assert approved.decision == "approve"
    assert approved.plan_digest == "digest"
    with pytest.raises(ValueError):
        probe._authorize_dispatch(SimpleNamespace(
            producer_handlers_may_write=False,
        ))


def test_dispatch_cancel_never_claims_approval(probe: ModuleType) -> None:
    review = SimpleNamespace(plan_digest="digest", challenge="challenge")
    decision = probe._cancel_dispatch(review)
    assert decision.decision == "cancel"
    assert decision.challenge == "challenge"
