from __future__ import annotations

from pathlib import Path

import pytest

from paper_data_suite.classroom_apply import load_core_classroom_apply_services
from paper_data_suite.classroom_planning import load_core_classroom_planning_services


def _write_roster(path: Path, *, first_name: str = "Alex") -> None:
    path.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        f"eng10,student001,Student,{first_name},2\n",
        encoding="utf-8",
        newline="",
    )


def test_exact_core_v063_guarded_roster_contract_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "incoming.csv"
    _write_roster(source)

    planning = load_core_classroom_planning_services()
    apply = load_core_classroom_apply_services()

    assert planning.plan_guarded_roster_import is not None
    assert apply.commit_roster_import is not None

    preview = planning.plan_guarded_roster_import(tmp_path, "eng10", source)
    assert preview.current_roster_present is False
    assert preview.addition_count == 1
    assert preview.change_count == 0
    assert preview.removal_count == 0
    assert preview.unchanged_count == 0

    result = apply.commit_roster_import(
        tmp_path,
        "eng10",
        source,
        expected_current_state_token=preview.current_state_token,
        expected_candidate_state_token=preview.candidate_state_token,
    )
    assert result.class_id == "eng10"
    assert result.previous_state_token == preview.current_state_token
    assert result.committed_state_token == preview.candidate_state_token

    verified = planning.plan_guarded_roster_import(
        tmp_path,
        "eng10",
        result.roster,
    )
    assert verified.current_state_token == preview.candidate_state_token
    assert verified.candidate_state_token == preview.candidate_state_token
    assert verified.addition_count == 0
    assert verified.change_count == 0
    assert verified.removal_count == 0
    assert verified.unchanged_count == 1


def test_exact_core_v063_guarded_commit_rejects_changed_candidate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "incoming.csv"
    _write_roster(source)

    planning = load_core_classroom_planning_services()
    apply = load_core_classroom_apply_services()
    assert planning.plan_guarded_roster_import is not None
    assert apply.commit_roster_import is not None
    preview = planning.plan_guarded_roster_import(tmp_path, "eng10", source)

    _write_roster(source, first_name="Changed")

    with pytest.raises(apply.roster_import_candidate_changed_error):
        apply.commit_roster_import(
            tmp_path,
            "eng10",
            source,
            expected_current_state_token=preview.current_state_token,
            expected_candidate_state_token=preview.candidate_state_token,
        )


def test_exact_core_v063_guarded_commit_rejects_first_import_absent_state_race(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    _write_roster(first, first_name="Alex")
    _write_roster(second, first_name="Taylor")

    planning = load_core_classroom_planning_services()
    apply = load_core_classroom_apply_services()
    assert planning.plan_guarded_roster_import is not None
    assert apply.commit_roster_import is not None

    stale = planning.plan_guarded_roster_import(tmp_path, "eng10", second)
    initial = planning.plan_guarded_roster_import(tmp_path, "eng10", first)
    apply.commit_roster_import(
        tmp_path,
        "eng10",
        first,
        expected_current_state_token=initial.current_state_token,
        expected_candidate_state_token=initial.candidate_state_token,
    )

    with pytest.raises(apply.roster_import_conflict_error):
        apply.commit_roster_import(
            tmp_path,
            "eng10",
            second,
            expected_current_state_token=stale.current_state_token,
            expected_candidate_state_token=stale.candidate_state_token,
        )


def test_exact_core_v063_guarded_commit_rejects_changed_existing_canonical(
    tmp_path: Path,
) -> None:
    initial_source = tmp_path / "initial.csv"
    reviewed_source = tmp_path / "reviewed.csv"
    intervening_source = tmp_path / "intervening.csv"
    _write_roster(initial_source, first_name="Initial")
    _write_roster(reviewed_source, first_name="Reviewed")
    _write_roster(intervening_source, first_name="Intervening")

    planning = load_core_classroom_planning_services()
    apply = load_core_classroom_apply_services()
    assert planning.plan_guarded_roster_import is not None
    assert apply.commit_roster_import is not None

    initial = planning.plan_guarded_roster_import(
        tmp_path,
        "eng10",
        initial_source,
    )
    apply.commit_roster_import(
        tmp_path,
        "eng10",
        initial_source,
        expected_current_state_token=initial.current_state_token,
        expected_candidate_state_token=initial.candidate_state_token,
    )

    reviewed = planning.plan_guarded_roster_import(
        tmp_path,
        "eng10",
        reviewed_source,
    )
    intervening = planning.plan_guarded_roster_import(
        tmp_path,
        "eng10",
        intervening_source,
    )
    apply.commit_roster_import(
        tmp_path,
        "eng10",
        intervening_source,
        expected_current_state_token=intervening.current_state_token,
        expected_candidate_state_token=intervening.candidate_state_token,
    )

    with pytest.raises(apply.roster_import_conflict_error):
        apply.commit_roster_import(
            tmp_path,
            "eng10",
            reviewed_source,
            expected_current_state_token=reviewed.current_state_token,
            expected_candidate_state_token=reviewed.candidate_state_token,
        )


def test_suite_apply_has_no_direct_roster_write_call() -> None:
    root = Path(__file__).resolve().parents[1]
    apply_source = (root / "paper_data_suite" / "classroom_apply.py").read_text(
        encoding="utf-8"
    )
    planning_source = (
        root / "paper_data_suite" / "classroom_planning.py"
    ).read_text(encoding="utf-8")

    assert "services.write_class_roster(" not in apply_source
    assert "_jit_check_roster_replacement" not in apply_source
    assert "def _roster_material" not in planning_source
