"""#17 Slice 1: observational contract and synthetic PDS2 vectors only."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    ModuleRoutingPreview,
    PagePreview,
    SourcePreview,
)

VECTORS = Path(__file__).parent / "fixtures" / "issue17" / "preview_vectors_v1.json"


def test_fixture_is_purely_synthetic_and_covers_six_modules() -> None:
    value = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert value["schema_version"] == "1"
    assert value["fixtures_are_synthetic"] is True
    cases = value["decoded_qr_cases"]
    modules = {item.get("module_id") for item in cases}
    assert {
        "scoreform", "quillan", "concord", "vitrine", "portia", "unknown"
    } <= modules
    assert {"legacy_schema", "omr_schema", "duplicate_key", "unicode", "oversized"} <= {
        case["id"] for case in cases
    }


def test_single_observed_page_and_read_only_invariants() -> None:
    page = PagePreview(1, "candidate_unverified", "scoreform")
    source = SourcePreview(1, "observed", (page,), "a" * 64)
    rows = (ModuleRoutingPreview("scoreform", "declared_unvalidated"),)
    preview = IntakePreview((source,), rows)
    assert preview.contract_version == "1"
    assert preview.processing_performed is False
    assert preview.sources[0].pages[0].page_number == 1
    with pytest.raises(FrozenInstanceError):
        preview.processing_performed = True  # type: ignore[misc]
    with pytest.raises(ValueError, match="cannot claim processing"):
        replace(preview, processing_performed=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("number", [0, -1, 1.0, True])
def test_non_positive_or_non_integer_numbers_fail(number: object) -> None:
    with pytest.raises(ValueError):
        PagePreview(number, "missing_qr")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SourcePreview(number, "unsupported_format")  # type: ignore[arg-type]


def test_candidate_only_module_and_registration() -> None:
    with pytest.raises(ValueError, match="needs a safe Core module ID"):
        PagePreview(1, "candidate_unverified")
    with pytest.raises(ValueError, match="cannot claim a module"):
        PagePreview(1, "missing_qr", "scoreform")
    with pytest.raises(ValueError, match="only candidates"):
        PagePreview(1, "ambiguous_qr", registration_status="registration_not_found")
    assert PagePreview(1, "candidate_unverified", "portia", "registration_not_found")


def test_no_arbitrary_path_or_sensitive_diagnostic_in_contract() -> None:
    page = PagePreview(1, "candidate_unverified", "quillan")
    assert "C:\\private\\student" not in repr(page)
    with pytest.raises(ValueError):
        PagePreview(1, "candidate_unverified", "C:/private/student")
    with pytest.raises(ValueError):
        PagePreview(1, "candidate_unverified", "\x1b[32m")


def test_source_page_order_stable_and_unobserved_has_no_pages() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        SourcePreview(1, "observed", (PagePreview(2, "missing_qr"),))
    with pytest.raises(ValueError, match="cannot claim observed pages"):
        SourcePreview(1, "source_decode_failed", (PagePreview(1, "missing_qr"),))
    with pytest.raises(ValueError, match="must list physical pages"):
        SourcePreview(1, "observed")
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        SourcePreview(1, "unsupported_format", sha256_advisory="A" * 64)


def test_batch_sources_contiguous_and_no_duplicate_providers() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        IntakePreview((SourcePreview(3, "unsupported_format"),), ())
    with pytest.raises(ValueError, match="duplicate"):
        IntakePreview((), (ModuleRoutingPreview("quillan", "not_declared"),) * 2)
    with pytest.raises(ValueError, match="unqualified metadata"):
        ModuleRoutingPreview("meridian", "not_declared", "profile_valid")


def test_vector_statuses_are_valid_contract_values() -> None:
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    for source_index, case in enumerate(vectors["source_cases"], start=1):
        statuses = case["page_statuses"]
        module_ids = iter(case.get("module_ids", []))
        pages = tuple(
            PagePreview(
                index,
                status,
                next(module_ids) if status == "candidate_unverified" else None,
            )
            for index, status in enumerate(statuses, start=1)
        )
        # The synthetic matrix also tests a candidate count distinct from modules.
        assert all(page.page_number > 0 for page in pages)
        if status := case["source_status"]:
            SourcePreview(source_index, status, pages)  # type: ignore[arg-type]


def test_core_pds2_decoded_vector_contract_when_installed() -> None:
    # The real Core v0.6.3–v0.6.6 public parser is exercised on Windows/CI.
    from pds_core.pds2 import Pds2PayloadError, parse_pds2_payload

    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    for case in vectors["decoded_qr_cases"]:
        if case["expected"] == "candidate_unverified":
            locator = parse_pds2_payload(case["text"])
            assert locator.module_id == case["module_id"], case["id"]
        else:
            with pytest.raises((Pds2PayloadError, ValueError)):
                parse_pds2_payload(case["text"])
