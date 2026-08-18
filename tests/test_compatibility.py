from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from paper_data_suite import __version__
from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    load_release_compatibility_manifest,
    parse_release_compatibility_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT / "paper_data_suite" / "data" / "release_compatibility_v1.json"
)
EXPECTED_COMPONENT_IDS = (
    "concord",
    "core",
    "quillan",
    "scoreform",
    "vitrine",
)


def _raw_manifest() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
    )


def _parse(data: dict[str, Any]) -> object:
    return parse_release_compatibility_manifest(json.dumps(data))


def _component(data: dict[str, Any], component_id: str) -> dict[str, Any]:
    return next(
        item for item in data["components"] if item["component_id"] == component_id
    )


def test_bundled_manifest_loads_and_matches_package_version() -> None:
    manifest = load_release_compatibility_manifest()

    assert manifest.record_type == (
        "paper_data_suite_release_compatibility_manifest"
    )
    assert manifest.contract_version == "1"
    assert manifest.suite.distribution == "paper-data-suite"
    assert manifest.suite.version == __version__ == "0.1.0.dev0"
    assert manifest.suite.release_status == "development"
    assert manifest.python.specifier == ">=3.11,<3.15"
    assert manifest.python.tested_minors == (
        "3.11",
        "3.12",
        "3.13",
        "3.14",
    )


def test_manifest_qualifies_exact_audited_published_releases() -> None:
    manifest = load_release_compatibility_manifest()
    by_id = {item.component_id: item for item in manifest.components}

    assert tuple(by_id) == EXPECTED_COMPONENT_IDS
    assert by_id["core"].release.sha256 == (
        "be28c061b38463ef59ebc328ed1aa443"
        "767fe7f2c626babb769c2d8e5932f308"
    )
    assert by_id["scoreform"].release.sha256 == (
        "04c79c9b884040e3fc32b2551a4ad4fa"
        "6c63d4d04f1094b648e223bbb3c076d0"
    )
    assert by_id["quillan"].release.sha256 == (
        "4e3bf92287d1a140a6edc062abcb759c"
        "02eb811c9ba4e2212e9c4878d3a07f1c"
    )
    assert by_id["concord"].release.sha256 == (
        "e7f0171e8fd54eaa6ab0fd71580378bd"
        "d5ee8577a686890cd470dac83f7a619e"
    )
    assert by_id["vitrine"].release.sha256 == (
        "a2c50b997abab7e4b32c2a8bc434990e"
        "f3b8229288db94b1c2677d1ee964a61b"
    )


def test_only_core_is_required() -> None:
    manifest = load_release_compatibility_manifest()

    required = tuple(
        item.component_id for item in manifest.components if item.required
    )
    assert required == ("core",)


def test_public_capabilities_remain_independent() -> None:
    manifest = load_release_compatibility_manifest()
    by_id = {item.component_id: item for item in manifest.components}

    producer_routing = (
        "launchable_application",
        "publication_producer",
        "routing_module",
    )
    assert by_id["scoreform"].capabilities == producer_routing
    assert by_id["quillan"].capabilities == producer_routing
    assert by_id["concord"].capabilities == producer_routing
    assert by_id["vitrine"].capabilities == ("launchable_application",)
    assert by_id["core"].capabilities == ("shared_core",)


def test_poppler_is_declared_only_for_audited_pdf_scan_components() -> None:
    manifest = load_release_compatibility_manifest()
    by_id = {item.component_id: item for item in manifest.components}

    for component_id in ("scoreform", "quillan"):
        prerequisites = by_id[component_id].external_prerequisites
        assert len(prerequisites) == 1
        prerequisite = prerequisites[0]
        assert prerequisite.prerequisite_id == "poppler_pdftoppm"
        assert prerequisite.kind == "command"
        assert prerequisite.required is True
        assert prerequisite.commands == ("pdftoppm",)
        assert prerequisite.platforms == ("linux", "windows")
        assert prerequisite.purpose == "PDF scan rasterization"

    assert by_id["core"].external_prerequisites == ()
    assert by_id["concord"].external_prerequisites == ()
    assert by_id["vitrine"].external_prerequisites == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("record_type", "wrong"),
        ("contract_version", "2"),
    ],
)
def test_wrong_top_level_contract_identity_fails(
    field: str,
    value: str,
) -> None:
    data = _raw_manifest()
    data[field] = value

    with pytest.raises(CompatibilityManifestError):
        _parse(data)


def test_unknown_top_level_field_fails() -> None:
    data = _raw_manifest()
    data["typo"] = "value"

    with pytest.raises(
        CompatibilityManifestError,
        match="unknown fields",
    ):
        _parse(data)


def test_duplicate_json_object_key_fails() -> None:
    text = (
        '{"record_type":"paper_data_suite_release_compatibility_manifest",'
        '"record_type":"paper_data_suite_release_compatibility_manifest"}'
    )

    with pytest.raises(
        CompatibilityManifestError,
        match="duplicate JSON object key",
    ):
        parse_release_compatibility_manifest(text)


def test_suite_version_mismatch_fails() -> None:
    data = _raw_manifest()
    data["suite"]["version"] = "0.1.0"

    with pytest.raises(
        CompatibilityManifestError,
        match="suite.version",
    ):
        _parse(data)


