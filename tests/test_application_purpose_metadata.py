from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    load_release_compatibility_manifest,
    parse_release_compatibility_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT / "paper_data_suite" / "data" / "release_compatibility_v1.json"
)

EXPECTED_PURPOSES = {
    "concord": "Paper-first collaborative classroom evidence and group-work workflows.",
    "quillan": "Standards-based writing evidence capture and review.",
    "scoreform": "Printable answer-sheet generation and OMR scoring.",
    "vitrine": "Portfolio curation and immutable snapshot workflows.",
}


def _raw_manifest() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
    )


def _component(data: dict[str, Any], component_id: str) -> dict[str, Any]:
    return next(
        item for item in data["components"] if item["component_id"] == component_id
    )


def _parse(data: dict[str, Any]) -> object:
    return parse_release_compatibility_manifest(json.dumps(data))


def test_launchable_components_have_bounded_teacher_purposes() -> None:
    manifest = load_release_compatibility_manifest()
    by_id = {component.component_id: component for component in manifest.components}

    assert by_id["core"].purpose is None
    assert {
        component_id: by_id[component_id].purpose
        for component_id in EXPECTED_PURPOSES
    } == EXPECTED_PURPOSES


def test_launchable_component_requires_purpose_field() -> None:
    data = _raw_manifest()
    del _component(data, "scoreform")["purpose"]

    with pytest.raises(CompatibilityManifestError, match="missing fields: purpose"):
        _parse(data)


def test_launchable_component_requires_non_null_purpose() -> None:
    data = _raw_manifest()
    _component(data, "scoreform")["purpose"] = None

    with pytest.raises(CompatibilityManifestError, match="must declare purpose"):
        _parse(data)


@pytest.mark.parametrize(
    "purpose",
    [
        "",
        " leading whitespace",
        "trailing whitespace ",
        "two\nlines",
        "a" * 161,
    ],
)
def test_launchable_component_rejects_invalid_purpose(purpose: str) -> None:
    data = _raw_manifest()
    _component(data, "scoreform")["purpose"] = purpose

    with pytest.raises(CompatibilityManifestError, match="purpose"):
        _parse(data)


def test_non_launchable_component_purpose_must_be_null() -> None:
    data = _raw_manifest()
    _component(data, "core")["purpose"] = "Shared infrastructure"

    with pytest.raises(CompatibilityManifestError, match="purpose must be null"):
        _parse(data)


def test_launchable_component_requires_exactly_one_console_script() -> None:
    data = _raw_manifest()
    component = _component(data, "vitrine")
    component["entry_points"]["console_scripts"]["vitrine-alt"] = (
        "vitrine.cli:main"
    )

    with pytest.raises(CompatibilityManifestError, match="exactly one console"):
        _parse(data)
