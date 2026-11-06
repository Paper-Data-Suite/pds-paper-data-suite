"""Suite #51: contract availability is not service or release qualification."""

from __future__ import annotations

from importlib import import_module
from io import StringIO
from types import ModuleType
from typing import Callable

import pytest

from paper_data_suite import cli
from paper_data_suite.teacher_experience_contracts import (
    CoreTeacherContractError,
    CoreTeacherContractObservation,
    observe_core_teacher_contract,
)


def _module(name: str, **names: object) -> ModuleType:
    module = ModuleType(name)
    for key, value in names.items():
        setattr(module, key, value)
    return module


def _importer(
    tokens: frozenset[str], *, missing: str | None = None
) -> tuple[Callable[[str], ModuleType], list[str]]:
    modules = {
        "pds_core.teacher_experience": _module(
            "pds_core.teacher_experience",
            TEACHER_EXPERIENCE_CONTRACT_VERSION="1",
            get_teacher_experience_capabilities=lambda: tokens,
        ),
        "pds_core.teacher_ui": _module(
            "pds_core.teacher_ui",
            TeacherScreenHeader=type("TeacherScreenHeader", (), {}),
            render_teacher_header=lambda *a, **kw: "header",
            print_teacher_header=lambda *a, **kw: None,
        ),
        "pds_core.teacher_commands": _module(
            "pds_core.teacher_commands",
            PromptKind=type("PromptKind", (), {}),
            SharedTeacherCommand=type("SharedTeacherCommand", (), {}),
            parse_shared_teacher_command=lambda *a, **kw: None,
        ),
    }
    requested: list[str] = []

    def load(name: str) -> ModuleType:
        requested.append(name)
        if name == missing:
            error = ModuleNotFoundError(f"No module named {name}")
            error.name = name
            raise error
        return modules[name]

    return load, requested


def test_precontract_core_is_a_read_only_unavailable_state() -> None:
    load, requested = _importer(frozenset(), missing="pds_core.teacher_experience")
    result = observe_core_teacher_contract(importer=load)
    assert result == CoreTeacherContractObservation(
        contract_present=False,
        advertised_capabilities=frozenset(),
        header_available=False,
        notes_recognizer_available=False,
    )
    assert requested == ["pds_core.teacher_experience"]


def test_nested_import_failure_is_not_misreported_as_precontract() -> None:
    def broken(name: str) -> ModuleType:
        error = ModuleNotFoundError("Nested import missing")
        error.name = "some_nested_dependency"
        raise error

    with pytest.raises(CoreTeacherContractError, match="missing dependency"):
        observe_core_teacher_contract(importer=broken)


def test_only_implemented_primitive_tokens_are_probed() -> None:
    tokens = frozenset(
        {
            "terminal.header.v1",
            "terminal.notes_command.v1",
            "notes.records.v1",
            "notes.menu.v1",
            "classroom.menu.v1",
            "notes.portability.v1",
        }
    )
    load, requested = _importer(tokens)
    result = observe_core_teacher_contract(importer=load)
    assert result.contract_present
    assert result.advertised_capabilities == tokens
    assert result.header_available and result.notes_recognizer_available
    assert requested == [
        "pds_core.teacher_experience",
        "pds_core.teacher_ui",
        "pds_core.teacher_commands",
    ]
    # Neither Notes services nor classroom/roster menus are imported or run.


def test_header_without_notes_does_not_probe_shared_command() -> None:
    load, requested = _importer(frozenset({"terminal.header.v1"}))
    result = observe_core_teacher_contract(importer=load)
    assert result.header_available
    assert not result.notes_recognizer_available
    assert "pds_core.teacher_commands" not in requested


def test_broken_claimed_header_refused() -> None:
    load, _ = _importer(frozenset({"terminal.header.v1"}))

    def broken(name: str) -> ModuleType:
        if name == "pds_core.teacher_ui":
            return _module(name, TeacherScreenHeader=object)
        return load(name)

    with pytest.raises(CoreTeacherContractError, match="broken teacher-header"):
        observe_core_teacher_contract(importer=broken)


