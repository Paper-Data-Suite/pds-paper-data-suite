"""Suite #52 Slice 1: interactive entry, truthful menu, and guarded actions."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Callable

import pytest

from paper_data_suite import cli
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationInventoryError,
    ApplicationLaunchStatus,
    ApplicationObservation,
)
from paper_data_suite.teacher_experience_contracts import (
    CoreTeacherContractError,
    CoreTeacherContractObservation,
)
from paper_data_suite.teacher_home import (
    build_home_applications,
    is_interactive_terminal,
    run_teacher_home,
)


class FakeTerminal(StringIO):
    def isatty(self) -> bool:
        return True


def _observation(component_id: str, *, available: bool) -> ApplicationObservation:
    return ApplicationObservation(
        component_id=component_id,
        display_name=component_id.title(),
        purpose="Teacher workflow",
        distribution=f"pds-{component_id}",
        qualified_version="historical only",
        installed_version="9.9" if available else None,
        console_script_name=component_id,
        console_script_target="test:main",
        status=(
            ApplicationLaunchStatus.AVAILABLE
            if available
            else ApplicationLaunchStatus.NOT_INSTALLED
        ),
        reason="local metadata; not official provenance",
        launcher_path=Path(f"/synthetic/{component_id}") if available else None,
    )


def _inventory() -> ApplicationInventory:
    return ApplicationInventory(
        (
            _observation("scoreform", available=True),
            _observation("quillan", available=False),
            _observation("concord", available=True),
            _observation("meridian", available=False),
            _observation("vitrine", available=False),
            _observation("portia", available=True),
        )
    )


def _precontract() -> CoreTeacherContractObservation:
    return CoreTeacherContractObservation(False, frozenset(), False, False)


def _run(
    choices: str,
    *,
    inventory: Callable[[], ApplicationInventory] = _inventory,
    launcher: Callable[[str], int] | None = None,
    doctor: Callable[[], int] | None = None,
    recent: Callable[[], tuple[str, ...]] = lambda: (),
    probe: Callable[[], CoreTeacherContractObservation] = _precontract,
    importer: Callable[[str], object] = lambda name: None,
) -> tuple[int, str]:
    output = FakeTerminal()
    exit_code = run_teacher_home(
        input_stream=FakeTerminal(choices),
        output=output,
        collect_inventory=inventory,
        launch=launcher or (lambda component: 0),
        doctor=doctor or (lambda: 0),
        show_help=lambda: output.write("usage: pds\n"),
        recent=recent,
        observe_contract=probe,
        core_importer=importer,
    )
    return exit_code, output.getvalue()


def test_tty_gate_checks_both_streams() -> None:
    assert is_interactive_terminal(
        input_stream=FakeTerminal(), output=FakeTerminal()
    )
    assert not is_interactive_terminal(
        input_stream=StringIO(), output=FakeTerminal()
    )
    assert not is_interactive_terminal(
        input_stream=FakeTerminal(), output=StringIO()
    )


def test_cli_no_args_noninteractive_still_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(()) == 0
    assert "usage: pds" in capsys.readouterr().out


def test_cli_no_args_interactive_dispatches_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_in = FakeTerminal("q\n")
    terminal_out = FakeTerminal()
    monkeypatch.setattr(cli.sys, "stdin", terminal_in)
    monkeypatch.setattr(cli.sys, "stdout", terminal_out)
    import paper_data_suite.teacher_home as home

    def synthetic_home(**kwargs: object) -> int:
        assert kwargs["input_stream"] is terminal_in
        assert kwargs["output"] is terminal_out
        terminal_out.write("Paper Data Suite\nTeacher Home\n")
        return 0

    monkeypatch.setattr(home, "run_teacher_home", synthetic_home)
    assert cli.main(()) == 0
    assert "Paper Data Suite\nTeacher Home" in terminal_out.getvalue()


def test_home_shows_exact_six_approved_apps_and_accurate_status() -> None:
    applications = build_home_applications(_inventory())
    assert [app.component_id for app in applications] == [
        "scoreform", "quillan", "concord", "meridian", "vitrine", "portia"
    ]
    assert applications[0].selectable
    assert not applications[1].selectable
    assert applications[1].status == "not installed"
    assert all(app.component_id != "core" for app in applications)
    code, text = _run("q\n")
    assert code == 0
    assert "Notes & Tasks — not yet available" in text
    assert "Attention Needed — not yet available" in text
    assert "Recent Applications" in text


def test_available_application_launches_via_injected_existing_path() -> None:
    launched: list[str] = []

    def launch(component_id: str) -> int:
        launched.append(component_id)
        return 0

    code, text = _run("1\nq\n", launcher=launch)
    assert code == 0
    assert launched == ["scoreform"]
    assert "Returned from ScoreForm" in text
    assert text.count("Teacher Home") >= 2


def test_unavailable_application_refuses_without_invoking_launcher() -> None:
    called: list[str] = []
    code, text = _run("2\nq\n", launcher=lambda cid: called.append(cid) or 0)
    assert code == 0
    assert called == []
    assert "cannot be launched (not installed)" in text


def test_nonzero_launch_recovers_and_other_apps_remain_usable() -> None:
    seen: list[str] = []

    def launch(component_id: str) -> int:
        seen.append(component_id)
        return 1 if component_id == "scoreform" else 0

    code, text = _run("1\n3\nq\n", launcher=launch)
    assert code == 0
    assert seen == ["scoreform", "concord"]
    assert "did not complete successfully" in text
    assert "Returned from Concord" in text


def test_missing_launcher_path_never_becomes_selectable() -> None:
    broken = replace(_observation("scoreform", available=True), launcher_path=None)
    inventory = ApplicationInventory((broken,))
    apps = build_home_applications(inventory)
    assert not apps[0].selectable


def test_planned_views_do_not_open_notes_or_provider_callbacks() -> None:
    touched: list[str] = []
    code, text = _run(
        "7\nb\n8\nm\n9\nb\n10\nm\nq\n",
        launcher=lambda component: touched.append(component) or 0,
    )
    assert code == 0
    assert touched == []
    assert "Core #238-#240" in text
    assert "no note was opened or saved" in text
    assert "not evidence of zero attention" in text


def test_home_and_help_navigation_and_eof() -> None:
    code, text = _run("b\nh\nb\nm\nwrong\nq\n")
    assert code == 0
    assert "Already at Teacher Home" in text
    assert "Teacher Home Help" in text
    assert "Choose a listed number" in text
    assert _run("")[0] == 0
    assert _run("h\n")[0] == 0


def test_recent_applications_are_labelled_and_rechecked_at_launch() -> None:
    seen: list[str] = []
    code, text = _run(
        "11\n2\nq\n",
        recent=lambda: ("quillan", "scoreform"),
        launcher=lambda cid: seen.append(cid) or 0,
    )
    assert code == 0
    assert "not a list of recent work items" in text
    assert "Quillan — not installed" in text
    assert seen == ["scoreform"]


def test_recent_unavailable_not_conflated_with_empty_records() -> None:
    def broken() -> tuple[str, ...]:
        from paper_data_suite.settings import SuiteSettingsReadError

        raise SuiteSettingsReadError("private path in error")

    code, text = _run("11\nb\nq\n", recent=broken)
    assert code == 0
    assert "could not be read" in text
    assert "private path" not in text


def test_diagnostics_is_opt_in_and_does_not_exit_shell() -> None:
    calls: list[str] = []

    def doctor() -> int:
        calls.append("doctor")
        return 1

    code, text = _run("12\n1\n12\n2\nq\n", doctor=doctor)
    assert code == 0
    assert calls == ["doctor"]
    assert "Doctor completed (status 1)" in text
    assert "usage: pds" in text


def test_interrupted_doctor_recovers_to_home() -> None:
    def interrupted() -> int:
        raise KeyboardInterrupt

    code, text = _run("12\n1\nq\n", doctor=interrupted)
    assert code == 0
    assert "Doctor interrupted; returning to Teacher Home" in text


def test_broken_advertised_core_header_has_visible_safe_fallback() -> None:
    def failed() -> CoreTeacherContractObservation:
        raise CoreTeacherContractError("private inner path")

    code, text = _run("q\n", probe=failed)
    assert code == 0
    assert "teacher-header interface is incompatible" in text
    assert "private inner path" not in text
    assert "Paper Data Suite\nTeacher Home" in text


def test_v1_header_uses_public_core_printer_with_color_auto() -> None:
    calls: list[tuple[str, str]] = []

    class Header:
        def __init__(
            self, *, application_name: str, screen_title: str
        ) -> None:
            calls.append((application_name, screen_title))
            self.screen_title = screen_title

    class Ui:
        TeacherScreenHeader = Header

        @staticmethod
        def print_teacher_header(
            header: Header, *, output: StringIO, color: str
        ) -> None:
            assert color == "auto"
            output.write("CORE_HEADER " + header.screen_title + "\n")

    code, text = _run(
        "q\n",
        probe=lambda: CoreTeacherContractObservation(
            True, frozenset({"terminal.header.v1"}), True, False
        ),
        importer=lambda name: Ui,
    )
    assert code == 0
    assert calls == [("Paper Data Suite", "Teacher Home")]
    assert "CORE_HEADER Teacher Home" in text


def test_inventory_error_does_not_disable_help_or_block_for_input() -> None:
    def failed() -> ApplicationInventory:
        raise ApplicationInventoryError("private installed path")

    code, text = _run("12\n2\nq\n", inventory=failed)
    assert code == 0
    assert "ScoreForm — unavailable" in text
    assert "usage: pds" in text
    assert "private installed path" not in text


def test_colon_notes_is_not_intercepted_without_a_handler() -> None:
    code, text = _run(":notes\nq\n")
    assert code == 0
    assert "Choose a listed number" in text
    assert "Notes & Tasks — not yet available" in text
