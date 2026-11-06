"""Slice 64: full PDS dependency closure preview without software mutation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from paper_data_suite.evergreen_catalog_contracts import (
    AuthorizedModuleClaim,
    ExactArtifactClaim,
    IntegrationClaims,
    MetadataWindow,
    ModuleReleaseClaims,
    RegistryClaims,
    ReleaseClaim,
)
from paper_data_suite.evergreen_catalog_stage_correlation import CatalogStagedWheel
from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    VerifiedIntegrationDocument,
    VerifiedModuleDocument,
    VerifiedRegistryDocument,
)
from paper_data_suite.evergreen_composition_review_plan import (
    ChangeOrigin,
    CompositionReviewPlanError,
    FeatureDelta,
    PlannedAction,
    plan_authenticated_composition_review,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)

NOW = datetime(2026, 10, 25, 16, tzinfo=UTC)
SHA = {key: key * 64 for key in "abcdef1234567890"}


def claim(
    version: str,
    digest: str,
    distribution: str,
    dependency: tuple[str, ...] = (),
    *,
    revoked: bool = False,
    python: str = ">=3.11",
) -> ReleaseClaim:
    return ReleaseClaim(
        version,
        "v" + version,
        distribution.replace("-", "_") + "-" + version + "-py3-none-any.whl",
        digest,
        python,
        dependency,
        distribution.removeprefix("pds-"),
        distribution.replace("-", "_") + ".cli:main",
        revoked,
    )


def sample() -> tuple[CatalogSnapshot, WitnessSelectedStageObservation]:
    window = MetadataWindow(2, NOW - timedelta(days=1), NOW + timedelta(days=3))
    ids = ("core", "quillan", "scoreform", "portia")
    registered = tuple(
        AuthorizedModuleClaim(
            key, "Paper-Data-Suite/pds-" + key, "pds-" + key, (key + "-key",)
        )
        for key in ids
    )
    registry = VerifiedRegistryDocument(
        RegistryClaims(window, registered, ("integration-key",)),
        SHA["a"],
        ("root-key",),
        RevisionCheckpoint(2, SHA["a"]),
        SHA["a"],
    )
    options = {
        "core": (
            claim("0.6.0", SHA["b"], "pds-core"),
            claim("0.7.0", SHA["c"], "pds-core"),
        ),
        "quillan": (
            claim("0.9.0", SHA["d"], "pds-quillan", ("pds-core>=0.6.0",)),
            claim("0.10.0", SHA["e"], "pds-quillan", ("pds-core>=0.7.0",)),
            claim(
                "0.10.1",
                SHA["1"],
                "pds-quillan",
                ("pds-core>=0.7.0", "packaging>=24.0"),
            ),
            claim("0.8.0", SHA["2"], "pds-quillan", revoked=True),
        ),
        "scoreform": (
            claim("0.13.0", SHA["f"], "pds-scoreform", ("pds-core>=0.6.0",)),
        ),
        "portia": (claim("0.2.0", SHA["3"], "pds-portia", ("pds-core>=0.6.0",)),),
    }
    documents = tuple(
        VerifiedModuleDocument(
            ModuleReleaseClaims(
                window,
                key,
                registered[i].repository,
                registered[i].distribution,
                options[key],
            ),
            SHA["a"],
            {
                "core": SHA["4"],
                "quillan": SHA["5"],
                "scoreform": SHA["6"],
                "portia": SHA["7"],
            }[key],
            (key + "-key",),
            RevisionCheckpoint(2, SHA["8"]),
        )
        for i, key in enumerate(ids)
    )
    exact = (
        VerifiedIntegrationDocument(
            IntegrationClaims(
                window,
                "quillan-core-routing",
                SHA["9"],
                "passed",
                (
                    ExactArtifactClaim("quillan", SHA["d"]),
                    ExactArtifactClaim("core", SHA["b"]),
                ),
                ("3.11",),
                ("win_arm64",),
            ),
            SHA["a"],
            SHA["9"],
            ("integration-key",),
            RevisionCheckpoint(2, SHA["9"]),
        ),
        VerifiedIntegrationDocument(
            IntegrationClaims(
                window,
                "scoreform-solo-contract",
                SHA["9"],
                "passed",
                (ExactArtifactClaim("scoreform", SHA["f"]),),
                ("3.11",),
                ("win_arm64",),
            ),
            SHA["a"],
            SHA["9"],
            ("integration-key",),
            RevisionCheckpoint(2, SHA["9"]),
        ),
    )
    snapshot = CatalogSnapshot(registry, documents, exact, NOW)
    observed = WitnessSelectedStageObservation(
        "e" * 32,
        1,
        3,
        SHA["a"],
        SHA["b"],
        SHA["c"],
        SHA["d"],
        (
            CatalogStagedWheel(
                "core", "pds-core", "0.6.0", SHA["b"], documents[0].payload_sha256
            ),
            CatalogStagedWheel(
                "quillan",
                "pds-quillan",
                "0.9.0",
                SHA["d"],
                documents[1].payload_sha256,
            ),
            CatalogStagedWheel(
                "scoreform",
                "pds-scoreform",
                "0.13.0",
                SHA["f"],
                documents[2].payload_sha256,
            ),
        ),
    )
    return snapshot, observed


def run(changes: dict[str, str | None], **other: Any) -> Any:
    snap, observed = sample()
    return plan_authenticated_composition_review(
        other.pop("snapshot", snap),
        other.pop("observed", observed),
        requested_targets=changes,
        python_minor=other.pop("python_minor", "3.11"),
        platform_tag=other.pop("platform_tag", "win_arm64"),
        **other,
    )


def by_component(plan: Any) -> dict[str, Any]:
    return {row.component_id: row for row in plan.modules}


def test_one_module_upgrade_plans_core_dependency_closure() -> None:
    with (
        patch("subprocess.run", side_effect=AssertionError("must not execute")),
        patch("socket.create_connection", side_effect=AssertionError("must not fetch")),
    ):
        plan = run({"quillan": "0.10.0"})
    rows = by_component(plan)
    assert rows["quillan"].action is PlannedAction.UPGRADE
    assert rows["quillan"].origin is ChangeOrigin.REQUESTED
    assert rows["core"].action is PlannedAction.UPGRADE
    assert rows["core"].origin is ChangeOrigin.DEPENDENCY_CLOSURE
    assert rows["scoreform"].action is PlannedAction.UNCHANGED
    assert plan.external_requirements == ()
    assert {x.feature_id: x.delta for x in plan.features} == {
        "quillan-core-routing": FeatureDelta.LOST,
        "scoreform-solo-contract": FeatureDelta.RETAINED,
    }
    assert plan.authority == (
        "NO_DOWNLOAD_INSTALL_ACTIVATION_RECEIPT_OR_LAUNCH_AUTHORITY"
    )
    assert "FULL_SIGNED_LOCK_STILL_REQUIRED" in plan.status


def test_whole_composition_explicit_add_and_upgrade() -> None:
    plan = run({"portia": "0.2.0", "quillan": "0.10.0"})
    rows = by_component(plan)
    assert rows["portia"].action is PlannedAction.ADD
    assert rows["portia"].to_wheel_sha256 == SHA["3"]
    assert rows["core"].action is PlannedAction.UPGRADE


def test_explicit_remove_does_not_remove_unrelated_modules() -> None:
    plan = run({"scoreform": None})
    rows = by_component(plan)
    assert rows["scoreform"].action is PlannedAction.REMOVE
    assert rows["core"].action is PlannedAction.UNCHANGED
    assert rows["quillan"].action is PlannedAction.UNCHANGED
    deltas = {x.feature_id: x.delta for x in plan.features}
    assert deltas["scoreform-solo-contract"] is FeatureDelta.LOST


def test_external_dependency_is_outstanding_signed_lock_requirement() -> None:
    plan = run({"quillan": "0.10.1"})
    assert plan.external_requirements == ("packaging>=24.0",)
    assert "LOCK_STILL_REQUIRED" in plan.status


def test_current_release_preferred_to_an_unneeded_update() -> None:
    plan = run({"portia": "0.2.0"})
    assert by_component(plan)["core"].action is PlannedAction.UNCHANGED


@pytest.mark.parametrize(
    "targets",
    [
        {},
        {"unknown": "1.0.0"},
        {"quillan": "99.0.0"},
        {"quillan": "0.8.0"},
        {"scoreform": None, "portia": None},
        {"scoreform": None, "quillan": "0.10.0", "core": None},
        {"core": "0.6.0", "quillan": "0.10.0"},
    ],
)
def test_unapproved_or_conflicting_requests_refuse(
    targets: dict[str, str | None],
) -> None:
    with pytest.raises(CompositionReviewPlanError):
        run(targets)


@pytest.mark.parametrize(
    "minor,platform",
    [("3.10", "win_arm64"), ("3.11", ""), ("no", "linux_x86_64")],
)
def test_invalid_runtime_inputs_refuse(minor: str, platform: str) -> None:
    with pytest.raises(CompositionReviewPlanError):
        run({"quillan": "0.10.0"}, python_minor=minor, platform_tag=platform)


def test_bad_observed_wheel_sha_refuses() -> None:
    snap, observed = sample()
    bad = replace(observed.modules[0], wheel_sha256=SHA["0"])
    with pytest.raises(CompositionReviewPlanError, match="baseline"):
        run(
            {"quillan": "0.10.0"},
            snapshot=snap,
            observed=replace(observed, modules=(bad, *observed.modules[1:])),
        )


def test_unsigned_publisher_refuses() -> None:
    snap, observed = sample()
    bad = replace(snap.modules[0], registry_payload_sha256=SHA["0"])
    with pytest.raises(CompositionReviewPlanError, match="publisher"):
        run(
            {"quillan": "0.10.0"},
            snapshot=replace(snap, modules=(bad, *snap.modules[1:])),
            observed=observed,
        )


def test_unresolved_registered_dependency_refuses() -> None:
    snap, observed = sample()
    docs = list(snap.modules)
    initial = docs[1].claims.releases[1]
    altered = replace(initial, requires_dist=("pds-core>=9.0.0",))
    docs[1] = replace(
        docs[1],
        claims=replace(
            docs[1].claims,
            releases=(
                docs[1].claims.releases[0],
                altered,
                *docs[1].claims.releases[2:],
            ),
        ),
    )
    with pytest.raises(CompositionReviewPlanError, match="no approved release"):
        run({"quillan": "0.10.0"}, snapshot=replace(snap, modules=tuple(docs)))


def test_external_direct_url_refused() -> None:
    snap, _ = sample()
    docs = list(snap.modules)
    old = docs[1].claims.releases[1]
    bad = replace(old, requires_dist=("external @ https://example.com/pkg.whl",))
    docs[1] = replace(
        docs[1],
        claims=replace(
            docs[1].claims,
            releases=(
                docs[1].claims.releases[0],
                bad,
                *docs[1].claims.releases[2:],
            ),
        ),
    )
    with pytest.raises(CompositionReviewPlanError, match="direct-URL"):
        run({"quillan": "0.10.0"}, snapshot=replace(snap, modules=tuple(docs)))


def test_platform_scope_does_not_inherit_exact_attestation() -> None:
    plan = run({"portia": "0.2.0"}, platform_tag="win_amd64")
    assert all(x.delta is FeatureDelta.UNQUALIFIED for x in plan.features)


def test_deterministic_read_only_plan() -> None:
    assert run({"quillan": "0.10.0"}) == run({"quillan": "0.10.0"})
