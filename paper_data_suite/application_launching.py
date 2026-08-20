"""Safe current-environment resolution and foreground application launching."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Protocol

from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
    ApplicationObservation,
)

_CONSOLE_SCRIPT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REPAIR_GUIDANCE = (
    "Use the verified Paper Data Suite bootstrap/update workflow to restore the "
    "suite-qualified environment."
)

ScriptsPathLookup = Callable[[], str | None]
ExecutableCheck = Callable[[Path], bool]
LauncherResolver = Callable[[str], Path]


class LauncherResolutionCode(str, Enum):
    """Stable reason a qualified console launcher cannot be trusted."""

    INVALID_NAME = "INVALID_NAME"
    SCRIPTS_DIRECTORY_UNAVAILABLE = "SCRIPTS_DIRECTORY_UNAVAILABLE"
    OUTSIDE_ENVIRONMENT = "OUTSIDE_ENVIRONMENT"
    MISSING = "MISSING"
    NOT_EXECUTABLE = "NOT_EXECUTABLE"


class ApplicationLauncherResolutionError(RuntimeError):
    """Raised when a current-environment console launcher is unavailable."""

    def __init__(self, code: LauncherResolutionCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ApplicationLaunchError(RuntimeError):
    """Base class for suite-owned application launch failures."""


class ApplicationLaunchRefusedError(ApplicationLaunchError):
    """Raised when the selected application is not eligible for execution."""


class ApplicationLaunchExecutionError(ApplicationLaunchError):
    """Raised when the verified launcher cannot be started."""


class ApplicationProcessRunner(Protocol):
    """Foreground subprocess shape used by suite application launching."""

    def __call__(
        self,
        args: Sequence[str],
        *,
        check: bool,
        shell: bool,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[bytes]: ...


@dataclass(frozen=True, slots=True)
class ApplicationLaunchResult:
    """Stable result after a verified child application exits."""

    component_id: str
    display_name: str
    launcher_path: Path
    exit_code: int

    @property
    def succeeded(self) -> bool:
        """Whether the child application exited successfully."""
        return self.exit_code == 0


def _current_scripts_path() -> str | None:
    value = sysconfig.get_path("scripts")
    return value if isinstance(value, str) else None


def _default_executable_check(path: Path) -> bool:
    return os.access(path, os.X_OK)


def _is_windows(platform: str) -> bool:
    normalized = platform.lower()
    return normalized.startswith(("win32", "cygwin", "msys"))


def resolve_current_environment_launcher(
    console_script_name: str,
    *,
    scripts_path_lookup: ScriptsPathLookup = _current_scripts_path,
    platform: str | None = None,
    executable_check: ExecutableCheck = _default_executable_check,
) -> Path:
    """Resolve one console launcher only from the running Python environment."""
    if _CONSOLE_SCRIPT_NAME_RE.fullmatch(console_script_name) is None:
        raise ApplicationLauncherResolutionError(
            LauncherResolutionCode.INVALID_NAME,
            "console-script name is not safe for launcher resolution",
        )

    raw_scripts_path = scripts_path_lookup()
    if raw_scripts_path is None or not raw_scripts_path.strip():
        raise ApplicationLauncherResolutionError(
            LauncherResolutionCode.SCRIPTS_DIRECTORY_UNAVAILABLE,
            "current Python environment does not expose a scripts directory",
        )

    scripts_root = Path(raw_scripts_path).expanduser().resolve(strict=False)
    if not scripts_root.is_dir():
        raise ApplicationLauncherResolutionError(
            LauncherResolutionCode.SCRIPTS_DIRECTORY_UNAVAILABLE,
            "current Python environment scripts directory is unavailable",
        )

    active_platform = platform or sys.platform
    filename = (
        f"{console_script_name}.exe"
        if _is_windows(active_platform)
        else console_script_name
    )
    candidate = (scripts_root / filename).resolve(strict=False)
    try:
        candidate.relative_to(scripts_root)
    except ValueError as error:
        raise ApplicationLauncherResolutionError(
            LauncherResolutionCode.OUTSIDE_ENVIRONMENT,
            "resolved console launcher escapes the current Python environment",
        ) from error

    if not candidate.is_file():
        raise ApplicationLauncherResolutionError(
            LauncherResolutionCode.MISSING,
            f"current-environment launcher {filename!r} is missing",
        )

    if not _is_windows(active_platform) and not executable_check(candidate):
        raise ApplicationLauncherResolutionError(
            LauncherResolutionCode.NOT_EXECUTABLE,
            f"current-environment launcher {filename!r} is not executable",
        )

    return candidate


def _unavailable_reason(
    application: ApplicationObservation,
    error: ApplicationLauncherResolutionError,
) -> str:
    return (
        f"{application.display_name} has qualified package metadata, but its "
        f"current-environment launcher is unavailable ({error.code.value.lower()})."
    )


def resolve_application_launchers(
    inventory: ApplicationInventory,
    *,
    launcher_resolver: LauncherResolver = resolve_current_environment_launcher,
) -> ApplicationInventory:
    """Resolve launchers for metadata-qualified rows without hiding other rows."""
    resolved: list[ApplicationObservation] = []
    for application in inventory.applications:
        if application.status is not ApplicationLaunchStatus.AVAILABLE:
            resolved.append(application)
            continue

        try:
            launcher = launcher_resolver(application.console_script_name)
        except ApplicationLauncherResolutionError as error:
            resolved.append(
                replace(
                    application,
                    status=ApplicationLaunchStatus.UNAVAILABLE,
                    reason=_unavailable_reason(application, error),
                    remediation=_REPAIR_GUIDANCE,
                    launcher_path=None,
                )
            )
            continue
        except OSError as error:
            message = str(error)[:200] or error.__class__.__name__
            resolved.append(
                replace(
                    application,
                    status=ApplicationLaunchStatus.UNAVAILABLE,
                    reason=(
                        f"{application.display_name} launcher could not be inspected: "
                        f"{message}"
                    ),
                    remediation=_REPAIR_GUIDANCE,
                    launcher_path=None,
                )
            )
            continue

        resolved.append(
            replace(
                application,
                reason=(
                    f"{application.display_name} {application.qualified_version} "
                    "has a verified launcher in the current Python environment."
                ),
                remediation=None,
                launcher_path=launcher,
            )
        )

    return ApplicationInventory(tuple(resolved))


def _default_process_runner(
    args: Sequence[str],
    *,
    check: bool,
    shell: bool,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        check=check,
        shell=shell,
        env=env,
    )


def launch_application(
    application: ApplicationObservation,
    *,
    process_runner: ApplicationProcessRunner = _default_process_runner,
    environ: Mapping[str, str] | None = None,
) -> ApplicationLaunchResult:
    """Launch one verified application in the foreground without private imports."""
    launcher = application.launcher_path
    if application.status is not ApplicationLaunchStatus.AVAILABLE or launcher is None:
        raise ApplicationLaunchRefusedError(
            f"{application.display_name} is not available for suite launch"
        )

    child_environment = dict(os.environ if environ is None else environ)
    for key in tuple(child_environment):
        if key.upper() == "PYTHONPATH":
            del child_environment[key]

    try:
        result = process_runner(
            (str(launcher),),
            check=False,
            shell=False,
            env=child_environment,
        )
    except OSError as error:
        message = str(error)[:300] or error.__class__.__name__
        raise ApplicationLaunchExecutionError(
            f"could not start {application.display_name}: {message}"
        ) from error

    return ApplicationLaunchResult(
        component_id=application.component_id,
        display_name=application.display_name,
        launcher_path=launcher,
        exit_code=result.returncode,
    )


__all__ = (
    "ApplicationLaunchError",
    "ApplicationLaunchExecutionError",
    "ApplicationLaunchRefusedError",
    "ApplicationLaunchResult",
    "ApplicationLauncherResolutionError",
    "ApplicationProcessRunner",
    "ExecutableCheck",
    "LauncherResolutionCode",
    "LauncherResolver",
    "ScriptsPathLookup",
    "launch_application",
    "resolve_application_launchers",
    "resolve_current_environment_launcher",
)
