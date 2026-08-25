"""Exercise one continuous installed-suite workflow from exact release wheels."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import venv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from paper_data_suite.artifact_verification import (
    ArtifactVerificationError,
    verify_artifact_directory,
    verify_release_tool_wheel,
)
from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    load_release_compatibility_manifest,
)
from paper_data_suite.release_tooling import (
    ReleaseToolingError,
    load_release_tooling_contract,
)


class CombinedSuiteSmokeError(RuntimeError):
    """Raised when combined installed-suite acceptance fails."""


@dataclass(frozen=True, slots=True)
class ApplicationExpectation:
    """One launchable application declared by the active suite manifest."""

    component_id: str
    display_name: str
    distribution: str
    version: str
    import_name: str
    wheel: str
    console_script: str


TreeSnapshot = tuple[tuple[str, str], ...]

_SIBLING_IMPORT_ROOTS: Final[frozenset[str]] = frozenset(
    {"concord", "meridian", "portia", "quillan", "scoreform", "vitrine"}
)
_SYNTHETIC_SCHOOL_YEAR: Final[str] = "2026-2027"
_SYNTHETIC_CLASS_ID: Final[str] = "eng10"
_SYNTHETIC_STARTER_PACK: Final[str] = "njsls_ela_2023"


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_text: str | None = None,
    timeout: float = 180.0,
    require_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=dict(env),
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CombinedSuiteSmokeError(
            f"Command could not complete: {' '.join(command)}: {error}"
        ) from error
    if require_success and result.returncode != 0:
        raise CombinedSuiteSmokeError(
            "Command failed "
            f"({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _scripts_directory(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> Path:
    result = _run(
        [
            str(python),
            "-c",
            "import sysconfig; print(sysconfig.get_path('scripts'))",
        ],
        cwd=cwd,
        env=env,
    )
    return Path(result.stdout.strip())


def _assert_clean_directory(path: Path) -> None:
    contents = tuple(path.iterdir())
    if contents:
        names = ", ".join(item.name for item in contents)
        raise CombinedSuiteSmokeError(
            f"Combined acceptance created working-directory artifacts: {names}"
        )


def _application_expectations() -> tuple[ApplicationExpectation, ...]:
    manifest = load_release_compatibility_manifest()
    applications: list[ApplicationExpectation] = []
    for component in manifest.components:
        if "launchable_application" not in component.capabilities:
            continue
        console_scripts = tuple(
            entry_point.name
            for entry_point in component.entry_points
            if entry_point.group == "console_scripts"
        )
        if len(console_scripts) != 1:
            raise CombinedSuiteSmokeError(
                f"{component.component_id} must declare one console script."
            )
        applications.append(
            ApplicationExpectation(
                component_id=component.component_id,
                display_name=component.display_name,
                distribution=component.distribution,
                version=component.version,
                import_name=component.import_name,
                wheel=component.release.wheel,
                console_script=console_scripts[0],
            )
        )
    if not applications:
        raise CombinedSuiteSmokeError(
            "Compatibility manifest declares no launchable applications."
        )
    return tuple(applications)


def _component_wheels(
    artifact_dir: Path,
    applications: Sequence[ApplicationExpectation],
) -> tuple[Path, tuple[Path, ...]]:
    manifest = load_release_compatibility_manifest()
    core_rows = tuple(
        component
        for component in manifest.components
        if component.component_id == "core"
    )
    if len(core_rows) != 1:
        raise CombinedSuiteSmokeError(
            "Compatibility manifest must declare exactly one Core component."
        )
    core_wheel = artifact_dir / core_rows[0].release.wheel
    application_wheels = tuple(
        artifact_dir / application.wheel for application in applications
    )
    missing = tuple(
        path for path in (core_wheel, *application_wheels) if not path.is_file()
    )
    if missing:
        raise CombinedSuiteSmokeError(
            "Verified component artifact is missing: "
            + ", ".join(str(path) for path in missing)
        )
    return core_wheel, application_wheels


def _installation_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env.pop("PYTHONPATH", None)
    env.pop("PDS_WORKSPACE_ROOT", None)
    env.pop("PIP_NO_INDEX", None)
    return env


def _command_environment(
    base_env: Mapping[str, str],
    *,
    user_home: Path,
    path_prefix: Path,
) -> dict[str, str]:
    env = dict(base_env)
    for key in tuple(env):
        if key.upper() in {"PYTHONPATH", "PDS_WORKSPACE_ROOT"}:
            env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INDEX"] = "1"
    env["HOME"] = str(user_home)
    env["USERPROFILE"] = str(user_home)
    env["LOCALAPPDATA"] = str(user_home / "AppData" / "Local")
    env["APPDATA"] = str(user_home / "AppData" / "Roaming")
    env["XDG_CONFIG_HOME"] = str(user_home / ".config")
    existing_path = env.get("PATH", "")
    env["PATH"] = (
        f"{path_prefix}{os.pathsep}{existing_path}"
        if existing_path
        else str(path_prefix)
    )
    return env


def _write_test_command(
    directory: Path,
    name: str,
    *,
    marker: Path | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        command = directory / f"{name}.cmd"
        lines = ["@echo off"]
        if marker is not None:
            lines.append(f'> "{marker}" echo foreign launcher executed')
        lines.append("exit /b 0")
        command.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        return command

    command = directory / name
    lines = ["#!/bin/sh"]
    if marker is not None:
        lines.append(f"printf '%s\\n' 'foreign launcher executed' > '{marker}'")
    lines.append("exit 0")
    command.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command.chmod(0o755)
    return command


def _assert_installed_versions(
    python: Path,
    applications: Sequence[ApplicationExpectation],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    manifest = load_release_compatibility_manifest()
    expected = {
        manifest.suite.distribution: manifest.suite.version,
        **{
            component.distribution: component.version
            for component in manifest.components
        },
    }
    code = (
        "import importlib.metadata as m, json; "
        f"names={tuple(expected)!r}; "
        "print(json.dumps({name: m.version(name) for name in names}, sort_keys=True))"
    )
    result = _run([str(python), "-c", code], cwd=cwd, env=env)
    observed_raw = json.loads(result.stdout)
    if not isinstance(observed_raw, dict):
        raise CombinedSuiteSmokeError("Installed version inventory was not an object.")
    observed = cast(dict[str, object], observed_raw)
    if observed != expected:
        raise CombinedSuiteSmokeError(
            f"Installed versions do not match the suite manifest: {observed!r}"
        )


def _assert_installed_import_roots(
    python: Path,
    environment: Path,
    applications: Sequence[ApplicationExpectation],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    import_names = (
        "paper_data_suite",
        "pds_core",
        *(application.import_name for application in applications),
    )
    code = (
        "import importlib, json; from pathlib import Path; "
        f"names={import_names!r}; "
        "print(json.dumps({name: str(Path(importlib.import_module(name).__file__)."
        "resolve()) for name in names}, sort_keys=True))"
    )
    result = _run([str(python), "-c", code], cwd=cwd, env=env)
    observed_raw = json.loads(result.stdout)
    if not isinstance(observed_raw, dict):
        raise CombinedSuiteSmokeError("Installed import inventory was not an object.")
    observed = cast(dict[str, object], observed_raw)
    environment_root = environment.resolve()
    for name, raw_path in observed.items():
        if not isinstance(raw_path, str):
            raise CombinedSuiteSmokeError(
                f"Installed import path for {name} is not a string."
            )
        path = Path(raw_path).resolve()
        try:
            path.relative_to(environment_root)
        except ValueError as error:
            raise CombinedSuiteSmokeError(
                f"Installed acceptance imported {name} outside the venv: {path}"
            ) from error


def _snapshot_tree(root: Path) -> TreeSnapshot:
    if not root.exists():
        return ()
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise CombinedSuiteSmokeError(
                f"Synthetic workspace unexpectedly contains a symlink: {relative}"
            )
        if path.is_dir():
            entries.append((relative, "directory"))
            continue
        if not path.is_file():
            raise CombinedSuiteSmokeError(
                f"Synthetic workspace has an unsupported entry: {relative}"
            )
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        entries.append((relative, f"file:{path.stat().st_size}:{digest}"))
    return tuple(entries)


def _assert_tree_unchanged(
    before: TreeSnapshot,
    after: TreeSnapshot,
    *,
    operation: str,
) -> None:
    if before != after:
        raise CombinedSuiteSmokeError(
            f"{operation} unexpectedly changed synthetic workspace bytes."
        )


def _seed_opaque_workspace_fixture(workspace: Path) -> None:
    """Add test-owned opaque bytes without pretending they are module records."""
    fixture = workspace / "future-module" / "opaque-custody-fixture"
    (fixture / "empty").mkdir(parents=True)
    (fixture / "opaque.bin").write_bytes(b"\x00\xffcombined-synthetic")
    (fixture / ".synthetic-hidden").write_text(
        "combined synthetic hidden file",
        encoding="utf-8",
    )
    (fixture / "zero.dat").write_bytes(b"")


def _find_completed_backup(parent: Path) -> Path:
    if not parent.is_dir():
        raise CombinedSuiteSmokeError("Backup destination parent was not created.")
    completed = tuple(
        path
        for path in parent.iterdir()
        if path.is_dir() and path.name.startswith("pds-workspace-backup-")
    )
    if len(completed) != 1:
        raise CombinedSuiteSmokeError(
            f"Expected one completed backup, found {len(completed)}."
        )
    incomplete = tuple(parent.glob(".*.incomplete-*"))
    if incomplete:
        raise CombinedSuiteSmokeError(
            "Successful combined backup left incomplete staging state."
        )
    return completed[0]


def _assert_backup_manifest(
    manifest_path: Path,
    *,
    backup_root: Path,
    source_snapshot: TreeSnapshot,
) -> str:
    try:
        payload_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CombinedSuiteSmokeError(
            f"Combined backup manifest could not be read: {error}"
        ) from error
    if not isinstance(payload_raw, dict):
        raise CombinedSuiteSmokeError("Combined backup manifest is not an object.")
    payload = cast(dict[str, object], payload_raw)
    manifest = load_release_compatibility_manifest()
    core = next(
        component
        for component in manifest.components
        if component.component_id == "core"
    )
    expected = {
        "record_type": "pds_workspace_backup_manifest",
        "schema_version": "1",
        "backup_id": backup_root.name,
        "suite_version": manifest.suite.version,
        "core_version": core.version,
        "payload_root": "workspace",
        "hash_algorithm": "sha256",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise CombinedSuiteSmokeError(
                f"Combined backup manifest {key} is unexpected: {payload.get(key)!r}"
            )
    if payload.get("directory_count") != sum(
        kind == "directory" for _path, kind in source_snapshot
    ):
        raise CombinedSuiteSmokeError("Backup manifest directory_count is incorrect.")
    expected_files = tuple(
        (path, value)
        for path, value in source_snapshot
        if value.startswith("file:")
    )
    if payload.get("file_count") != len(expected_files):
        raise CombinedSuiteSmokeError("Backup manifest file_count is incorrect.")
    expected_bytes = sum(
        int(value.split(":", 2)[1])
        for _path, value in expected_files
    )
    if payload.get("total_bytes") != expected_bytes:
        raise CombinedSuiteSmokeError("Backup manifest total_bytes is incorrect.")
    if payload.get("exclusions") != []:
        raise CombinedSuiteSmokeError("Backup manifest exclusions are unexpected.")
    with manifest_path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _workspace_override_environment(
    env: Mapping[str, str],
    workspace: Path,
) -> dict[str, str]:
    override = dict(env)
    override["PDS_WORKSPACE_ROOT"] = str(workspace.resolve())
    return override


def _suite_settings_path(
    user_home: Path,
    env: Mapping[str, str],
    *,
    platform: str | None = None,
) -> Path:
    active_platform = (platform or sys.platform).lower()
    if active_platform.startswith(("win32", "cygwin", "msys")):
        configured = env.get("LOCALAPPDATA", "").strip()
        root = Path(configured) if configured else user_home / "AppData" / "Local"
        return root / "Paper Data Suite" / "settings.json"
    if active_platform == "darwin":
        return (
            user_home
            / "Library"
            / "Application Support"
            / "Paper Data Suite"
            / "settings.json"
        )
    configured = env.get("XDG_CONFIG_HOME", "").strip()
    root = Path(configured) if configured else user_home / ".config"
    return root / "paper-data-suite" / "settings.json"


def _assert_settings_document(
    path: Path,
    *,
    expected_recent: Sequence[str],
) -> None:
    if not path.is_file():
        raise CombinedSuiteSmokeError(f"Suite settings were not written: {path}")
    try:
        payload_raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CombinedSuiteSmokeError(
            f"Suite settings could not be inspected: {error}"
        ) from error
    if not isinstance(payload_raw, dict):
        raise CombinedSuiteSmokeError("Suite settings are not a JSON object.")
    payload = cast(dict[str, object], payload_raw)
    if set(payload) != {"record_type", "schema_version", "recent_components"}:
        raise CombinedSuiteSmokeError(
            f"Suite settings contain unexpected fields: {sorted(payload)}"
        )
    if payload.get("record_type") != "paper_data_suite_settings":
        raise CombinedSuiteSmokeError("Suite settings record_type is unexpected.")
    if payload.get("schema_version") != "1":
        raise CombinedSuiteSmokeError("Suite settings schema_version is unexpected.")
    if payload.get("recent_components") != list(expected_recent):
        raise CombinedSuiteSmokeError(
            "Suite recent-component context does not match actual launches."
        )


def _sibling_private_imports(package_root: Path) -> tuple[str, ...]:
    findings: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as error:
            raise CombinedSuiteSmokeError(
                f"Could not inspect production import boundary in {path}: {error}"
            ) from error
        for node in ast.walk(tree):
            names: tuple[str, ...]
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = (node.module,)
            else:
                continue
            for name in names:
                root = name.split(".", 1)[0]
                if root in _SIBLING_IMPORT_ROOTS:
                    findings.append(f"{path.as_posix()}:{node.lineno}:{name}")
    return tuple(findings)


def _assert_no_sibling_private_imports(package_root: Path) -> None:
    findings = _sibling_private_imports(package_root)
    if findings:
        raise CombinedSuiteSmokeError(
            "Suite production code imports sibling application internals: "
            + ", ".join(findings)
        )


def _first_setup_input(roster_source: Path) -> str:
    values = (
        _SYNTHETIC_SCHOOL_YEAR,
        _SYNTHETIC_CLASS_ID,
        str(roster_source),
        "",
        _SYNTHETIC_STARTER_PACK,
        "1",
        "q1",
        "quarter",
        "Quarter 1",
        "2026-09-01",
        "2026-11-01",
        "",
        "1",
        "planned",
        "n",
        "APPLY",
    )
    return "\n".join(values) + "\n"


def _rerun_setup_input(roster_source: Path) -> str:
    values = (
        _SYNTHETIC_CLASS_ID,
        str(roster_source),
        "",
        _SYNTHETIC_STARTER_PACK,
        "APPLY",
    )
    return "\n".join(values) + "\n"


def _assert_core_setup_state(
    python: Path,
    roster_source: Path,
    workspace: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    code = f"""
