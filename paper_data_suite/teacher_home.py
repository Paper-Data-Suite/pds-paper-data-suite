"""Interactive, read-only-first teacher home for the Suite terminal shell.

The home displays approved local launch eligibility without loading producer
providers, workspaces, Notes or student records. Foreground launches delegate to
Suite's existing ``pds launch`` policy function, supplied by the CLI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import TextIO

from paper_data_suite.application_launching import (
    ApplicationLaunchExecutionError,
    ApplicationLaunchRefusedError,
)
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationInventoryError,
    ApplicationLaunchStatus,
    ApplicationObservation,
)
from paper_data_suite.evergreen_local_application_inventory import (
    collect_local_launch_inventory,
)
from paper_data_suite.evergreen_local_compatibility import LocalInspectionError
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.settings import SuiteSettingsError, load_suite_settings
from paper_data_suite.teacher_experience_contracts import (
    CoreTeacherContractError,
    CoreTeacherContractObservation,
    observe_core_teacher_contract,
)


@dataclass(frozen=True, slots=True)
class HomeApplication:
    """One ordered, approved application; never an alternate launch authority."""

    component_id: str
    display_name: str
    purpose: str
    status: str
    selectable: bool
    unavailable_reason: str
    remediation: str


_WORKFLOWS: tuple[tuple[str, str, str], ...] = (
    (
        "Workspace & Classroom Management",
        "A callable classroom administration menu is not yet qualified. "
        "Core #241-#242 and Suite #53 own that integration.",
        "Existing standalone commands: pds workspace and pds setup.",
    ),
    (
        "Notes & Tasks",
        "Private Notes records and a callable Notes menu are not qualified. "
        "Core #238-#240 and Suite #54 own this integration.",
        "Recognizing :notes is not a Notes service; no note was opened or saved.",
    ),
    (
        "Process Returned Papers",
        "Unified paper intake and routing are not yet available here. "
        "Suite #17-#19 own this workflow.",
        "Use an application through its own supported menu instead.",
    ),
    (
        "Attention Needed",
        "A real evaluated cross-module attention view is not yet qualified. "
        "Suite #20-#23 own this workflow.",
        "An available application or valid provider is not evidence of zero attention.",
    ),
)


class _Header:
    """Per-session Core v1 header adapter with honest pre-contract fallback."""

    def __init__(
        self,
        *,
        probe: Callable[[], CoreTeacherContractObservation],
        importer: Callable[[str], object],
    ) -> None:
        self._ui: object | None = None
        self.notice: str | None = None
        try:
            observation = probe()
            if observation.header_available:
                self._ui = importer("pds_core.teacher_ui")
        except (CoreTeacherContractError, ImportError, AttributeError, TypeError):
            self.notice = (
                "Core teacher-header interface is incompatible; using plain text. "
                "Run pds doctor for diagnostics."
            )

    def print(self, title: str, *, output: TextIO) -> None:
        if self._ui is not None:
            try:
                header_type = getattr(self._ui, "TeacherScreenHeader")
                printer = getattr(self._ui, "print_teacher_header")
                header = header_type(
                    application_name="Paper Data Suite", screen_title=title
                )
                printer(header, output=output, color="auto")
                return
            except (
                AttributeError,
                ImportError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                self._ui = None
                self.notice = (
                    "Core teacher-header rendering failed; using plain text. "
                    "Run pds doctor for diagnostics."
                )
        output.write(f"Paper Data Suite\n{title}\n")


def is_interactive_terminal(*, input_stream: TextIO, output: TextIO) -> bool:
    """Require both actual terminal input and terminal output before prompting."""
    try:
        return bool(input_stream.isatty()) and bool(output.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _status_label(status: ApplicationLaunchStatus) -> str:
    return {
        ApplicationLaunchStatus.AVAILABLE: "available",
        ApplicationLaunchStatus.NOT_INSTALLED: "not installed",
        ApplicationLaunchStatus.INCOMPATIBLE: "incompatible",
        ApplicationLaunchStatus.UNAVAILABLE: "launcher unavailable",
    }[status]


def _safe_unavailable_details(
    observed: ApplicationObservation | None,
) -> tuple[str, str]:
    """Give actionable categories without echoing unchecked metadata or paths.

    The authoritative detail remains ``pds modules``. Producer/package error
    strings can contain private installation paths or active terminal controls,
    so they must never be interpolated into Suite's interactive home.
    """
    if observed is None:
        return (
            "Current-environment inventory could not establish launch eligibility.",
            "Run pds modules to inspect and repair the local installation.",
        )
    if observed.status is ApplicationLaunchStatus.NOT_INSTALLED:
        return (
            "The approved application is not installed in this Python environment.",
            "Install its official module wheel into this environment, then rerun "
            "pds modules.",
        )
    if observed.status is ApplicationLaunchStatus.INCOMPATIBLE:
        return (
            "Installed dependency or entry-point metadata did not qualify.",
            "Run pds modules to identify the incompatible component and repair it "
            "before launching.",
        )
    if observed.status is ApplicationLaunchStatus.UNAVAILABLE:
        return (
            "The approved current-environment application launcher is unavailable.",
            "Run pds modules to inspect launcher resolution and remediation.",
        )
    if observed.launcher_path is None:
        return (
            "Local metadata qualified but no approved launcher was resolved.",
            "Run pds modules and repair the current-environment launcher.",
        )
    return ("", "")


def build_home_applications(
    inventory: ApplicationInventory | None,
) -> tuple[HomeApplication, ...]:
    """Render only the six approved app IDs, never arbitrary installed packages."""
    rows: list[HomeApplication] = []
    for approved in APPROVED_COMPONENTS:
        if not approved.launchable:
            continue
        found = inventory.for_component(approved.component_id) if inventory else None
        usable = (
            found is not None
            and found.status is ApplicationLaunchStatus.AVAILABLE
            and found.launcher_path is not None
        )
        explanation, remediation = _safe_unavailable_details(found)
        rows.append(
            HomeApplication(
                component_id=approved.component_id,
                display_name=approved.display_name,
                purpose=found.purpose if found else "Inspect with pds modules",
                status=(
                    "launcher unavailable"
                    if found is not None
                    and found.status is ApplicationLaunchStatus.AVAILABLE
                    and found.launcher_path is None
                    else _status_label(found.status)
                    if found is not None
                    else "unavailable"
                ),
                selectable=usable,
                unavailable_reason=explanation,
                remediation=remediation,
            )
        )
    return tuple(rows)


def _load_recent_component_ids() -> tuple[str, ...]:
    allowed = frozenset(
        component.component_id
        for component in APPROVED_COMPONENTS
        if component.launchable
    )
    return load_suite_settings(allowed_component_ids=allowed).recent_components


def _choice(input_stream: TextIO, output: TextIO) -> str | None:
    output.write("Selection: ")
    output.flush()
    try:
        entered = input_stream.readline()
    except (EOFError, KeyboardInterrupt, OSError, UnicodeError):
        return None
    if not entered:
        return None
    # Do not echo or log untrusted input; do not treat multiline text as commands.
    if len(entered) > 64:
        return ""
    return entered.strip().casefold()


def _navigation(value: str, *, at_home: bool) -> str | None:
    if value == "q":
        return "quit"
    if value == "m" or (value == "b" and not at_home):
        return "home"
    if value == "b" and at_home:
        return "already-home"
    return None


def _home_screen(
    *,
    output: TextIO,
    header: _Header,
    applications: tuple[HomeApplication, ...],
    inventory_failed: bool,
) -> None:
    header.print("Teacher Home", output=output)
    if header.notice:
        output.write(f"{header.notice}\n")
    if inventory_failed:
        output.write(
            "Application inventory unavailable; inspect with pds modules.\n"
        )
    output.write("\nApplications (current environment; provenance not verified)\n")
    for number, app in enumerate(applications, start=1):
        output.write(f" {number}. {app.display_name} — {app.status}\n")
        output.write(f"    {app.purpose}\n")
    output.write("\nTeacher workflows\n")
    for number, (name, _, _) in enumerate(_WORKFLOWS, start=7):
        output.write(f" {number}. {name} — not yet available\n")
    output.write(" 11. Recent Applications — previously opened applications only\n")
    output.write(" 12. Help & Diagnostics\n")
    output.write("\nH. Help   B. Back   M. Main Menu   Q. Quit\n")


def _view(
    *,
    output: TextIO,
    input_stream: TextIO,
    header: _Header,
    title: str,
    lines: tuple[str, ...],
) -> bool:
    """Show a Suite-owned informational screen. True means quit entire shell."""
    while True:
        header.print(title, output=output)
        output.write("\n" + "\n".join(lines) + "\n")
        output.write("\nB. Back   M. Main Menu   Q. Quit\n")
        entered = _choice(input_stream, output)
        if entered is None or _navigation(entered, at_home=False) == "quit":
            return True
        if _navigation(entered, at_home=False) == "home":
            return False
        output.write("Choose B, M, or Q.\n")


def _launch(
    *,
    app: HomeApplication,
    output: TextIO,
    header: _Header,
    launch: Callable[[str], int],
) -> None:
    if not app.selectable:
        header.print("Application Unavailable", output=output)
        output.write(
            f"{app.display_name} cannot be launched ({app.status}).\n"
            f"Reason: {app.unavailable_reason}\n"
            f"Next step: {app.remediation}\n"
        )
        return
    # CLI's existing _run_launch() is the authorization, action-time inventory
    # recheck, foreground subprocess and recent-component recording authority.
    output.write(f"Opening {app.display_name} through pds launch...\n")
    output.flush()
    try:
        result = launch(app.component_id)
    except KeyboardInterrupt:
        header.print("Application Result", output=output)
        output.write("Application launch interrupted; returning to Teacher Home.\n")
        return
    except (ApplicationLaunchExecutionError, ApplicationLaunchRefusedError, OSError):
        # Bounded launcher failures should not end the interactive Suite shell.
        # Do not print raw exception text: it may contain private local paths.
        header.print("Application Result", output=output)
        output.write(
            "Application launch was refused or could not start. "
            "Run pds modules for current-environment diagnostics. "
            "Returning to Teacher Home.\n"
        )
        return
    header.print("Application Result", output=output)
    if result == 0:
        output.write(f"Returned from {app.display_name}.\n")
    else:
        output.write(
            f"{app.display_name} did not complete successfully "
            f"(Suite launch status {result}). Returning to Teacher Home.\n"
        )


def _recent_screen(
    *,
    input_stream: TextIO,
    output: TextIO,
    header: _Header,
    recent: Callable[[], tuple[str, ...]],
    applications: tuple[HomeApplication, ...],
    launch: Callable[[str], int],
) -> bool:
    by_id = {app.component_id: app for app in applications}
    try:
        ids = tuple(value for value in recent() if value in by_id)[:5]
        notice = None
    except (SuiteSettingsError, OSError):
        ids = ()
        notice = (
            "Recent application settings could not be read; "
            "no settings were changed."
        )
    while True:
        header.print("Recent Applications", output=output)
        output.write(
            "\nThis is application history, not a list of recent work items.\n"
        )
        if notice:
            output.write(notice + "\n")
        if not ids:
            output.write("No readable recent applications.\n")
        for number, component_id in enumerate(ids, start=1):
            app = by_id[component_id]
            output.write(f" {number}. {app.display_name} — {app.status}\n")
        output.write("\nB. Back   M. Main Menu   Q. Quit\n")
        choice = _choice(input_stream, output)
        if choice is None or _navigation(choice, at_home=False) == "quit":
            return True
        if _navigation(choice, at_home=False) == "home":
            return False
        if choice.isascii() and choice.isdecimal() and 1 <= int(choice) <= len(ids):
            _launch(
                app=by_id[ids[int(choice) - 1]],
                output=output,
                header=header,
                launch=launch,
            )
            return False
        output.write("Choose a listed application, B, M, or Q.\n")


def _diagnostic_screen(
    *,
    input_stream: TextIO,
    output: TextIO,
    header: _Header,
    doctor: Callable[[], int],
    show_help: Callable[[], None],
) -> bool:
    while True:
        header.print("Help & Diagnostics", output=output)
        output.write(
            "\n1. Run pds doctor (explicit read-only diagnosis)\n"
            "2. Show pds --help\n\nB. Back   M. Main Menu   Q. Quit\n"
        )
        choice = _choice(input_stream, output)
        if choice is None or _navigation(choice, at_home=False) == "quit":
            return True
        if _navigation(choice, at_home=False) == "home":
            return False
        if choice == "1":
            header.print("Diagnostics Result", output=output)
            try:
                code = doctor()
            except KeyboardInterrupt:
                output.write("Doctor interrupted; returning to Teacher Home.\n")
                return False
            output.write(f"Doctor completed (status {code}).\n")
            return False
        if choice == "2":
            header.print("Command-Line Help", output=output)
            show_help()
            return False
        output.write("Choose 1, 2, B, M, or Q.\n")


def run_teacher_home(
    *,
    input_stream: TextIO,
    output: TextIO,
    collect_inventory: Callable[[], ApplicationInventory] = (
        collect_local_launch_inventory
    ),
    launch: Callable[[str], int],
    doctor: Callable[[], int],
    show_help: Callable[[], None],
    recent: Callable[[], tuple[str, ...]] = _load_recent_component_ids,
    observe_contract: Callable[[], CoreTeacherContractObservation] = (
        observe_core_teacher_contract
    ),
    core_importer: Callable[[str], object] = import_module,
) -> int:
    """Run an injected foreground shell; zero settings/workspace writes on entry."""
    header = _Header(probe=observe_contract, importer=core_importer)
    while True:
        try:
            inventory = collect_inventory()
        except (ApplicationInventoryError, LocalInspectionError, OSError):
            inventory = None
        applications = build_home_applications(inventory)
        _home_screen(
            output=output,
            header=header,
            applications=applications,
            inventory_failed=inventory is None,
        )
        choice = _choice(input_stream, output)
        if choice is None or _navigation(choice, at_home=True) == "quit":
            output.write("Leaving Paper Data Suite.\n")
            return 0
        if _navigation(choice, at_home=True) == "already-home":
            output.write("Already at Teacher Home.\n")
            continue
        if _navigation(choice, at_home=True) == "home":
            continue
        if choice == "h":
            quit_home = _view(
                output=output,
                input_stream=input_stream,
                header=header,
                title="Teacher Home Help",
                lines=(
                    "Choose 1-6 for an eligible installed application.",
                    "The foreground application controls its own menus and commands.",
                    "B returns from a Suite view; M redraws home; Q quits Suite.",
                    "Disabled options do not imply empty or evaluated records.",
                    "Use Help & Diagnostics for pds doctor and CLI help.",
                ),
            )
            if quit_home:
                return 0
            continue
        if (
            choice.isascii()
            and choice.isdecimal()
            and 1 <= int(choice) <= len(applications)
        ):
            _launch(
                app=applications[int(choice) - 1],
                output=output,
                header=header,
                launch=launch,
            )
            continue
        if choice.isascii() and choice.isdecimal() and 7 <= int(choice) <= 10:
            title, detail, alternative = _WORKFLOWS[int(choice) - 7]
            if _view(
                output=output,
                input_stream=input_stream,
                header=header,
                title=title,
                lines=(detail, alternative),
            ):
                return 0
            continue
        if choice == "11":
            if _recent_screen(
                input_stream=input_stream,
                output=output,
                header=header,
                recent=recent,
                applications=applications,
                launch=launch,
            ):
                return 0
            continue
        if choice == "12":
            if _diagnostic_screen(
                input_stream=input_stream,
                output=output,
                header=header,
                doctor=doctor,
                show_help=show_help,
            ):
                return 0
            continue
        output.write("Choose a listed number, H, B, M, or Q.\n")
