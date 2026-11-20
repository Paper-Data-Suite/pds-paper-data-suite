"""#19G1: contracted installed Home harness; native gate remains opt-in."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from scripts import issue19_g1_installed_teacher_home_rehearsal as home


def test_all_four_teacher_journeys_bind_separate_consents(tmp_path: Path) -> None:
    root = tmp_path / "suite18_synthetic_workspace"
    wheels = tmp_path / "official_wheels"
    cases = {
        case: home._transcript(root, decision=case, wheelhouse=wheels)
        for case in ("cancel_first", "retain_only", "cancel_second", "dispatch")
    }
    for transcript in cases.values():
        lines = transcript.splitlines()
        assert lines[:7] == ["9", "2", str(root), "1", "1,2", "P", "R"]
        # Exactly one inbox entry-selection and one TWO-PAGE selection.
        # An extra "1" here silently selects only the first physical page.
        assert lines[3:7] == ["1", "1,2", "P", "R"]
        assert "*" not in lines and "" not in lines
        assert lines[-1] == "Q"
        assert lines.count("R") == 1
        assert lines.count("D") <= 1
    assert "RETAIN" not in cases["cancel_first"]
    assert "D" not in cases["retain_only"].splitlines()
    assert "DISPATCH" not in cases["cancel_second"]
    assert cases["dispatch"].count("RETAIN") == 1
    assert cases["dispatch"].count("DISPATCH") == 1
    # Q must be issued at Teacher Home after explicit Back navigation.
    # Quitting inside the papers submenu skips the Home farewell message.
    assert cases["cancel_first"].splitlines()[-3:] == ["CANCEL", "B", "Q"]
    assert cases["retain_only"].splitlines()[-4:] == ["V", "B", "B", "Q"]
    assert cases["cancel_second"].splitlines()[-4:] == [
        "CANCEL", "B", "B", "Q",
    ]
    assert cases["dispatch"].splitlines()[-3:] == ["DISPATCH", "B", "Q"]
    with pytest.raises(home.HomeAcceptanceRefused):
        home._transcript(root, decision="inferred_approve", wheelhouse=wheels)


def test_physical_page_choice_is_consumed_before_plan_review(tmp_path: Path) -> None:
    """The inbox prompts: entry number, page numbers, plan, then retention."""
    root = tmp_path / "suite18_synthetic_workspace"
    wheels = tmp_path / "official_wheels"
    for decision in ("cancel_first", "retain_only", "cancel_second", "dispatch"):
        commands = home._transcript(root, decision=decision, wheelhouse=wheels)
        lines = commands.splitlines()
        assert lines[3] == "1"  # Exactly one selected inbox entry
        assert lines[4] == "1,2"  # Both physical pages in that entry
        assert lines[5:7] == ["P", "R"]  # Only after page selection
        assert lines.count("1,2") == 1
        assert lines[:7].count("1") == 1


def test_two_prepared_pages_are_required_in_acceptance_source() -> None:
    source = Path(home.__file__).read_text(encoding="utf-8")
    assert '"Prepared typed Core requests: 2" in display' in source
    assert '"Stage: 2 Core-retained page request(s) prepared" in display' in source
    assert '"Core attempted physical pages: 2" in display' in source


def test_invalid_parent_or_wheelhouse_fails_before_any_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []
    monkeypatch.setattr(
        home, "_run_case", lambda *_args: observed.append("ran")
    )
    assert home.main([
        "--synthetic-parent", str(tmp_path),
        "--wheelhouse", "relative_wheels",
    ]) == 2
    assert not observed


def test_main_sequence_only_reports_pass_after_all_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    seen: list[str] = []

    def scenario(_: Path, __: Path, name: str) -> None:
        seen.append(name)

    monkeypatch.setattr(home, "_run_case", scenario)
    assert home.main([
        "--synthetic-parent", str(tmp_path),
        "--wheelhouse", str(wheels),
    ]) == 0
    assert seen == ["cancel_first", "retain_only", "cancel_second", "dispatch"]
    assert "SUITE19_G1_INSTALLED_TEACHER_HOME_ACCEPTANCE_PASSED" in (
        capsys.readouterr().out
    )


def test_failed_native_scenario_does_not_print_success_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheels = tmp_path / "wheels"
    wheels.mkdir()

    def failed(_: Path, __: Path, name: str) -> None:
        if name == "retain_only":
            raise RuntimeError("PRIVATE PDS2| teacher path")

    monkeypatch.setattr(home, "_run_case", failed)
    assert home.main([
        "--synthetic-parent", str(tmp_path),
        "--wheelhouse", str(wheels),
    ]) == 2
    captured = capsys.readouterr()
    assert "PRIVATE" not in captured.err
    assert "PDS2|" not in captured.err
    assert "ACCEPTANCE_PASSED" not in captured.out


def test_real_cli_adapter_never_returns_fake_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import cli

    monkeypatch.setattr(cli, "main", lambda _: 2)
    previous = sys.stdin, sys.stdout
    with pytest.raises(home.HomeAcceptanceRefused):
        home._drive_installed_cli("9\nq\n")
    assert (sys.stdin, sys.stdout) == previous


def test_cli_adapter_rejects_private_qr_and_restores_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import cli

    def fake(_: object) -> int:
        assert isinstance(sys.stdin, io.StringIO)
        sys.stdout.write(
            "Paper Data Suite Teacher Home\nProcess Returned Papers\n"
            "PDS2|PRIVATE\nLeaving Paper Data Suite.\n"
        )
        return 0

    monkeypatch.setattr(cli, "main", fake)
    old = sys.stdin, sys.stdout
    with pytest.raises(home.HomeAcceptanceRefused):
        home._drive_installed_cli("9\nq\n")
    assert (sys.stdin, sys.stdout) == old


def test_e3a_opt_in_integration_does_not_change_default() -> None:
    script = Path("scripts/issue19_e3a_windows_installed_acceptance.ps1")
    value = script.read_text(encoding="utf-8")
    assert "[switch]$IncludeTeacherHome" in value
    assert "if ($IncludeTeacherHome.IsPresent)" in value
    assert "issue19_g1_installed_teacher_home_rehearsal.py" in value
    assert "Assert-Exit 'G1 actual installed Teacher Home native journey'" in value
    assert "SUITE19_G1_ACTUAL_INSTALLED_HOME_VERIFIED" in value
    assert "SUITE19_E3A_SYNTHETIC_INSTALLED_ACCEPTANCE_PASSED" in value


def test_native_refusal_reports_scenario_with_allowlisted_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheels = tmp_path / "wheels"
    wheels.mkdir()

    def fail(_parent: Path, _wheels: Path, scenario: str) -> None:
        assert scenario == "cancel_first"
        raise home.HomeAcceptanceRefused(
            "installed interactive Home not completed"
        )

    monkeypatch.setattr(home, "_run_case", fail)
    assert home.main([
        "--synthetic-parent", str(tmp_path),
        "--wheelhouse", str(wheels),
    ]) == 2
    reported = capsys.readouterr()
    assert "SUITE19_G1_HOME_CANCEL_FIRST_STARTED" in reported.out
    assert "SUITE19_G1_HOME_FAILED_SCENARIO=cancel_first" in reported.err
    assert "SUITE19_G1_HOME_FAILURE_CODE=home_exit" in reported.err
    assert "ACCEPTANCE_PASSED" not in reported.out


def test_unknown_failure_does_not_echo_sensitive_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheels = tmp_path / "wheels"
    wheels.mkdir()

    def fail(_parent: Path, _wheels: Path, _scenario: str) -> None:
        raise home.HomeAcceptanceRefused("SENSITIVE PDS2| C:/private/student")

    monkeypatch.setattr(home, "_run_case", fail)
    assert home.main([
        "--synthetic-parent", str(tmp_path),
        "--wheelhouse", str(wheels),
    ]) == 2
    reported = capsys.readouterr()
    assert "SUITE19_G1_HOME_FAILURE_CODE=unclassified" in reported.err
    assert "SENSITIVE" not in reported.err
    assert "PDS2|" not in reported.err
    assert "private/student" not in reported.err
    assert "ACCEPTANCE_PASSED" not in reported.out
