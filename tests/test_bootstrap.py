from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from paper_data_suite.bootstrap import (
    BootstrapPlanningError,
    EnvironmentMarkerIdentity,
    EnvironmentSnapshot,
    InstalledDistribution,
    build_bootstrap_plan,
)
from paper_data_suite.compatibility import load_release_compatibility_manifest

_MANIFEST_SHA256 = "a" * 64


def _installed(**versions: str) -> tuple[InstalledDistribution, ...]:
    return tuple(
        InstalledDistribution(distribution=name, version=version)
        for name, version in versions.items()
    )


def _snapshot(
    *,
    exists: bool = False,
    is_virtual_environment: bool = False,
    python_version: str = "3.11.9",
    suite_version: str | None = None,
    manifest_sha256: str = _MANIFEST_SHA256,
    installed: tuple[InstalledDistribution, ...] = (),
) -> EnvironmentSnapshot:
    marker = (
        None
        if suite_version is None
        else EnvironmentMarkerIdentity(
            suite_version=suite_version,
            compatibility_manifest_sha256=manifest_sha256,
        )
    )
    return EnvironmentSnapshot(
        path=r"C:\Users\Teacher\AppData\Local\Paper Data Suite\envs\0.1.0.dev0",
        exists=exists,
        is_virtual_environment=is_virtual_environment,
        python_version=python_version,
        marker=marker,
        installed_distributions=installed,
    )


def _plan(
    environment: EnvironmentSnapshot,
    selected: tuple[str, ...] = (),
):
    return build_bootstrap_plan(
        load_release_compatibility_manifest(),
        compatibility_manifest_sha256=_MANIFEST_SHA256,
        environment=environment,
        selected_component_ids=selected,
    )


def _package_actions(plan) -> dict[str, str]:
    return {item.component_id: item.action for item in plan.packages}


def test_new_environment_plan_is_deterministic_and_install_only_selected() -> None:
    plan = _plan(
        _snapshot(),
        selected=("scoreform", "quillan"),
    )

    assert plan.environment.action == "create_environment"
    assert plan.can_apply
    assert plan.changes_required
    assert tuple(item.component_id for item in plan.packages) == (
        "core",
        "suite",
        "concord",
        "quillan",
        "scoreform",
        "vitrine",
    )
    assert _package_actions(plan) == {
        "core": "install_missing",
        "suite": "install_missing",
        "concord": "skip_unselected_optional",
        "quillan": "install_missing",
        "scoreform": "install_missing",
        "vitrine": "skip_unselected_optional",
    }


def test_existing_exact_environment_keeps_all_selected_packages() -> None:
    manifest = load_release_compatibility_manifest()
    installed = _installed(
        **{
            manifest.suite.distribution: manifest.suite.version,
            **{
                item.distribution: item.version
                for item in manifest.components
            },
        }
    )
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version=manifest.suite.version,
            installed=installed,
        ),
        selected=("concord", "quillan", "scoreform", "vitrine"),
    )

    assert plan.environment.action == "keep_environment"
    assert plan.can_apply
    assert not plan.changes_required
    assert all(item.action == "keep_exact" for item in plan.packages)


def test_missing_selected_optional_is_installed() -> None:
    plan = _plan(_snapshot(), selected=("vitrine",))

    assert _package_actions(plan)["vitrine"] == "install_missing"


def test_missing_unselected_optional_is_skipped() -> None:
    plan = _plan(_snapshot())

    assert _package_actions(plan)["quillan"] == "skip_unselected_optional"


def test_exact_unselected_optional_is_retained() -> None:
    manifest = load_release_compatibility_manifest()
    quillan = next(
        item for item in manifest.components if item.component_id == "quillan"
    )
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version=manifest.suite.version,
            installed=_installed(**{quillan.distribution: quillan.version}),
        )
    )

    assert _package_actions(plan)["quillan"] == "keep_exact"


def test_incompatible_core_blocks_instead_of_replacing() -> None:
    manifest = load_release_compatibility_manifest()
    core = next(
        item for item in manifest.components if item.component_id == "core"
    )
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version=manifest.suite.version,
            installed=_installed(**{core.distribution: "0.6.99"}),
        )
    )

    core_plan = next(item for item in plan.packages if item.component_id == "core")
    assert core_plan.action == "blocked_incompatible"
    assert not plan.can_apply
    assert any(
        blocker.component_id == "core"
        and blocker.code == "incompatible_pds_version"
        for blocker in plan.blockers
    )


def test_incompatible_unselected_optional_still_blocks() -> None:
    manifest = load_release_compatibility_manifest()
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version=manifest.suite.version,
            installed=_installed(scoreform="0.11.0"),
        )
    )

    scoreform = next(
        item for item in plan.packages if item.component_id == "scoreform"
    )
    assert scoreform.action == "blocked_incompatible"
    assert not plan.can_apply


