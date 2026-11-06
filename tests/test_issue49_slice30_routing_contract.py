"""Issue #49 Slice 30: explicit Core routing PDS2 profile validation, no actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from test_issue49_slice3_signature_verification import (
    NOW,
    _registry,
    _ring,
    _signed,
)

from paper_data_suite.evergreen_candidate_acceptance import CandidateAcceptanceError
from paper_data_suite.evergreen_provider_import_probe import (
    ObservedProviderImport,
    ProviderImportError,
    ProviderImportStatus,
)
from paper_data_suite.evergreen_routing_contract_probe import (
    _CONTRACT_SCRIPT,
    RoutingContractError,
    RoutingContractStatus,
    probe_signed_routing_contract,
)


@pytest.fixture
def scene(tmp_path: Path) -> tuple[dict[str, Any], ObservedProviderImport]:
    software = tmp_path / "managed-software"
    software.mkdir()
    stage = software / "stage"
    wheels = software / "wheels"
    stage.mkdir()
    wheels.mkdir()
    workspace = tmp_path / "classroom"
    workspace.mkdir()
    inputs: dict[str, Any] = {
        "stage_root": stage,
        "wheelhouse": wheels,
        "classroom_workspace": workspace,
        "prepared_record": b"prepared",
        "registry_envelope": _signed(_registry(), "root-primary"),
        "lock_envelope": b"lock",
        "evidence_envelope": b"evidence",
        "module_envelopes": {"quillan": b"module"},
        "component_id": "quillan",
        "trust": _ring(),
        "now": NOW,
        "allow_candidate_execution": True,
    }
    observed = ObservedProviderImport(
        "a" * 32,
        "quillan",
        "paper_data_suite.modules",
        ProviderImportStatus.IMPORTABLE_NOT_CONTRACT_TESTED,
        "quillan.pds_module:get_module_profile",
        "b" * 64,
        "c" * 64,
        "d" * 64,
    )
    return inputs, observed


def test_validated_profile_is_not_routing_dispatch(
    scene: tuple[dict[str, Any], ObservedProviderImport],
) -> None:
    inputs, observed = scene
    with (
        patch(
            "paper_data_suite.evergreen_routing_contract_probe."
            "probe_signed_provider_import",
            return_value=observed,
        ) as preflight,
        patch(
            "paper_data_suite.evergreen_routing_contract_probe._run_check"
        ) as execute,
    ):
        result = probe_signed_routing_contract(**inputs)
    assert preflight.call_count == 2
    assert execute.call_count == 1
    args = execute.call_args.args[1]
    assert args[:3] == ("-I", "-B", "-c")
    assert args[4:] == (
        "quillan",
        "quillan",
        "quillan.pds_module:get_module_profile",
    )
    assert "validate_module_profile(factory())" in _CONTRACT_SCRIPT
    assert "route_handler(" not in _CONTRACT_SCRIPT
    assert "registration_validator(" not in _CONTRACT_SCRIPT
    assert result.status is RoutingContractStatus.PDS2_PROFILE_VALID_NOT_DISPATCHED
    assert result.provider_target == observed.target
    assert result.pip_inventory_sha256 == observed.pip_inventory_sha256
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "ready")


def test_missing_optional_routing_profile_never_executes(
    scene: tuple[dict[str, Any], ObservedProviderImport],
) -> None:
    inputs, observed = scene
    absent = ObservedProviderImport(
        observed.transaction_id,
        observed.component_id,
        observed.group,
        ProviderImportStatus.NOT_DECLARED,
        None,
        observed.pip_inventory_sha256,
        observed.native_payload_sha256,
        observed.provider_declaration_sha256,
    )
    with (
        patch(
            "paper_data_suite.evergreen_routing_contract_probe."
            "probe_signed_provider_import",
            return_value=absent,
        ) as preflight,
        patch(
            "paper_data_suite.evergreen_routing_contract_probe._run_check",
            side_effect=AssertionError("no subprocess allowed"),
        ),
    ):
        result = probe_signed_routing_contract(**inputs)
    assert preflight.call_count == 1
    assert result.status is RoutingContractStatus.NOT_DECLARED
    assert result.provider_target is None


@pytest.mark.parametrize("bad", [False, None, 0, "True"])
def test_requires_explicit_approval(
    scene: tuple[dict[str, Any], ObservedProviderImport],
    bad: Any,
) -> None:
    inputs, _ = scene
    inputs["allow_candidate_execution"] = bad
    with patch(
        "paper_data_suite.evergreen_routing_contract_probe."
        "probe_signed_provider_import",
        side_effect=AssertionError("no probe"),
    ):
        with pytest.raises(RoutingContractError, match="explicit"):
            probe_signed_routing_contract(**inputs)


@pytest.mark.parametrize("timeout", [-1, 0, 61, True, 1.5])
def test_rejects_unbounded_timeout_before_probe(
    scene: tuple[dict[str, Any], ObservedProviderImport],
    timeout: Any,
) -> None:
    inputs, _ = scene
    inputs["timeout_seconds"] = timeout
    with patch(
        "paper_data_suite.evergreen_routing_contract_probe."
        "probe_signed_provider_import",
        side_effect=AssertionError("no probe"),
    ):
        with pytest.raises(RoutingContractError, match="explicit"):
            probe_signed_routing_contract(**inputs)


def test_failed_factory_never_claims_supported_routing_contract(
    scene: tuple[dict[str, Any], ObservedProviderImport],
) -> None:
    inputs, observed = scene
    with (
        patch(
            "paper_data_suite.evergreen_routing_contract_probe."
            "probe_signed_provider_import",
            return_value=observed,
        ) as preflight,
        patch(
            "paper_data_suite.evergreen_routing_contract_probe._run_check",
            side_effect=CandidateAcceptanceError("private provider failure"),
        ),
    ):
        with pytest.raises(RoutingContractError, match="validation failed"):
            probe_signed_routing_contract(**inputs)
    assert preflight.call_count == 2


def test_post_factory_source_drift_blocks_routing_success(
    scene: tuple[dict[str, Any], ObservedProviderImport],
) -> None:
    inputs, observed = scene
    after = ObservedProviderImport(
        observed.transaction_id,
        observed.component_id,
        observed.group,
        observed.status,
        observed.target,
        "1" * 64,
        observed.native_payload_sha256,
        observed.provider_declaration_sha256,
    )
    with (
        patch(
            "paper_data_suite.evergreen_routing_contract_probe."
            "probe_signed_provider_import",
            side_effect=[observed, after],
        ),
        patch("paper_data_suite.evergreen_routing_contract_probe._run_check"),
    ):
        with pytest.raises(RoutingContractError, match="drifted"):
            probe_signed_routing_contract(**inputs)


def test_provenance_failure_never_invokes_contract_factory(
    scene: tuple[dict[str, Any], ObservedProviderImport],
) -> None:
    inputs, _ = scene
    with (
        patch(
            "paper_data_suite.evergreen_routing_contract_probe."
            "probe_signed_provider_import",
            side_effect=ProviderImportError("bad wheel"),
        ),
        patch(
            "paper_data_suite.evergreen_routing_contract_probe._run_check",
            side_effect=AssertionError("must not run"),
        ),
    ):
        with pytest.raises(RoutingContractError, match="preflight"):
            probe_signed_routing_contract(**inputs)


def test_classroom_workspace_never_used_for_routing_check(
    scene: tuple[dict[str, Any], ObservedProviderImport],
) -> None:
    inputs, observed = scene
    workspaces: list[Path] = []

    def check(*args: Any, **kwargs: Any) -> None:
        workspaces.append(kwargs["working"])
        assert inputs["classroom_workspace"] not in kwargs["working"].parents
        assert kwargs["environment"]["PIP_NO_INDEX"] == "1"
        assert kwargs["environment"]["PDS_EXPECTED_VENV_ROOT"] == str(
            inputs["stage_root"]
        )

    with (
        patch(
            "paper_data_suite.evergreen_routing_contract_probe."
            "probe_signed_provider_import",
            return_value=observed,
        ),
        patch(
            "paper_data_suite.evergreen_routing_contract_probe._run_check",
            side_effect=check,
        ),
    ):
        probe_signed_routing_contract(**inputs)
    assert len(workspaces) == 1
    assert not workspaces[0].exists()
    assert list(inputs["classroom_workspace"].iterdir()) == []


def test_incorrect_module_identity_disallowed_before_factory(
    scene: tuple[dict[str, Any], ObservedProviderImport],
) -> None:
    inputs, observed = scene
    inputs["component_id"] = "not_registered"
    with (
        patch(
            "paper_data_suite.evergreen_routing_contract_probe."
            "probe_signed_provider_import",
            return_value=observed,
        ),
        patch(
            "paper_data_suite.evergreen_routing_contract_probe._run_check",
            side_effect=AssertionError("must not run"),
        ),
    ):
        with pytest.raises(RoutingContractError, match="scope mismatch"):
            probe_signed_routing_contract(**inputs)


def _routing_wheel(path: Path) -> None:
    """Authentic signed fixture can import routing factory but lacks Core."""
    import io
    import zipfile

    from test_issue49_slice9_virtualenv_runtime import _console_wheel

    _console_wheel(path)
    rewritten = io.BytesIO()
    with (
        zipfile.ZipFile(path) as original,
        zipfile.ZipFile(rewritten, "w", compression=zipfile.ZIP_DEFLATED) as output,
    ):
        for member in original.infolist():
            if member.filename.endswith("/entry_points.txt"):
                continue
            content = (
                b"# fixture package\n"
                if member.filename == "demo_app/__init__.py"
                else original.read(member)
            )
            output.writestr(member, content)
        output.writestr(
            "demo_app-1.0.0.dist-info/entry_points.txt",
            "[console_scripts]\ndemo = demo_app.cli:main\n\n"
            "[paper_data_suite.modules]\n"
            "demo = demo_app.pds_module:get_profile\n",
        )
        output.writestr(
            "demo_app/pds_module.py",
            b"def get_profile():\n"
            b"    raise AssertionError('factory must not run without Core')\n",
        )
    path.write_bytes(rewritten.getvalue())


def test_real_offline_signed_routing_without_core_contract_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importability is not proof of an installed pds-core routing API."""
    import test_issue49_slice23_real_pip_direct_url as pip_fixture
    import test_issue49_slice24_publisher_pip_preflight as pub_fixture
    import test_issue49_slice28_provider_import as import_fixture

    root = tmp_path / "private-software"
    root.mkdir()
    with monkeypatch.context() as context:
        context.setattr(
            pip_fixture,
            "_console_wheel",
            _routing_wheel,
        )
        stage, wheels, registry, lock, prepared, release = pub_fixture._signed_stage(
            root, context
        )
    workspace = tmp_path / "classroom-no-write"
    workspace.mkdir()
    options: dict[str, Any] = {
        "stage_root": stage,
        "wheelhouse": wheels,
        "classroom_workspace": workspace,
        "prepared_record": prepared,
        "registry_envelope": registry,
        "lock_envelope": lock,
        "evidence_envelope": import_fixture._native_evidence(stage, prepared),
        "module_envelopes": {"demo": release},
        "component_id": "demo",
        "trust": _ring(),
        "now": NOW,
        "allow_candidate_execution": True,
    }
    with pytest.raises(RoutingContractError, match="validation failed"):
        probe_signed_routing_contract(**options)
    assert list(workspace.iterdir()) == []


def test_embedded_routing_core_probe_compiles_without_user_files() -> None:
    compile(_CONTRACT_SCRIPT, "<Core PDS2 routing contract>", "exec")
