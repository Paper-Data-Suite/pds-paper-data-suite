"""Read-only observation of installed Core teacher-interface capabilities.

This is a narrow handoff for Suite #52, not a new menu/Notes adapter.
Only the two implemented Core #237 primitives are inspected; other tokens
are reported but never used as permission to call a shared service.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType

_CONTRACT_MODULE = "pds_core.teacher_experience"
_HEADER_TOKEN = "terminal.header.v1"
_COMMAND_TOKEN = "terminal.notes_command.v1"
_MAX_CAPABILITIES = 64


class CoreTeacherContractError(RuntimeError):
    """Installed Core claims an unusable or inconsistent teacher interface."""


@dataclass(frozen=True, slots=True)
class CoreTeacherContractObservation:
    """Implemented primitive availability, not menu or release qualification."""

    contract_present: bool
    advertised_capabilities: frozenset[str]
    header_available: bool
    notes_recognizer_available: bool


def _required_module(
    name: str, importer: Callable[[str], ModuleType]
) -> ModuleType:
    try:
        return importer(name)
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        # A claimed symbol is broken, not an optional missing feature.
        raise CoreTeacherContractError(
            f"Installed Core teacher interface is incompatible: {name}."
        ) from error


def observe_core_teacher_contract(
    *, importer: Callable[[str], ModuleType] = import_module
) -> CoreTeacherContractObservation:
    """Inspect the two implemented v1 primitives without invoking menus.

    Absence of the teacher_experience module itself means pre-contract Core.
    A nested missing import or a broken claimed API fails explicitly. Do not
    call this to establish wheel authenticity, Notes access or teacher identity.
    """
    try:
        contract = importer(_CONTRACT_MODULE)
    except ModuleNotFoundError as error:
        if error.name == _CONTRACT_MODULE:
            return CoreTeacherContractObservation(
                contract_present=False,
                advertised_capabilities=frozenset(),
                header_available=False,
                notes_recognizer_available=False,
            )
        raise CoreTeacherContractError(
            "Installed Core teacher interface has a missing dependency."
        ) from error
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        raise CoreTeacherContractError(
            "Installed Core teacher interface could not be imported."
        ) from error

    if getattr(contract, "TEACHER_EXPERIENCE_CONTRACT_VERSION", None) != "1":
        raise CoreTeacherContractError(
            "Installed Core teacher interface has unsupported contract version."
        )
    declaration = getattr(contract, "get_teacher_experience_capabilities", None)
    if not callable(declaration):
        raise CoreTeacherContractError(
            "Installed Core teacher interface lacks capability declaration."
        )
    try:
        advertised = declaration()
    except Exception as error:
        raise CoreTeacherContractError(
            "Installed Core teacher capability inquiry failed."
        ) from error
    if (
        type(advertised) is not frozenset
        or len(advertised) > _MAX_CAPABILITIES
        or any(type(item) is not str or not item for item in advertised)
    ):
        raise CoreTeacherContractError(
            "Installed Core teacher capability declaration is malformed."
        )

    if _HEADER_TOKEN in advertised:
        ui = _required_module("pds_core.teacher_ui", importer)
        if not (
            isinstance(getattr(ui, "TeacherScreenHeader", None), type)
            and callable(getattr(ui, "render_teacher_header", None))
            and callable(getattr(ui, "print_teacher_header", None))
        ):
            raise CoreTeacherContractError(
                "Installed Core advertises a broken teacher-header API."
            )
    if _COMMAND_TOKEN in advertised:
        commands = _required_module("pds_core.teacher_commands", importer)
        if not (
            isinstance(getattr(commands, "PromptKind", None), type)
            and isinstance(getattr(commands, "SharedTeacherCommand", None), type)
            and callable(getattr(commands, "parse_shared_teacher_command", None))
        ):
            raise CoreTeacherContractError(
                "Installed Core advertises a broken shared-command API."
            )
    return CoreTeacherContractObservation(
        contract_present=True,
        advertised_capabilities=advertised,
        header_available=_HEADER_TOKEN in advertised,
        notes_recognizer_available=_COMMAND_TOKEN in advertised,
    )
