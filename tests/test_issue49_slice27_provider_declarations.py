"""Issue #49 Slice 27: signed provider entry-point declarations, not readiness."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice24_publisher_pip_preflight as publisher_fixture
from test_issue49_slice3_signature_verification import NOW, _ring

from paper_data_suite.evergreen_provider_declarations import (
    DeclarationStatus,
    ProviderDeclarationError,
    _declaration,
    inspect_authenticated_provider_declaration,
)

_GROUP = "paper_data_suite.module_operations"
_MEMBERS = frozenset({"demo_app/pds_operations.py", "demo_app/__init__.py"})


def _metadata(provider: str = "demo = demo_app.pds_operations:get_profile") -> bytes:
    return (
        f"[console_scripts]\ndemo = demo_app.cli:main\n\n[{_GROUP}]\n{provider}\n"
    ).encode()


@pytest.mark.parametrize(
    "group",
    [
        "paper_data_suite.modules",
        "paper_data_suite.module_operations",
        "paper_data_suite.publication_producers",
    ],
)
def test_known_core_discovery_groups_are_metadata_only(group: str) -> None:
    raw = f"[{group}]\ndemo = demo_app.pds_operations:get_profile\n".encode()
    status, target = _declaration(
        raw, component_id="demo", group=group, wheel_members=_MEMBERS
    )
    assert status is DeclarationStatus.DECLARED_NOT_TESTED
    assert target == "demo_app.pds_operations:get_profile"


def test_absent_public_contract_does_not_block_other_provider() -> None:
    state, target = _declaration(
        b"[console_scripts]\ndemo = demo_app.cli:main\n",
        component_id="demo",
        group=_GROUP,
        wheel_members=_MEMBERS,
    )
    assert state is DeclarationStatus.NOT_DECLARED
    assert target is None


@pytest.mark.parametrize(
    "provider",
    [
        "foreign = demo_app.pds_operations:get_profile",
        "demo = os:system",
        "demo = demo_app.pds_operations:get_profile [extra]",
        "demo = demo_app.pds_operations:get_profile; injected",
        "demo = ../other:run",
        "demo = demo_app.pds_operations:get_profile\n"
        "demo = demo_app.pds_operations:get_profile",
        "demo = demo_app.pds_operations:get_profile\n"
        "foreign = demo_app.pds_operations:get_profile",
    ],
)
def test_unowned_or_ambiguous_declaration_is_rejected(provider: str) -> None:
    with pytest.raises(ProviderDeclarationError):
        _declaration(
            _metadata(provider),
            component_id="demo",
            group=_GROUP,
            wheel_members=_MEMBERS,
        )


def test_unowned_target_source_fails_closed() -> None:
    with pytest.raises(ProviderDeclarationError, match="absent"):
        _declaration(
            _metadata(),
            component_id="demo",
            group=_GROUP,
            wheel_members=frozenset({"demo_app/__init__.py"}),
        )


def test_empty_or_oversized_entrypoint_text_is_rejected() -> None:
    for raw in (b"", b"X" * (32 * 1024 + 1)):
        with pytest.raises(ProviderDeclarationError, match="length"):
            _declaration(raw, component_id="demo", group=_GROUP, wheel_members=_MEMBERS)


def test_invalid_utf8_and_defaults_fail_closed() -> None:
    for raw in (b"\xff\xfe", b"[DEFAULT]\ndemo = unsafe\n" + _metadata()):
        with pytest.raises(ProviderDeclarationError):
            _declaration(raw, component_id="demo", group=_GROUP, wheel_members=_MEMBERS)


def test_provider_metadata_itself_never_executes() -> None:
    with patch("subprocess.run", side_effect=AssertionError("no subprocess")):
        assert (
            _declaration(
                _metadata(),
                component_id="demo",
                group=_GROUP,
                wheel_members=_MEMBERS,
            )[0]
            is DeclarationStatus.DECLARED_NOT_TESTED
        )


@pytest.fixture(scope="module")
def signed_stage(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, bytes, bytes, bytes, bytes]:
    patcher = pytest.MonkeyPatch()
    try:
        stage = publisher_fixture._signed_stage(
            tmp_path_factory.mktemp("signed-provider-stage"), patcher
        )
    finally:
        patcher.undo()
    return stage


def _inspect(
    signed_stage: tuple[Path, Path, bytes, bytes, bytes, bytes],
    **overrides: Any,
):
    stage, wheels, registry, lock, prepared, module = signed_stage
    options: dict[str, Any] = {
        "stage_root": stage,
        "wheelhouse": wheels,
        "prepared_record": prepared,
        "registry_envelope": registry,
        "lock_envelope": lock,
        "module_envelopes": {"demo": module},
        "component_id": "demo",
        "group": _GROUP,
        "trust": _ring(),
        "now": NOW,
    }
    options.update(overrides)
    return inspect_authenticated_provider_declaration(**options)


def test_signed_real_pip_stage_correctly_reports_undeclared_provider(
    signed_stage: tuple[Path, Path, bytes, bytes, bytes, bytes],
) -> None:
    with patch("subprocess.run", side_effect=AssertionError("no subprocess")):
        result = _inspect(signed_stage)
    assert result.status is DeclarationStatus.NOT_DECLARED
    assert result.target is None
    assert result.transaction_id == "e" * 32
    assert len(result.wheel_sha256) == 64
    assert len(result.pip_inventory_sha256) == 64
    assert len(result.publisher_payload_sha256) == 64
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "provider_ready")


def test_unknown_group_and_component_do_not_gain_authority(
    signed_stage: tuple[Path, Path, bytes, bytes, bytes, bytes],
) -> None:
    for changes in (
        {"group": "other.plugins"},
        {"component_id": "unknown"},
        {"component_id": "../demo"},
    ):
        with pytest.raises(ProviderDeclarationError):
            _inspect(signed_stage, **changes)


def test_publisher_evidence_remains_mandatory(
    signed_stage: tuple[Path, Path, bytes, bytes, bytes, bytes],
) -> None:
    with pytest.raises(ProviderDeclarationError, match="audit failed"):
        _inspect(signed_stage, module_envelopes={"demo": b"unsigned"})


def test_installed_metadata_tamper_cannot_be_promoted_to_public_provider(
    signed_stage: tuple[Path, Path, bytes, bytes, bytes, bytes],
) -> None:
    stage = signed_stage[0]
    import os
    import sys

    site = stage / (
        "Lib/site-packages"
        if os.name == "nt"
        else f"lib/python{sys.version_info.major}."
        f"{sys.version_info.minor}/site-packages"
    )
    entry = site / "demo_app-1.0.0.dist-info/entry_points.txt"
    old = entry.read_bytes()
    try:
        entry.write_bytes(old + b"\n" + _metadata())
        with pytest.raises(ProviderDeclarationError, match="audit failed"):
            _inspect(signed_stage)
    finally:
        entry.write_bytes(old)