import json
from pds_core.academic_period_storage import load_current_academic_period_calendar
from pds_core.classes import list_class_folders
from pds_core.roster_imports import plan_roster_import
from pds_core.school_years import get_active_school_year
from pds_core.standards import load_workspace_standards_library
from pds_core.workspace import inspect_workspace_root

root = inspect_workspace_root().root
folders = list_class_folders(root, require_metadata=True)
library = load_workspace_standards_library(root)
calendar = load_current_academic_period_calendar(root, {_SYNTHETIC_SCHOOL_YEAR!r})
preview = plan_roster_import(root, {_SYNTHETIC_CLASS_ID!r}, {str(roster_source)!r})
print(json.dumps({{
    "root": str(root.resolve()),
    "active_school_year": get_active_school_year(root),
    "class_ids": [folder.class_id for folder in folders],
    "standards_count": len(library.standards),
    "profile_count": len(library.profiles),
    "framework_count": len(library.frameworks),
    "framework_ids": [framework.framework_id for framework in library.frameworks],
    "calendar_revision": None if calendar is None else calendar.calendar_revision,
    "period_ids": (
        [] if calendar is None else [period.period_id for period in calendar.periods]
    ),
    "roster_current": preview.current_roster_present,
    "roster_additions": preview.addition_count,
    "roster_changes": preview.change_count,
    "roster_removals": preview.removal_count,
    "roster_unchanged": preview.unchanged_count,
    "roster_tokens_match": preview.current_state_token == preview.candidate_state_token,
}}, sort_keys=True))
""".strip()
    result = _run([str(python), "-c", code], cwd=cwd, env=env)
    payload_raw = json.loads(result.stdout)
    if not isinstance(payload_raw, dict):
        raise CombinedSuiteSmokeError("Core setup state was not a JSON object.")
    payload = cast(dict[str, object], payload_raw)
    if payload.get("root") != str(workspace.resolve()):
        raise CombinedSuiteSmokeError("Core resolved the wrong synthetic workspace.")
    if payload.get("active_school_year") != _SYNTHETIC_SCHOOL_YEAR:
        raise CombinedSuiteSmokeError("Synthetic school year was not opened.")
    if payload.get("class_ids") != [_SYNTHETIC_CLASS_ID]:
        raise CombinedSuiteSmokeError("Synthetic class state is unexpected.")
    standards_count = payload.get("standards_count")
    profile_count = payload.get("profile_count")
    if not isinstance(standards_count, int) or standards_count <= 0:
        raise CombinedSuiteSmokeError("Starter standards were not installed.")
    if not isinstance(profile_count, int) or profile_count <= 0:
        raise CombinedSuiteSmokeError("Starter standards profiles were not installed.")
    if payload.get("framework_count") != 1:
        raise CombinedSuiteSmokeError(
            "Starter standards framework metadata was not installed exactly once."
        )
    if payload.get("framework_ids") != [_SYNTHETIC_STARTER_PACK]:
        raise CombinedSuiteSmokeError(
            "Installed starter framework identity is unexpected."
        )
    if payload.get("calendar_revision") != 1 or payload.get("period_ids") != ["q1"]:
        raise CombinedSuiteSmokeError("Initial Academic Period calendar is unexpected.")
    expected_roster = {
        "roster_current": True,
        "roster_additions": 0,
        "roster_changes": 0,
        "roster_removals": 0,
        "roster_unchanged": 2,
        "roster_tokens_match": True,
    }
    for key, value in expected_roster.items():
        if payload.get(key) != value:
            raise CombinedSuiteSmokeError(
                f"Guarded roster verification failed for {key}: {payload.get(key)!r}"
            )


def _assert_module_inventory(
    output: str,
    applications: Sequence[ApplicationExpectation],
) -> None:
    if not output.startswith("Paper Data Suite applications\n"):
        raise CombinedSuiteSmokeError("Installed module inventory heading is wrong.")
    for application in applications:
        required = (
            application.display_name,
            "Status: available",
            f"Component ID: {application.component_id}",
            f"Suite-qualified version: {application.version}",
            f"Installed version: {application.version}",
            f"Launch: pds launch {application.component_id}",
        )
        missing = tuple(fragment for fragment in required if fragment not in output)
        if missing:
            raise CombinedSuiteSmokeError(
                f"Inventory for {application.component_id} is incomplete: "
                + ", ".join(missing)
            )
    if output.count("Status: available") != len(applications):
        raise CombinedSuiteSmokeError(
            "Combined inventory contains an unexpected application status."
        )
    forbidden = ("PDS Core\n", "Meridian\n", "Portia\n", ".cli:main")
    leaked = tuple(fragment for fragment in forbidden if fragment in output)
    if leaked:
        raise CombinedSuiteSmokeError(
            "Combined inventory exposed an invalid row or private target: "
            + ", ".join(leaked)
        )


def _assert_configured_doctor(output: str) -> None:
    required = (
        "Core workspace inspection public contract is available.",
        "Core active school year public contract is available.",
        "Core academic registry status public contract is available.",
        "Core failure-isolated provider diagnostics are available.",
        "Core module-operations contract v1 is available.",
        "No suite-qualified module readiness provider is available.",
        "Routing provider concord satisfies the active Core contract.",
        "Routing provider quillan satisfies the active Core contract.",
        "Routing provider scoreform satisfies the active Core contract.",
        "Publication provider concord satisfies the active Core contract.",
        "Publication provider quillan satisfies the active Core contract.",
        "Publication provider scoreform satisfies the active Core contract.",
    )
    missing = tuple(fragment for fragment in required if fragment not in output)
    if missing:
        raise CombinedSuiteSmokeError(
            "Configured doctor output is missing expected integration evidence: "
            + ", ".join(missing)
        )


def _qualified_release_tool_wheel(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise CombinedSuiteSmokeError(
            f"Release-tool wheel does not exist: {resolved}"
        )
    try:
        contract = load_release_tooling_contract()
        if len(contract.tools) != 1:
            raise CombinedSuiteSmokeError(
                "Release-tooling contract must declare exactly one tool."
            )
        tool = contract.tools[0]
        if tool.distribution != "pip":
            raise CombinedSuiteSmokeError(
                "Release-tooling contract does not qualify pip."
            )
        verify_release_tool_wheel(tool, resolved)
    except (ArtifactVerificationError, ReleaseToolingError) as error:
        raise CombinedSuiteSmokeError(
            f"Release-tool wheel failed exact authentication: {error}"
        ) from error
    return resolved


def _install_exact_composition(
    python: Path,
    suite_wheel: Path,
    core_wheel: Path,
    application_wheels: Sequence[Path],
    release_tool_wheel: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--force-reinstall",
            str(release_tool_wheel),
        ],
        cwd=cwd,
        env=env,
        timeout=300.0,
    )
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-input",
            str(core_wheel),
            str(suite_wheel),
            *(str(path) for path in application_wheels),
        ],
        cwd=cwd,
        env=env,
        timeout=300.0,
    )
    _run(
        [str(python), "-m", "pip", "check"],
        cwd=cwd,
        env=env,
    )


def smoke_test(
    suite_wheel: Path,
    artifact_dir: Path,
    release_tool_wheel: Path,
) -> None:
    """Run one continuous installed-suite acceptance through restore."""
    suite_wheel = suite_wheel.resolve()
    artifact_dir = artifact_dir.resolve()
    if not suite_wheel.is_file():
        raise CombinedSuiteSmokeError(f"Suite wheel does not exist: {suite_wheel}")
    if not artifact_dir.is_dir():
        raise CombinedSuiteSmokeError(
            f"Artifact directory does not exist: {artifact_dir}"
        )
    release_tool_wheel = _qualified_release_tool_wheel(release_tool_wheel)

    source_package = Path(__file__).resolve().parents[1] / "paper_data_suite"
    _assert_no_sibling_private_imports(source_package)

    try:
        verify_artifact_directory(artifact_dir)
        applications = _application_expectations()
        core_wheel, application_wheels = _component_wheels(
            artifact_dir,
            applications,
        )
    except (
        OSError,
        CompatibilityManifestError,
        ArtifactVerificationError,
    ) as error:
        raise CombinedSuiteSmokeError(
            f"Qualified component artifact verification failed: {error}"
        ) from error

    with tempfile.TemporaryDirectory(prefix="pds-combined-suite-smoke-") as temporary:
        temp_root = Path(temporary)
        environment = temp_root / "venv"
        run_directory = temp_root / "run"
        user_home = temp_root / "user"
        command_bin = temp_root / "command-bin"
        workspace = temp_root / "workspace"
        roster_source = temp_root / "synthetic-roster.csv"
        run_directory.mkdir()
        user_home.mkdir()
        command_bin.mkdir()
        roster_source.write_text(
            "class_id,student_id,last_name,first_name,period\n"
            "eng10,student001,Synthetic,Alex,2\n"
            "eng10,student002,Synthetic,Jordan,2\n",
            encoding="utf-8",
            newline="",
        )

        venv.EnvBuilder(with_pip=True).create(environment)
        python = _venv_python(environment)
        install_env = _installation_environment()
        _install_exact_composition(
            python,
            suite_wheel,
            core_wheel,
            application_wheels,
            release_tool_wheel,
            cwd=run_directory,
            env=install_env,
        )

        _write_test_command(command_bin, "pdftoppm")
        foreign_markers: dict[str, Path] = {}
        for application in applications:
            marker = temp_root / f"foreign-{application.component_id}-ran.txt"
            _write_test_command(
                command_bin,
                application.console_script,
                marker=marker,
            )
            foreign_markers[application.component_id] = marker

        command_env = _command_environment(
            install_env,
            user_home=user_home,
            path_prefix=command_bin,
        )
        _assert_installed_versions(
            python,
            applications,
            cwd=run_directory,
            env=command_env,
        )
        _assert_installed_import_roots(
            python,
            environment,
            applications,
            cwd=run_directory,
            env=command_env,
        )

        scripts = _scripts_directory(
            python,
            cwd=run_directory,
            env=command_env,
        )
        pds = scripts / ("pds.exe" if os.name == "nt" else "pds")
        if not pds.is_file():
            raise CombinedSuiteSmokeError(
                f"Installed pds launcher does not exist: {pds}"
            )

        version = _run([str(pds), "--version"], cwd=run_directory, env=command_env)
        manifest = load_release_compatibility_manifest()
        expected_version = f"pds {manifest.suite.version}"
        if version.stdout.strip() != expected_version:
            raise CombinedSuiteSmokeError(
                f"Installed pds version is unexpected: {version.stdout.strip()!r}"
            )
        print("PASS install")

        settings_path = _suite_settings_path(user_home, command_env)
        default_workspace = user_home / "Paper Data Suite"
        initial_doctor = _run(
            [str(pds), "doctor"],
            cwd=run_directory,
            env=command_env,
        )
        if "No accessible workspace currently exists" not in initial_doctor.stdout:
            raise CombinedSuiteSmokeError(
                "Initial doctor did not report missing workspace state."
            )
        if workspace.exists() or default_workspace.exists():
            raise CombinedSuiteSmokeError(
                "Initial doctor created workspace state."
            )
        if settings_path.exists():
            raise CombinedSuiteSmokeError("Initial doctor created suite settings.")
        _assert_clean_directory(run_directory)
        print("PASS initial doctor")

        workspace_setup = _run(
            [str(pds), "workspace", "setup"],
            cwd=run_directory,
            env=command_env,
            input_text=f"2\n{workspace}\nUSE\n",
        )
        for fragment in (
            "Workspace ready",
            "The workspace selection was saved through Core.",
            "No school year or classroom setup was changed.",
        ):
            if fragment not in workspace_setup.stdout:
                raise CombinedSuiteSmokeError(
                    f"Workspace setup output is missing: {fragment}"
                )
        if not workspace.is_dir():
            raise CombinedSuiteSmokeError(
                "Workspace setup did not create the workspace."
            )
        _assert_clean_directory(run_directory)
        print("PASS workspace setup")

        pre_setup_doctor = _run(
            [str(pds), "doctor"],
            cwd=run_directory,
            env=command_env,
        )
        if (
            "The resolved workspace exists and is writable."
            not in pre_setup_doctor.stdout
        ):
            raise CombinedSuiteSmokeError(
                "Doctor did not recognize the selected synthetic workspace."
            )
        if "No active school year is configured" not in pre_setup_doctor.stdout:
            raise CombinedSuiteSmokeError(
                "Doctor did not preserve expected pre-classroom warning state."
            )

        applied = _run(
            [str(pds), "setup"],
            cwd=run_directory,
            env=command_env,
            input_text=_first_setup_input(roster_source),
        )
        required_setup = (
            "Shared setup review",
            "2026-2027: OPEN",
            "eng10: CREATE",
            "Incoming students: 2",
            "Additions: 2",
            "Pack njsls_ela_2023: INSTALL",
            "q1 | quarter | Quarter 1",
            "Plan is eligible for final APPLY.",
            "Shared classroom setup complete",
            "school_year:OPEN:2026-2027",
            "class:CREATE:eng10",
            "roster:CREATE:eng10",
        )
        missing_setup = tuple(
            fragment for fragment in required_setup if fragment not in applied.stdout
        )
        if missing_setup:
            raise CombinedSuiteSmokeError(
                "Combined classroom setup output is incomplete: "
                + ", ".join(missing_setup)
            )
        _assert_core_setup_state(
            python,
            roster_source,
            workspace,
            cwd=run_directory,
            env=command_env,
        )
        _assert_clean_directory(run_directory)
        print("PASS classroom setup")

        before_rerun = _snapshot_tree(workspace)
        rerun = _run(
            [str(pds), "setup"],
            cwd=run_directory,
            env=command_env,
            input_text=_rerun_setup_input(roster_source),
        )
        if "No persistent changes were needed" not in rerun.stdout:
            raise CombinedSuiteSmokeError(
                "Combined setup rerun did not report already-current state."
            )
        after_rerun = _snapshot_tree(workspace)
        _assert_tree_unchanged(before_rerun, after_rerun, operation="setup rerun")
        _assert_core_setup_state(
            python,
            roster_source,
            workspace,
            cwd=run_directory,
            env=command_env,
        )
        print("PASS setup rerun")

        configured_doctor = _run(
            [str(pds), "doctor"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_configured_doctor(configured_doctor.stdout)
        if settings_path.exists():
            raise CombinedSuiteSmokeError(
                "Doctor created suite recent-component settings."
            )
        print("PASS configured doctor")

        before_shell_only = _snapshot_tree(workspace)
        inventory = _run(
            [str(pds), "modules"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_module_inventory(inventory.stdout, applications)
        if settings_path.exists():
            raise CombinedSuiteSmokeError(
                "Module discovery created suite recent-component settings."
            )
        print("PASS module discovery")

        for application in applications:
            launched = _run(
                [str(pds), "launch", application.component_id],
                cwd=run_directory,
                env=command_env,
                input_text="q\n",
                timeout=60.0,
            )
            if application.display_name.casefold() not in launched.stdout.casefold():
                raise CombinedSuiteSmokeError(
                    f"{application.display_name} menu did not identify itself."
                )
            if foreign_markers[application.component_id].exists():
                raise CombinedSuiteSmokeError(
                    f"pds launch used foreign {application.console_script} from PATH."
                )
            print(f"PASS launch {application.component_id}")

        settings_show = _run(
            [str(pds), "settings", "show"],
            cwd=run_directory,
            env=command_env,
        )
        if "Suite settings" not in settings_show.stdout:
            raise CombinedSuiteSmokeError(
                "Installed settings show output is unexpected."
            )
        expected_recent = tuple(
            application.component_id for application in reversed(applications)
        )
        _assert_settings_document(settings_path, expected_recent=expected_recent)
        try:
            settings_path.resolve().relative_to(workspace.resolve())
        except ValueError:
            pass
        else:
            raise CombinedSuiteSmokeError(
                "Suite settings were written inside workspace."
            )

        _run(
            [str(pds), "settings", "clear-recent"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_settings_document(settings_path, expected_recent=())
        after_shell_only = _snapshot_tree(workspace)
        _assert_tree_unchanged(
            before_shell_only,
            after_shell_only,
            operation="doctor/modules/launch/settings",
        )
        _assert_clean_directory(run_directory)
        print("PASS suite settings and ownership boundary")

        _seed_opaque_workspace_fixture(workspace)
        custody_snapshot = _snapshot_tree(workspace)
        saved_workspace_before = _run(
            [str(pds), "workspace", "show"],
            cwd=run_directory,
            env=command_env,
        ).stdout
        print("PASS opaque custody fixture")

        backup_parent = temp_root / "backups"
        backup_result = _run(
            [
                str(pds),
                "backup",
                "create",
                "--destination",
                str(backup_parent),
                "--yes",
            ],
            cwd=run_directory,
            env=command_env,
        )
        if "Workspace backup complete" not in backup_result.stdout:
            raise CombinedSuiteSmokeError(
                "Combined backup creation did not report verified completion."
            )
        backup_root = _find_completed_backup(backup_parent)
        manifest_path = backup_root / "manifest.json"
        payload_root = backup_root / "workspace"
        if not manifest_path.is_file() or not payload_root.is_dir():
            raise CombinedSuiteSmokeError(
                "Combined backup lacks manifest.json plus workspace payload."
            )
        _assert_tree_unchanged(
            custody_snapshot,
            _snapshot_tree(workspace),
            operation="backup creation",
        )
        if _snapshot_tree(payload_root) != custody_snapshot:
            raise CombinedSuiteSmokeError(
                "Combined backup payload does not match source workspace bytes."
            )
        manifest_hash = _assert_backup_manifest(
            manifest_path,
            backup_root=backup_root,
            source_snapshot=custody_snapshot,
        )
        if f"Manifest SHA-256: {manifest_hash}" not in backup_result.stdout:
            raise CombinedSuiteSmokeError(
                "Backup completion reported the wrong manifest digest."
            )
        print("PASS backup create")

        verify_result = _run(
            [str(pds), "backup", "verify", str(backup_root)],
            cwd=run_directory,
            env=command_env,
        )
        if "Workspace backup verified" not in verify_result.stdout:
            raise CombinedSuiteSmokeError(
                "Combined backup verification did not report success."
            )
        if f"Manifest SHA-256: {manifest_hash}" not in verify_result.stdout:
            raise CombinedSuiteSmokeError(
                "Backup verification reported the wrong manifest digest."
            )
        _assert_tree_unchanged(
            custody_snapshot,
            _snapshot_tree(workspace),
            operation="backup verification",
        )
        print("PASS backup verify")

        restore_destination = temp_root / "recovery" / "restored-workspace"
        if restore_destination.exists():
            raise CombinedSuiteSmokeError(
                "Synthetic restore destination unexpectedly exists before restore."
            )
        restore_result = _run(
            [
                str(pds),
                "backup",
                "restore",
                str(backup_root),
                "--destination",
                str(restore_destination),
                "--yes",
            ],
            cwd=run_directory,
            env=command_env,
        )
        if "Workspace restore complete" not in restore_result.stdout:
            raise CombinedSuiteSmokeError(
                "Combined restore did not report verified completion."
            )
        if "was not selected automatically" not in restore_result.stdout:
            raise CombinedSuiteSmokeError(
                "Combined restore omitted the workspace-selection boundary."
            )
        if not restore_destination.is_dir():
            raise CombinedSuiteSmokeError(
                "Combined restore did not publish the requested destination."
            )
        if (restore_destination / "manifest.json").exists():
            raise CombinedSuiteSmokeError(
                "Restore injected backup manifest.json into workspace state."
            )
        if (restore_destination / "workspace").exists():
            raise CombinedSuiteSmokeError(
                "Restore introduced an extra nested workspace directory."
            )
        if _snapshot_tree(restore_destination) != custody_snapshot:
            raise CombinedSuiteSmokeError(
                "Restored workspace does not match the source byte-for-byte."
            )
        _assert_tree_unchanged(
            custody_snapshot,
            _snapshot_tree(workspace),
            operation="alternate restore",
        )
        saved_workspace_after = _run(
            [str(pds), "workspace", "show"],
            cwd=run_directory,
            env=command_env,
        ).stdout
        if saved_workspace_after != saved_workspace_before:
            raise CombinedSuiteSmokeError(
                "Alternate restore changed Core's saved workspace selection."
            )
        incomplete_restore = tuple(
            restore_destination.parent.glob(".*.pds-restore.incomplete-*")
        )
        if incomplete_restore:
            raise CombinedSuiteSmokeError(
                "Successful combined restore left incomplete staging state."
            )
        print("PASS restore")

        restored_env = _workspace_override_environment(
            command_env,
            restore_destination,
        )
        _assert_core_setup_state(
            python,
            roster_source,
            restore_destination,
            cwd=run_directory,
            env=restored_env,
        )
        restored_doctor = _run(
            [str(pds), "doctor"],
            cwd=run_directory,
            env=restored_env,
        )
        _assert_configured_doctor(restored_doctor.stdout)
        if _run(
            [str(pds), "workspace", "show"],
            cwd=run_directory,
            env=command_env,
        ).stdout != saved_workspace_before:
            raise CombinedSuiteSmokeError(
                "Restored-state inspection changed the saved original workspace."
            )
        _assert_clean_directory(run_directory)
        print("PASS restored workspace")

        print("Combined installed-suite acceptance passed.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Install one exact PDS composition and exercise one continuous "
            "synthetic workspace workflow."
        )
    )
    parser.add_argument("suite_wheel", type=Path)
    parser.add_argument(
        "--artifact-dir",
        required=True,
        type=Path,
        help="directory containing the exact release wheels declared by the manifest",
    )
    parser.add_argument(
        "--release-tool-wheel",
        required=True,
        type=Path,
        help="exact authenticated release-tooling wheel (pip)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        smoke_test(
            args.suite_wheel,
            args.artifact_dir,
            args.release_tool_wheel,
        )
    except CombinedSuiteSmokeError as error:
        print(f"Combined installed-suite acceptance failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