@pytest.mark.parametrize(
    "tested_minors",
    [
        ["3.11", "3.11"],
        ["3.12", "3.11"],
        ["3.11", "3.15"],
    ],
)
def test_invalid_tested_python_minor_sets_fail(
    tested_minors: list[str],
) -> None:
    data = _raw_manifest()
    data["python"]["tested_minors"] = tested_minors

    with pytest.raises(CompatibilityManifestError):
        _parse(data)


def test_malformed_python_specifier_fails() -> None:
    data = _raw_manifest()
    data["python"]["specifier"] = "Python >= 3.11"

    with pytest.raises(
        CompatibilityManifestError,
        match="specifier",
    ):
        _parse(data)


def test_unknown_component_id_fails() -> None:
    data = _raw_manifest()
    data["components"][0]["component_id"] = "unknown_component"

    with pytest.raises(
        CompatibilityManifestError,
        match="unsupported PDS component_id",
    ):
        _parse(data)


def test_duplicate_component_id_fails() -> None:
    data = _raw_manifest()
    data["components"].append(copy.deepcopy(data["components"][0]))

    with pytest.raises(
        CompatibilityManifestError,
        match="duplicate component_id",
    ):
        _parse(data)


def test_duplicate_distribution_fails() -> None:
    data = _raw_manifest()
    concord = _component(data, "concord")
    scoreform = _component(data, "scoreform")
    scoreform["distribution"] = concord["distribution"]
    scoreform["release"]["wheel"] = "pds_concord-0.10.0-py3-none-any.whl"

    with pytest.raises(
        CompatibilityManifestError,
        match="duplicate component distribution",
    ):
        _parse(data)


def test_components_must_be_sorted() -> None:
    data = _raw_manifest()
    data["components"][0], data["components"][1] = (
        data["components"][1],
        data["components"][0],
    )

    with pytest.raises(
        CompatibilityManifestError,
        match="sorted by component_id",
    ):
        _parse(data)


@pytest.mark.parametrize(
    "digest",
    [
        "a" * 63,
        "A" * 64,
        "g" * 64,
    ],
)
def test_malformed_digest_fails(digest: str) -> None:
    data = _raw_manifest()
    _component(data, "core")["release"]["sha256"] = digest

    with pytest.raises(
        CompatibilityManifestError,
        match="sha256",
    ):
        _parse(data)


def test_supported_component_cannot_use_dev_version() -> None:
    data = _raw_manifest()
    component = _component(data, "core")
    component["version"] = "0.6.1.dev0"
    component["release"]["tag"] = "v0.6.1.dev0"
    component["release"]["wheel"] = "pds_core-0.6.1.dev0-py3-none-any.whl"

    with pytest.raises(
        CompatibilityManifestError,
        match="development version",
    ):
        _parse(data)


def test_sibling_component_cannot_be_required() -> None:
    data = _raw_manifest()
    _component(data, "scoreform")["required"] = True

    with pytest.raises(
        CompatibilityManifestError,
        match="cannot be required",
    ):
        _parse(data)


def test_suite_distribution_cannot_be_component_row() -> None:
    data = _raw_manifest()
    component = _component(data, "scoreform")
    component["distribution"] = "paper-data-suite"
    component["release"]["wheel"] = (
        "paper_data_suite-0.10.0-py3-none-any.whl"
    )

    with pytest.raises(
        CompatibilityManifestError,
        match="subordinate component row",
    ):
        _parse(data)


def test_routing_capability_must_match_routing_entry_point() -> None:
    data = _raw_manifest()
    component = _component(data, "scoreform")
    component["entry_points"]["paper_data_suite.modules"] = {}

    with pytest.raises(
        CompatibilityManifestError,
        match="routing capability",
    ):
        _parse(data)


def test_publication_capability_must_match_producer_entry_point() -> None:
    data = _raw_manifest()
    component = _component(data, "quillan")
    component["entry_points"]["paper_data_suite.publication_producers"] = {}

    with pytest.raises(
        CompatibilityManifestError,
        match="producer capability",
    ):
        _parse(data)


def test_launchable_application_requires_console_script() -> None:
    data = _raw_manifest()
    component = _component(data, "vitrine")
    component["entry_points"]["console_scripts"] = {}

    with pytest.raises(
        CompatibilityManifestError,
        match="must expose a console script",
    ):
        _parse(data)


def test_prerequisite_command_must_be_bare_executable_name() -> None:
    data = _raw_manifest()
    prerequisite = _component(data, "scoreform")["external_prerequisites"][0]
    prerequisite["commands"] = ["C:\\Program Files\\poppler\\pdftoppm.exe"]

    with pytest.raises(
        CompatibilityManifestError,
        match="bare executable",
    ):
        _parse(data)


def test_prerequisite_platforms_must_be_sorted() -> None:
    data = _raw_manifest()
    prerequisite = _component(data, "scoreform")["external_prerequisites"][0]
    prerequisite["platforms"] = ["windows", "linux"]

    with pytest.raises(
        CompatibilityManifestError,
        match="platforms must be sorted",
    ):
        _parse(data)


def test_manifest_models_are_immutable() -> None:
    manifest = load_release_compatibility_manifest()

    with pytest.raises(AttributeError):
        manifest.suite.version = "0.1.0"  # type: ignore[misc]