def test_broken_claimed_command_refused() -> None:
    load, _ = _importer(frozenset({"terminal.notes_command.v1"}))

    def broken(name: str) -> ModuleType:
        if name == "pds_core.teacher_commands":
            return _module(name, PromptKind=object)
        return load(name)

    with pytest.raises(CoreTeacherContractError, match="broken shared-command"):
        observe_core_teacher_contract(importer=broken)


@pytest.mark.parametrize("invalid", [[], {"terminal.header.v1"}, frozenset({1})])
def test_malformed_capabilities_are_not_accepted(invalid: object) -> None:
    load, _ = _importer(frozenset())

    def malformed(name: str) -> ModuleType:
        if name == "pds_core.teacher_experience":
            return _module(
                name,
                TEACHER_EXPERIENCE_CONTRACT_VERSION="1",
                get_teacher_experience_capabilities=lambda: invalid,
            )
        return load(name)

    with pytest.raises(CoreTeacherContractError, match="malformed"):
        observe_core_teacher_contract(importer=malformed)


def test_unknown_contract_version_is_rejected_not_silently_absent() -> None:
    def unsupported(name: str) -> ModuleType:
        return _module(name, TEACHER_EXPERIENCE_CONTRACT_VERSION="2")

    with pytest.raises(CoreTeacherContractError, match="unsupported"):
        observe_core_teacher_contract(importer=unsupported)


def test_legacy_explicit_cli_still_works_with_no_shared_menu(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(()) == 0
    assert "usage: pds" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main(("--help",))
    assert exc.value.code == 0


def test_actual_installed_core_is_either_precontract_or_valid_v1() -> None:
    result = observe_core_teacher_contract()
    assert isinstance(result, CoreTeacherContractObservation)
    if result.contract_present:
        assert isinstance(result.advertised_capabilities, frozenset)
    else:
        assert not result.header_available
        assert not result.notes_recognizer_available


def test_no_implicit_output_or_notes_write_for_capability_inspection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    load, _ = _importer(frozenset({"terminal.notes_command.v1"}))
    output = StringIO()
    assert output.getvalue() == ""
    observe_core_teacher_contract(importer=load)
    assert output.getvalue() == ""
    assert capsys.readouterr() == ("", "")


def test_installed_core_header_vectors_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = observe_core_teacher_contract()
    if not observed.header_available:
        pytest.skip("installed Core has no qualified header primitive")
    ui = import_module("pds_core.teacher_ui")
    header = ui.TeacherScreenHeader("Paper Data Suite", "Home")
    assert ui.render_teacher_header(header) == "Paper Data Suite\nHome"
    output = StringIO()
    monkeypatch.setenv("NO_COLOR", "1")
    ui.print_teacher_header(header, output=output, color="auto")
    assert output.getvalue() == "Paper Data Suite\nHome\n"
    with pytest.raises(ValueError):
        ui.TeacherScreenHeader("Paper Data Suite\x1b[0m", "Home")


def test_installed_core_parser_vectors_when_available() -> None:
    observed = observe_core_teacher_contract()
    if not observed.notes_recognizer_available:
        pytest.skip("installed Core has no qualified prompt recognizer")
    commands = import_module("pds_core.teacher_commands")
    parse = commands.parse_shared_teacher_command
    kind = commands.PromptKind
    recognized = commands.SharedTeacherCommand.NOTES
    assert parse(
        " :NoTeS ", prompt_kind=kind.MENU_CHOICE,
        interactive=True, allow_notes=True,
    ) is recognized
    for value in ("N", "W", "B", "M", "Q", "H", "1", ":note", ":notes more"):
        assert parse(
            value, prompt_kind=kind.MENU_CHOICE,
            interactive=True, allow_notes=True,
        ) is None
    for prompt_kind in (kind.DATA_ENTRY, kind.CONFIRMATION, kind.PAUSE):
        assert parse(
            ":notes", prompt_kind=prompt_kind,
            interactive=True, allow_notes=True,
        ) is None
    assert parse(
        ":notes", prompt_kind=kind.MENU_CHOICE,
        interactive=False, allow_notes=True,
    ) is None
    assert parse(
        ":notes", prompt_kind=kind.MENU_CHOICE,
        interactive=True, allow_notes=False,
    ) is None
