"""Suite #52 Slice 4: source-only teacher journey and negative boundaries."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from paper_data_suite import cli
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
    ApplicationObservation,
)
from paper_data_suite.teacher_experience_contracts import (
    CoreTeacherContractError,
    CoreTeacherContractObservation,
)
from paper_data_suite.teacher_home import run_teacher_home
from scripts import issue52_teacher_home_source_acceptance as witness


class TTY(StringIO):
    def isatty(self) -> bool:
        return True


def _legacy() -> CoreTeacherContractObservation:
    return CoreTeacherContractObservation(False, frozenset(), False, False)


def _inventoried(status: ApplicationLaunchStatus) -> ApplicationInventory:
    observation = ApplicationObservation(
        component_id="scoreform",
        display_name="ScoreForm",
        purpose="Synthetic answer-sheet workflow",
        distribution="scoreform",
        qualified_version="historical only",
        installed_version="synthetic",
        console_script_name="scoreform",
        console_script_target="scoreform.cli:main",
        status=status,
        reason="private/teacher/path\x1b[31m",
        remediation="private/teacher/path\x1b[31m",
        launcher_path=(
            Path("/synthetic/scoreform")
            if status is ApplicationLaunchStatus.AVAILABLE else None
        ),
    )
    return ApplicationInventory((observation,))


def _drive(
    choices: str, inventory: ApplicationInventory,
    *, launch_return: int = 0,
) -> tuple[str, list[str]]:
    output = TTY()
    launches: list[str] = []

    def launcher(component: str) -> int:
        launches.append(component)
        return launch_return

    exit_code = run_teacher_home(
        input_stream=TTY(choices),
        output=output,
        collect_inventory=lambda: inventory,
        launch=launcher,
        doctor=lambda: 0,
        show_help=lambda: output.write("usage: pds\n"),
        recent=lambda: (),
        observe_contract=_legacy,
    )
    assert exit_code == 0
    return output.getvalue(), launches


def test_automated_teacher_journey_covers_owner_boundaries() -> None:
    scenario = witness.source_journey()
    assert scenario["status"] == "passed"
    assert scenario["approved_application_count"] == 6
    assert scenario["synthetic_launch_count"] == 2
    assert scenario["actual_producer_launches"] == 0
    assert scenario["notes_writes"] == 0
    assert not scenario["real_terminal_vt_qualified"]


@pytest.mark.parametrize(
    "status",
    [
        ApplicationLaunchStatus.NOT_INSTALLED,
        ApplicationLaunchStatus.INCOMPATIBLE,
        ApplicationLaunchStatus.UNAVAILABLE,
    ],
)
def test_unavailable_module_does_not_leak_metadata_or_launch(
    status: ApplicationLaunchStatus,
) -> None:
    output, launched = _drive("1\nm\nq\n", _inventoried(status))
    assert launched == []
    assert "ScoreForm cannot be launched" in output
    assert "private/teacher/path" not in output
    assert "\x1b" not in output
    assert "Paper Data Suite\nTeacher Home\n" in output


def test_app_failure_is_reported_and_does_not_interrupt_menu() -> None:
    output, launched = _drive(
        "1\nm\nq\n", _inventoried(ApplicationLaunchStatus.AVAILABLE),
        launch_return=1,
    )
    assert launched == ["scoreform"]
    assert "did not complete successfully" in output
    assert output.count("Paper Data Suite\nTeacher Home\n") >= 3
    assert "Leaving Paper Data Suite." in output


def test_precontract_fallback_keeps_disabled_notes_and_no_ansi() -> None:
    output, launched = _drive(
        ":notes\n8\nb\nq\n", _inventoried(ApplicationLaunchStatus.AVAILABLE)
    )
    assert launched == []
    assert "Choose a listed number" in output
    assert "Recognizing :notes is not a Notes service" in output
    assert "\x1b" not in output


def test_broken_claimed_core_header_does_not_block_unrelated_help() -> None:
    output = TTY()
    def broken() -> CoreTeacherContractObservation:
        raise CoreTeacherContractError("C:/private/not-for-screen")

    exit_code = run_teacher_home(
        input_stream=TTY("12\n2\nq\n"), output=output,
        collect_inventory=lambda: _inventoried(ApplicationLaunchStatus.AVAILABLE),
        launch=lambda _: pytest.fail("unexpected launch"),
        doctor=lambda: pytest.fail("unexpected doctor"),
        show_help=lambda: output.write("usage: pds\n"),
        recent=lambda: pytest.fail("unexpected settings read"),
        observe_contract=broken,
    )
    assert exit_code == 0
    text = output.getvalue()
    assert "teacher-header interface is incompatible" in text
    assert "C:/private" not in text
    assert "usage: pds" in text


def test_cli_real_home_controller_with_injected_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.teacher_home as home

    stdin = TTY("h\nb\nq\n")
    stdout = TTY()
    original = home.run_teacher_home

    def injected_home(**kwargs: object) -> int:
        return original(
            input_stream=stdin,
            output=stdout,
            collect_inventory=lambda: _inventoried(
                ApplicationLaunchStatus.NOT_INSTALLED
            ),
            launch=lambda _: pytest.fail("producer must not run"),
            doctor=lambda: pytest.fail("doctor must be opt-in"),
            show_help=lambda: stdout.write("usage: pds\n"),
            recent=lambda: pytest.fail("settings must not load"),
            observe_contract=_legacy,
        )

    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(home, "run_teacher_home", injected_home)
    assert cli.main(()) == 0
    rendered = stdout.getvalue()
    assert "Teacher Home Help" in rendered
    assert rendered.count("Paper Data Suite\nTeacher Home\n") >= 2
    assert "Leaving Paper Data Suite." in rendered


def test_noninteractive_no_args_never_enters_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.teacher_home as home

    def forbidden_home(**_kwargs: object) -> int:
        pytest.fail("noninteractive no-args invocation opened Teacher Home")

    stdout = StringIO()
    monkeypatch.setattr(cli.sys, "stdin", StringIO("1\n"))
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(home, "run_teacher_home", forbidden_home)
    assert cli.main(()) == 0
    assert "usage: pds" in stdout.getvalue()


def test_witness_refuses_wrong_suite_parent_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(_repo: Path) -> str:
        raise ValueError("Source acceptance requires Slice 3 as an ancestor")

    monkeypatch.setattr(witness, "_verified_source_revision", refuse)
    monkeypatch.setattr(
        "sys.argv",
        [
            "issue52_teacher_home_source_acceptance.py",
            "--suite-root", str(tmp_path),
            "--output", str(tmp_path / "evidence.json"),
        ],
    )
    with pytest.raises(ValueError, match="Slice 3 as an ancestor"):
        witness.main()
    assert not (tmp_path / "evidence.json").exists()


def test_witness_only_writes_non_sensitive_synthetic_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    evidence = tmp_path / "results" / "teacher-home.json"
    monkeypatch.setattr(
        witness, "_verified_source_revision", lambda _: witness.PARENT_SUITE_SHA
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "issue52_teacher_home_source_acceptance.py",
            "--suite-root", str(tmp_path),
            "--output", str(evidence),
        ],
    )
    assert witness.main() == 0
    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["stage"] == "Slice 4 / D1 source synthetic"
    assert report["official_core_v1_header_d2_d3"] == "PENDING"
    assert report["scenario"]["status"] == "passed"
    assert str(tmp_path) not in evidence.read_text(encoding="utf-8")