def test_incompatible_suite_package_blocks() -> None:
    manifest = load_release_compatibility_manifest()
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version=manifest.suite.version,
            installed=_installed(**{"paper-data-suite": "0.2.0"}),
        )
    )

    suite = next(item for item in plan.packages if item.component_id == "suite")
    assert suite.action == "blocked_incompatible"
    assert not plan.can_apply




def test_exact_version_editable_pds_install_blocks() -> None:
    manifest = load_release_compatibility_manifest()
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version=manifest.suite.version,
            installed=(
                InstalledDistribution(
                    distribution="scoreform",
                    version="0.10.0",
                    editable=True,
                ),
            ),
        )
    )

    scoreform = next(
        item for item in plan.packages if item.component_id == "scoreform"
    )
    assert scoreform.action == "blocked_incompatible"
    assert any(
        blocker.code == "incompatible_pds_installation"
        and blocker.component_id == "scoreform"
        for blocker in plan.blockers
    )

def test_unsupported_python_minor_blocks_environment() -> None:
    plan = _plan(_snapshot(python_version="3.15.0"))

    assert plan.environment.action == "blocked_environment"
    assert not plan.environment.python_qualified
    assert any(
        blocker.code == "unsupported_python" for blocker in plan.blockers
    )


def test_existing_unmarked_environment_is_not_adopted() -> None:
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version=None,
        )
    )

    assert plan.environment.action == "blocked_environment"
    assert any(
        blocker.code == "unmarked_environment" for blocker in plan.blockers
    )


def test_existing_non_venv_target_is_blocked() -> None:
    manifest = load_release_compatibility_manifest()
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=False,
            suite_version=manifest.suite.version,
        )
    )

    assert plan.environment.action == "blocked_environment"
    assert any(
        blocker.code == "invalid_environment" for blocker in plan.blockers
    )


def test_environment_suite_marker_mismatch_blocks() -> None:
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version="9.9.9",
        )
    )

    assert any(
        blocker.code == "environment_suite_mismatch"
        for blocker in plan.blockers
    )


def test_environment_manifest_marker_mismatch_blocks() -> None:
    manifest = load_release_compatibility_manifest()
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version=manifest.suite.version,
            manifest_sha256="b" * 64,
        )
    )

    assert any(
        blocker.code == "environment_manifest_mismatch"
        for blocker in plan.blockers
    )


def test_malformed_environment_marker_is_a_blocker() -> None:
    manifest = load_release_compatibility_manifest()
    plan = _plan(
        _snapshot(
            exists=True,
            is_virtual_environment=True,
            suite_version=manifest.suite.version,
            manifest_sha256="not-a-sha256",
        )
    )

    assert any(
        blocker.code == "invalid_environment_marker"
        for blocker in plan.blockers
    )


def test_unknown_optional_component_is_rejected() -> None:
    with pytest.raises(
        BootstrapPlanningError,
        match="unsupported optional component ID",
    ):
        _plan(_snapshot(), selected=("meridian",))


def test_duplicate_optional_selection_is_rejected() -> None:
    with pytest.raises(
        BootstrapPlanningError,
        match="must not contain duplicates",
    ):
        _plan(_snapshot(), selected=("vitrine", "vitrine"))


def test_selected_external_prerequisite_is_deduplicated() -> None:
    plan = _plan(
        _snapshot(),
        selected=("scoreform", "quillan"),
    )

    assert len(plan.external_prerequisites) == 1
    prerequisite = plan.external_prerequisites[0]
    assert prerequisite.prerequisite_id == "poppler_pdftoppm"
    assert prerequisite.commands == ("pdftoppm",)
    assert prerequisite.required_by == ("quillan", "scoreform")
    assert len(plan.warnings) == 1
    assert plan.warnings[0].code == "external_prerequisite_not_managed"


def test_plan_is_immutable_and_does_not_retain_mutable_selection() -> None:
    selected = ["scoreform"]
    plan = build_bootstrap_plan(
        load_release_compatibility_manifest(),
        compatibility_manifest_sha256=_MANIFEST_SHA256,
        environment=_snapshot(),
        selected_component_ids=selected,
    )
    selected.append("vitrine")

    assert next(
        item for item in plan.packages if item.component_id == "vitrine"
    ).action == "skip_unselected_optional"

    with pytest.raises(FrozenInstanceError):
        plan.environment.path = "changed"  # type: ignore[misc]


def test_invalid_environment_marker_blocks_explicitly() -> None:
    manifest = load_release_compatibility_manifest()
    environment = EnvironmentSnapshot(
        path=r"C:\Users\Teacher\AppData\Local\Paper Data Suite\envs\0.1.0.dev0",
        exists=True,
        is_virtual_environment=True,
        python_version="3.11.9",
        marker=None,
        marker_error="environment marker is invalid JSON",
        installed_distributions=(),
    )
    plan = build_bootstrap_plan(
        manifest,
        compatibility_manifest_sha256=_MANIFEST_SHA256,
        environment=environment,
    )

    assert not plan.can_apply
    assert any(
        blocker.code == "invalid_environment_marker"
        for blocker in plan.blockers
    )
