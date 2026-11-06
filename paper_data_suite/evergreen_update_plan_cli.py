"""Issue #49 Slice 65: explicitly requested, read-only update review CLI.

The authenticated catalog and witness-selected staged bytes are observed
freshly through the existing Slice 63 adapter. No plan constitutes permission
to download, install, alter active state, run code, or change classroom data.
This command may contact an independently provisioned witness; ordinary Suite
commands must not. Full signed transitive wheel locks remain mandatory.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from paper_data_suite.evergreen_composition_review_plan import (
    CompositionReviewPlan,
    CompositionReviewPlanError,
    plan_authenticated_composition_review,
)
from paper_data_suite.evergreen_selected_witness_cli import (
    SelectedWitnessCliError,
    inspect_selected_witness_catalog_evidence,
)

_TARGET = re.compile(
    r"([a-z][a-z0-9_-]{1,47})="
    r"([0-9]+\.[0-9]+\.[0-9]+(?:\.post[0-9]+)?|REMOVE)\Z"
)
_MAX_TARGETS = 32


class UpdateReviewCliError(ValueError):
    """Requested read-only update preview cannot be safely produced."""


def parse_requested_targets(specifications: tuple[str, ...]) -> dict[str, str | None]:
    """Require explicit, distinct, exact release targets or a deliberate REMOVE."""
    if (
        type(specifications) is not tuple
        or not 1 <= len(specifications) <= _MAX_TARGETS
        or any(type(spec) is not str for spec in specifications)
    ):
        raise UpdateReviewCliError("one to 32 explicit --target requests required")
    targets: dict[str, str | None] = {}
    for raw in specifications:
        match = _TARGET.fullmatch(raw)
        if match is None:
            raise UpdateReviewCliError(
                "target must be component=exact.version or component=REMOVE"
            )
        component, selection = match.groups()
        if component in targets:
            raise UpdateReviewCliError("duplicate requested component")
        targets[component] = None if selection == "REMOVE" else selection
    return targets


def render_authenticated_update_review(plan: CompositionReviewPlan) -> str:
    """Render only review facts; no field grants installation authority."""
    if not isinstance(plan, CompositionReviewPlan):
        raise UpdateReviewCliError("authenticated review plan required")
    lines = [
        "Paper Data Suite — authenticated update review (read-only)",
        "",
        "PLAN ONLY — NO DOWNLOAD, INSTALLATION, ACTIVATION OR LAUNCH AUTHORITY.",
        "A fresh signed witness query was requested; "
        "this is not protected active state.",
        "Complete authenticated transitive wheel lock: STILL REQUIRED",
        "Trust-policy and witness pins require independent provenance.",
        "",
        f"Baseline transaction: {plan.baseline_transaction_id}",
        f"Witness revision: {plan.baseline_witness_revision}",
        f"Signed registry SHA-256: {plan.registry_payload_sha256}",
        f"Target Python/platform: {plan.python_minor} / {plan.platform_tag}",
        "",
        "Proposed PDS release changes:",
    ]
    for row in plan.modules:
        source = row.from_version if row.from_version is not None else "(absent)"
        target = row.to_version if row.to_version is not None else "(removed)"
        lines.append(
            f"  {row.action.value:9} {row.component_id}: {source} -> {target} "
            f"[{row.origin.value}]"
        )
        if row.to_wheel_sha256 is not None:
            lines.append(f"    Proposed signed wheel SHA-256: {row.to_wheel_sha256}")
    lines.extend(("", "Named exact integration-qualification changes:"))
    if not plan.features:
        lines.append("  No signed exact integration claims in this catalog")
    for feature in plan.features:
        lines.append(
            f"  {feature.feature_id}: {feature.delta.value} "
            f"(signed result: {feature.signed_result})"
        )
    lines.extend(("", "External dependency requirements (not resolved/installed):"))
    if not plan.external_requirements:
        lines.append("  None declared by selected PDS releases")
    for requirement in plan.external_requirements:
        lines.append(f"  {requirement}")
    lines.extend(
        (
            "",
            "PDS dependency closure is a review proposal, NOT a verified wheelhouse.",
            "No package operation or classroom workspace mutation was performed.",
            "A separate authenticated plan-to-apply and recovery flow is required.",
        )
    )
    return "\n".join(lines) + "\n"


def inspect_authenticated_update_review(
    *,
    catalog_cache: Path,
    trust_policy: Path,
    pinned_policy_sha256: str,
    witness_configuration: Path,
    target_specs: tuple[str, ...],
    python_minor: str,
    platform_tag: str,
    now: datetime,
) -> str:
    """Reverify catalog and witness-selected bytes, then calculate a preview.

    Refuse invalid targets before any file read or witness network request.
    Never infer a trusted target from a package's self-reported version.
    """
    requested = parse_requested_targets(target_specs)
    if (
        not isinstance(catalog_cache, Path)
        or not isinstance(trust_policy, Path)
        or not isinstance(witness_configuration, Path)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise UpdateReviewCliError("explicit paths and aware clock required")
    try:
        snapshot, witnessed = inspect_selected_witness_catalog_evidence(
            catalog_cache=catalog_cache,
            trust_policy=trust_policy,
            pinned_policy_sha256=pinned_policy_sha256,
            configuration=witness_configuration,
            now=now,
        )
        planned = plan_authenticated_composition_review(
            snapshot,
            witnessed,
            requested_targets=requested,
            python_minor=python_minor,
            platform_tag=platform_tag,
        )
    except (SelectedWitnessCliError, CompositionReviewPlanError, OSError) as error:
        raise UpdateReviewCliError(
            "authenticated baseline or requested composition could not be planned"
        ) from error
    return render_authenticated_update_review(planned)


__all__ = (
    "UpdateReviewCliError",
    "inspect_authenticated_update_review",
    "parse_requested_targets",
    "render_authenticated_update_review",
)
