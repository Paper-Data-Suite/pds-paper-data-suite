"""Slice 65: explicit update planning, never package or classroom mutation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice64_composition_review_plan as earlier

import paper_data_suite.evergreen_update_plan_cli as module
from paper_data_suite import cli
from paper_data_suite.evergreen_composition_review_plan import (
    CompositionReviewPlanError,
    plan_authenticated_composition_review,
)
from paper_data_suite.evergreen_selected_witness_cli import SelectedWitnessCliError
from paper_data_suite.evergreen_update_plan_cli import (
    UpdateReviewCliError,
    inspect_authenticated_update_review,
    parse_requested_targets,
    render_authenticated_update_review,
)

NOW = datetime(2026, 10, 25, 18, tzinfo=UTC)
PIN = "a" * 64


def inputs() -> dict[str, Any]:
    return {
        "catalog_cache": Path("catalog"),
        "trust_policy": Path("policy"),
        "pinned_policy_sha256": PIN,
        "witness_configuration": Path("witness.json"),
        "target_specs": ("quillan=0.10.0",),
        "python_minor": "3.11",
        "platform_tag": "win_arm64",
        "now": NOW,
    }


def test_parse_explicit_versions_removals_and_multiple_targets() -> None:
    assert parse_requested_targets(
        ("quillan=0.10.0", "scoreform=REMOVE", "portia=0.2.0")
    ) == {"quillan": "0.10.0", "scoreform": None, "portia": "0.2.0"}


@pytest.mark.parametrize(
    "requested",
    [
        (),
        ("quillan=",),
        ("quillan=latest",),
        ("quillan=0.10.0rc1",),
        ("quillan=0.10.0", "quillan=REMOVE"),
        ("Quillan=0.10.0",),
        ("quillan=0.10.0;echo",),
        ("quillan=../0.10.0",),
        ("core=remove",),
        ("unknown",),
        ("core=1.0.0\n",),
        tuple(f"unit{i}=1.0.0" for i in range(33)),
    ],
)
def test_invalid_requests_refuse_without_read_or_witness(
    requested: tuple[str, ...],
) -> None:
    with patch.object(
        module,
        "inspect_selected_witness_catalog_evidence",
        side_effect=AssertionError("must not read or query witness"),
    ):
        with pytest.raises(UpdateReviewCliError):
            inspect_authenticated_update_review(
                **{**inputs(), "target_specs": requested}
            )


@pytest.mark.parametrize(
    "change",
    [
        {"witness_configuration": None},
        {"catalog_cache": "not a Path"},
        {"trust_policy": "not a Path"},
        {"now": datetime(2026, 10, 25, 18)},
    ],
)
def test_invalid_inputs_refuse_without_witness(change: dict[str, Any]) -> None:
    with patch.object(
        module,
        "inspect_selected_witness_catalog_evidence",
        side_effect=AssertionError("must not inspect"),
    ):
        with pytest.raises(UpdateReviewCliError, match="paths and aware clock"):
            inspect_authenticated_update_review(**{**inputs(), **change})


def test_authenticated_review_per_module_core_closure_and_scoped_attestation() -> None:
    snapshot, witnessed = earlier.sample()
    with (
        patch.object(
            module,
            "inspect_selected_witness_catalog_evidence",
            return_value=(snapshot, witnessed),
        ) as witness,
        patch("subprocess.run", side_effect=AssertionError("no process execution")),
        patch(
            "socket.create_connection", side_effect=AssertionError("no catalog fetch")
        ),
    ):
        report = inspect_authenticated_update_review(**inputs())
    witness.assert_called_once_with(
        catalog_cache=Path("catalog"),
        trust_policy=Path("policy"),
        pinned_policy_sha256=PIN,
        configuration=Path("witness.json"),
        now=NOW,
    )
    assert "UPGRADE   quillan: 0.9.0 -> 0.10.0 [requested]" in report
    assert "UPGRADE   core: 0.6.0 -> 0.7.0 [dependency_closure]" in report
    assert "UNCHANGED scoreform:" in report
    assert "quillan-core-routing: LOST_EXACT_CLAIM" in report
    assert "scoreform-solo-contract: RETAINED_EXACT_CLAIM" in report
    assert "NO DOWNLOAD, INSTALLATION, ACTIVATION OR LAUNCH AUTHORITY" in report
    assert "Complete authenticated transitive wheel lock: STILL REQUIRED" in report
    assert "No package operation or classroom workspace mutation" in report


def test_multiple_targets_and_external_requirements_honestly_reported() -> None:
    snapshot, witnessed = earlier.sample()
    with patch.object(
        module,
        "inspect_selected_witness_catalog_evidence",
        return_value=(snapshot, witnessed),
    ):
        report = inspect_authenticated_update_review(
            **{
                **inputs(),
                "target_specs": ("quillan=0.10.1", "portia=0.2.0"),
            }
        )
    assert "ADD       portia:" in report
    assert "packaging>=24.0" in report
    assert "Proposed signed wheel SHA-256:" in report


def test_rejected_witness_does_not_invoke_planner() -> None:
    with (
        patch.object(
            module,
            "inspect_selected_witness_catalog_evidence",
            side_effect=SelectedWitnessCliError("invalid witness pin"),
        ),
        patch.object(
            module,
            "plan_authenticated_composition_review",
            side_effect=AssertionError("must not plan"),
        ),
    ):
        with pytest.raises(UpdateReviewCliError, match="authenticated baseline"):
            inspect_authenticated_update_review(**inputs())


def test_invalid_signed_targets_refuse_without_report() -> None:
    snapshot, witnessed = earlier.sample()
    with patch.object(
        module,
        "inspect_selected_witness_catalog_evidence",
        return_value=(snapshot, witnessed),
    ):
        with pytest.raises(UpdateReviewCliError, match="could not be planned"):
            inspect_authenticated_update_review(
                **{**inputs(), "target_specs": ("quillan=9.9.9",)}
            )


def test_render_refuses_a_forged_report_object() -> None:
    with pytest.raises(UpdateReviewCliError, match="plan required"):
        render_authenticated_update_review(object())  # type: ignore[arg-type]


def test_render_reports_explicit_removals_without_running_anything() -> None:
    snapshot, witnessed = earlier.sample()
    plan = plan_authenticated_composition_review(
        snapshot,
        witnessed,
        requested_targets={"scoreform": None},
        python_minor="3.11",
        platform_tag="win_arm64",
    )
    result = render_authenticated_update_review(plan)
    assert "REMOVE    scoreform: 0.13.0 -> (removed) [requested]" in result
    assert "scoreform-solo-contract: LOST_EXACT_CLAIM" in result


def test_planner_refusal_is_not_reclassified_as_safe_plan() -> None:
    with (
        patch.object(
            module,
            "inspect_selected_witness_catalog_evidence",
            return_value=earlier.sample(),
        ),
        patch.object(
            module,
            "plan_authenticated_composition_review",
            side_effect=CompositionReviewPlanError("conflict"),
        ),
    ):
        with pytest.raises(UpdateReviewCliError):
            inspect_authenticated_update_review(**inputs())


def test_cli_default_and_existing_legacy_commands_unchanged() -> None:
    parser = cli.build_parser()
    parsed = parser.parse_args(["modules"])
    assert parsed.command == "modules"
    plan = parser.parse_args(
        [
            "update",
            "--plan",
            "--target",
            "quillan=0.10.0",
            "--catalog-cache",
            "cache",
            "--trust-policy",
            "policy",
            "--trust-sha256",
            PIN,
            "--witness-config",
            "witness.json",
        ]
    )
    assert plan.command == "update"
    assert plan.plan is True
    assert plan.target == ["quillan=0.10.0"]
    assert plan.witness_config == Path("witness.json")


@pytest.mark.parametrize(
    "missing", ["plan", "target", "cache", "policy", "pin", "witness"]
)
def test_incomplete_cli_arguments_refuse_before_any_inspection(
    missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = {
        "plan": True,
        "target": ("quillan=0.10.0",),
        "catalog_cache": Path("cache"),
        "trust_policy": Path("policy"),
        "trust_sha256": PIN,
        "witness_config": Path("witness.json"),
    }
    key = {
        "cache": "catalog_cache",
        "policy": "trust_policy",
        "pin": "trust_sha256",
        "witness": "witness_config",
    }.get(missing, missing)
    arguments[key] = () if missing == "target" else False if missing == "plan" else None
    with patch.object(
        cli,
        "inspect_authenticated_update_review",
        side_effect=AssertionError("must not inspect"),
    ):
        assert cli._run_update(**arguments) == 2
    assert "requires" in capsys.readouterr().err.lower()


def test_cli_real_dispatch_is_opt_in_and_no_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(
            cli, "inspect_authenticated_update_review", return_value="plan only\n"
        ) as adapter,
        patch.object(cli, "_run_launch", side_effect=AssertionError("launch")),
        patch.object(cli, "_run_modules", side_effect=AssertionError("modules")),
    ):
        rc = cli.main(
            [
                "update",
                "--plan",
                "--target",
                "quillan=0.10.0",
                "--catalog-cache",
                "cache",
                "--trust-policy",
                "policy",
                "--trust-sha256",
                PIN,
                "--witness-config",
                "witness.json",
            ]
        )
    assert rc == 0
    assert capsys.readouterr().out == "plan only\n"
    assert adapter.call_args.kwargs["target_specs"] == ("quillan=0.10.0",)
    assert adapter.call_args.kwargs["witness_configuration"] == Path("witness.json")
    assert isinstance(adapter.call_args.kwargs["now"], datetime)


def test_cli_refused_plan_does_not_fallback_or_print_partial_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.object(
        cli,
        "inspect_authenticated_update_review",
        side_effect=UpdateReviewCliError("invalid catalog"),
    ):
        rc = cli._run_update(
            plan=True,
            target=("quillan=0.10.0",),
            catalog_cache=Path("cache"),
            trust_policy=Path("policy"),
            trust_sha256=PIN,
            witness_config=Path("witness.json"),
        )
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == "" and "refused" in out.err


def test_explicit_update_without_plan_cannot_mutate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        cli._run_update(
            plan=False,
            target=("quillan=0.10.0",),
            catalog_cache=Path("cache"),
            trust_policy=Path("policy"),
            trust_sha256=PIN,
            witness_config=Path("witness.json"),
        )
        == 2
    )
    assert "requires" in capsys.readouterr().err.lower()
