"""Smoke-test installed whole-workspace backup creation from built wheels."""

from __future__ import annotations

import argparse
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
from typing import cast


class WorkspaceBackupSmokeTestError(RuntimeError):
    """Raised when installed workspace-backup acceptance fails."""


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    """Independent file facts used by the smoke test."""

    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class TreeSnapshot:
    """Independent directory/file snapshot used to compare source and payload."""

    directories: tuple[str, ...]
    files: tuple[FileSnapshot, ...]


_MANIFEST_KEYS = frozenset(
    {
        "record_type",
        "schema_version",
        "backup_id",
        "created_at",
        "suite_version",
        "core_version",
        "payload_root",
        "hash_algorithm",
        "directory_count",
        "file_count",
        "total_bytes",
        "directories",
        "files",
        "exclusions",
    }
)
_FILE_KEYS = frozenset({"path", "size", "sha256"})


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_text: str | None = None,
    expected_returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != expected_returncode:
        raise WorkspaceBackupSmokeTestError(
            "Command returned an unexpected status "
            f"({result.returncode}, expected {expected_returncode}): "
            f"{' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
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


def _isolated_command_env(
    base_env: Mapping[str, str],
    *,
    user_home: Path,
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
    env["APPDATA"] = str(user_home / "AppData" / "Roaming")
    env["XDG_CONFIG_HOME"] = str(user_home / ".config")
    return env


def _assert_installed_suite_location(
    python: Path,
    *,
    environment: Path,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    result = _run(
        [
            str(python),
            "-c",
            (
                "from pathlib import Path; import paper_data_suite; "
                "print(Path(paper_data_suite.__file__).resolve())"
            ),
        ],
        cwd=cwd,
        env=env,
    )
    installed_path = Path(result.stdout.strip()).resolve()
    try:
        installed_path.relative_to(environment.resolve())
    except ValueError as error:
        raise WorkspaceBackupSmokeTestError(
            "Smoke test imported paper_data_suite outside the isolated environment: "
            f"{installed_path}"
        ) from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _snapshot_tree(root: Path) -> TreeSnapshot:
    directories: list[str] = []
    files: list[FileSnapshot] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirnames.sort()
        filenames.sort()
        for name in dirnames:
            path = current_path / name
            if path.is_symlink():
                raise WorkspaceBackupSmokeTestError(
                    f"Synthetic smoke tree unexpectedly contains a symlink: {path}"
                )
            directories.append(_relative(root, path))
        for name in filenames:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise WorkspaceBackupSmokeTestError(
                    f"Synthetic smoke tree contains unsupported file entry: {path}"
                )
            files.append(
                FileSnapshot(
                    path=_relative(root, path),
                    size=path.stat().st_size,
                    sha256=_sha256(path),
                )
            )
    return TreeSnapshot(
        directories=tuple(sorted(directories)),
        files=tuple(sorted(files, key=lambda item: item.path)),
    )


def _json_object(path: Path) -> dict[str, object]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkspaceBackupSmokeTestError(
            f"Could not read backup manifest as UTF-8 JSON: {path}"
        ) from error
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise WorkspaceBackupSmokeTestError("Backup manifest is not a JSON object.")
    return cast(dict[str, object], raw)


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise WorkspaceBackupSmokeTestError(f"{label} is not a string array.")
    return tuple(cast(list[str], value))


def _manifest_file_entries(value: object) -> tuple[FileSnapshot, ...]:
    if not isinstance(value, list):
        raise WorkspaceBackupSmokeTestError("Manifest files is not an array.")
    result: list[FileSnapshot] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or any(not isinstance(key, str) for key in item):
            raise WorkspaceBackupSmokeTestError(
                f"Manifest files[{index}] is not an object."
            )
        mapping = cast(dict[str, object], item)
        if frozenset(mapping) != _FILE_KEYS:
            raise WorkspaceBackupSmokeTestError(
                f"Manifest files[{index}] has unexpected fields."
            )
        path = mapping.get("path")
        size = mapping.get("size")
        sha256 = mapping.get("sha256")
        if not isinstance(path, str):
            raise WorkspaceBackupSmokeTestError(
                f"Manifest files[{index}].path is invalid."
            )
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise WorkspaceBackupSmokeTestError(
                f"Manifest files[{index}].size is invalid."
            )
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise WorkspaceBackupSmokeTestError(
                f"Manifest files[{index}].sha256 is invalid."
            )
        result.append(FileSnapshot(path=path, size=size, sha256=sha256))
    return tuple(result)


def _contains_string(value: object, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, list):
        return any(_contains_string(item, needle) for item in value)
    if isinstance(value, dict):
        return any(_contains_string(item, needle) for item in value.values())
    return False


def _assert_manifest_matches_source(
    manifest_path: Path,
    *,
    source_root: Path,
    final_root: Path,
    source: TreeSnapshot,
) -> None:
    manifest = _json_object(manifest_path)
    if _contains_string(manifest, str(source_root.resolve())):
        raise WorkspaceBackupSmokeTestError(
            "Portable manifest leaked the absolute source workspace path."
        )
    if frozenset(manifest) != _MANIFEST_KEYS:
        raise WorkspaceBackupSmokeTestError("Backup manifest fields are unexpected.")
    expected_scalars = {
        "record_type": "pds_workspace_backup_manifest",
        "schema_version": "1",
        "backup_id": final_root.name,
        "payload_root": "workspace",
        "hash_algorithm": "sha256",
    }
    for key, expected in expected_scalars.items():
        if manifest.get(key) != expected:
            raise WorkspaceBackupSmokeTestError(
                f"Unexpected manifest {key}: {manifest.get(key)!r}"
            )
    for key in ("created_at", "suite_version", "core_version"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value:
            raise WorkspaceBackupSmokeTestError(f"Manifest {key} is invalid.")
    if manifest.get("exclusions") != []:
        raise WorkspaceBackupSmokeTestError("Manifest exclusions must be empty in v1.")

    directories = _string_list(manifest.get("directories"), "Manifest directories")
    files = _manifest_file_entries(manifest.get("files"))
    if directories != source.directories:
        raise WorkspaceBackupSmokeTestError(
            "Manifest directory inventory does not match the source tree."
        )
    if files != source.files:
        raise WorkspaceBackupSmokeTestError(
            "Manifest file inventory/hashes do not match the source tree."
        )
    if manifest.get("directory_count") != len(source.directories):
        raise WorkspaceBackupSmokeTestError("Manifest directory_count is incorrect.")
    if manifest.get("file_count") != len(source.files):
        raise WorkspaceBackupSmokeTestError("Manifest file_count is incorrect.")
    expected_bytes = sum(item.size for item in source.files)
    if manifest.get("total_bytes") != expected_bytes:
        raise WorkspaceBackupSmokeTestError("Manifest total_bytes is incorrect.")


def _assert_clean_directory(path: Path) -> None:
    contents = tuple(path.iterdir())
    if contents:
        raise WorkspaceBackupSmokeTestError(
            "Workspace-backup smoke created working-directory artifacts: "
            + ", ".join(item.name for item in contents)
        )


def _assert_help(output: str) -> None:
    normalized = " ".join(output.split())
    required = (
        "currently resolved Core workspace",
        "--destination",
        "--yes",
        "potentially sensitive data",
        "does not encrypt, upload, or cloud-sync",
    )
    missing = [fragment for fragment in required if fragment not in normalized]
    if missing:
        raise WorkspaceBackupSmokeTestError(
            "Installed backup help is missing expected content: " + ", ".join(missing)
        )


def _exercise_installed_collision(
    python: Path,
    *,
    destination: Path,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    code = """
from datetime import datetime, timezone
from pathlib import Path
import sys
from paper_data_suite.workspace_backup import (
    WorkspaceBackupCollisionError,
    backup_name,
    plan_workspace_backup,
)

destination = Path(sys.argv[1])
fixed = datetime(2026, 8, 20, 19, 1, 2, 345678, tzinfo=timezone.utc)
final_root = destination / backup_name(fixed)
final_root.mkdir(parents=True)
sentinel = final_root / "sentinel.txt"
sentinel.write_text("preserve", encoding="utf-8")
try:
    plan_workspace_backup(destination, clock=lambda: fixed)
except WorkspaceBackupCollisionError:
    pass
else:
    raise SystemExit("collision was not refused")
if sentinel.read_text(encoding="utf-8") != "preserve":
    raise SystemExit("collision modified the existing backup")
""".strip()
    _run(
        [str(python), "-c", code, str(destination)],
        cwd=cwd,
        env=env,
    )


def smoke_test_workspace_backup_wheel(
    suite_wheel: Path,
    core_wheel: Path,
) -> None:
    """Exercise installed whole-workspace backup creation beside exact Core."""
    suite_wheel = suite_wheel.resolve()
    core_wheel = core_wheel.resolve()
    if not suite_wheel.is_file():
        raise WorkspaceBackupSmokeTestError(
            f"Suite wheel does not exist: {suite_wheel}"
        )
    if not core_wheel.is_file():
        raise WorkspaceBackupSmokeTestError(f"Core wheel does not exist: {core_wheel}")

    with tempfile.TemporaryDirectory(prefix="pds-backup-smoke-") as temporary:
        temp_root = Path(temporary)
        environment = temp_root / "venv"
        run_directory = temp_root / "run"
        user_home = temp_root / "user"
        workspace = temp_root / "workspace"
        backup_parent = temp_root / "backups"
        cancel_parent = temp_root / "cancel-backups"
        collision_parent = temp_root / "collision-backups"
        run_directory.mkdir()
        user_home.mkdir()

        venv.EnvBuilder(with_pip=True).create(environment)
        python = _venv_python(environment)
        command_env = _isolated_command_env(os.environ, user_home=user_home)

        _run(
            [str(python), "-m", "pip", "install", "--no-deps", str(core_wheel)],
            cwd=run_directory,
            env=command_env,
        )
        _run(
            [str(python), "-m", "pip", "install", "--no-deps", str(suite_wheel)],
            cwd=run_directory,
            env=command_env,
        )
        _run(
            [str(python), "-m", "pip", "check"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_installed_suite_location(
            python,
            environment=environment,
            cwd=run_directory,
            env=command_env,
        )

        scripts = _scripts_directory(
            python,
            cwd=run_directory,
            env=command_env,
        )
        launcher = scripts / ("pds.exe" if os.name == "nt" else "pds")
        if not launcher.is_file():
            raise WorkspaceBackupSmokeTestError(
                f"Installed pds launcher does not exist: {launcher}"
            )

        module_help = _run(
            [
                str(python),
                "-m",
                "paper_data_suite",
                "backup",
                "create",
                "--help",
            ],
            cwd=run_directory,
            env=command_env,
        )
        console_help = _run(
            [str(launcher), "backup", "create", "--help"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_help(module_help.stdout)
        _assert_help(console_help.stdout)

        _run(
            [str(launcher), "workspace", "set", str(workspace)],
            cwd=run_directory,
            env=command_env,
        )
        (workspace / "classes" / "future-module" / "empty").mkdir(parents=True)
        (workspace / "classes" / "future-module" / "opaque.bin").write_bytes(
            b"\x00\xffsynthetic"
        )
        (workspace / ".hidden").write_text("synthetic hidden", encoding="utf-8")
        (workspace / "zero.dat").write_bytes(b"")
        sensitive_name = workspace / "classes" / "student-private.csv"
        sensitive_name.write_text("synthetic-only", encoding="utf-8")
        source_before = _snapshot_tree(workspace)

        cancelled = _run(
            [
                str(python),
                "-m",
                "paper_data_suite",
                "backup",
                "create",
                "--destination",
                str(cancel_parent),
            ],
            cwd=run_directory,
            env=command_env,
            input_text="Q\n",
        )
        if "No backup was created" not in cancelled.stdout:
            raise WorkspaceBackupSmokeTestError(
                "Installed module-form cancellation did not report no creation."
            )
        if cancel_parent.exists():
            raise WorkspaceBackupSmokeTestError(
                "Cancellation created the destination before confirmation."
            )

        inside = workspace / "backup-destination"
        refused = _run(
            [
                str(launcher),
                "backup",
                "create",
                "--destination",
                str(inside),
                "--yes",
            ],
            cwd=run_directory,
            env=command_env,
            expected_returncode=1,
        )
        if "Backup refused" not in refused.stderr:
            raise WorkspaceBackupSmokeTestError(
                "Installed backup did not clearly refuse an inside-workspace "
                "destination."
            )
        if inside.exists():
            raise WorkspaceBackupSmokeTestError(
                "Inside-workspace refusal created destination state."
            )

        created = _run(
            [
                str(launcher),
                "backup",
                "create",
                "--destination",
                str(backup_parent),
                "--yes",
            ],
            cwd=run_directory,
            env=command_env,
        )
        if "Workspace backup complete" not in created.stdout:
            raise WorkspaceBackupSmokeTestError(
                "Installed backup did not report verified completion."
            )
        if sensitive_name.name in created.stdout:
            raise WorkspaceBackupSmokeTestError(
                "Normal installed backup output leaked a payload filename."
            )

        completed = tuple(
            path
            for path in backup_parent.iterdir()
            if path.is_dir() and path.name.startswith("pds-workspace-backup-")
        )
        if len(completed) != 1:
            raise WorkspaceBackupSmokeTestError(
                f"Expected one completed backup, found {len(completed)}."
            )
        incomplete = tuple(backup_parent.glob(".*.incomplete-*"))
        if incomplete:
            raise WorkspaceBackupSmokeTestError(
                "Successful backup left incomplete staging state."
            )
        final_root = completed[0]
        manifest_path = final_root / "manifest.json"
        payload_root = final_root / "workspace"
        if not manifest_path.is_file() or not payload_root.is_dir():
            raise WorkspaceBackupSmokeTestError(
                "Completed backup does not contain manifest.json plus workspace/."
            )

        source_after = _snapshot_tree(workspace)
        if source_after != source_before:
            raise WorkspaceBackupSmokeTestError(
                "Backup creation modified the source workspace tree."
            )
        payload = _snapshot_tree(payload_root)
        if payload != source_before:
            raise WorkspaceBackupSmokeTestError(
                "Backup payload does not independently match source bytes/tree."
            )
        _assert_manifest_matches_source(
            manifest_path,
            source_root=workspace,
            final_root=final_root,
            source=source_before,
        )
        manifest_hash = _sha256(manifest_path)
        if f"Manifest SHA-256: {manifest_hash}" not in created.stdout:
            raise WorkspaceBackupSmokeTestError(
                "Completion output manifest SHA-256 does not match persisted bytes."
            )

        _exercise_installed_collision(
            python,
            destination=collision_parent,
            cwd=run_directory,
            env=command_env,
        )
        _assert_clean_directory(run_directory)


def build_parser() -> argparse.ArgumentParser:
    """Build the installed workspace-backup smoke-test parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Install the built Paper Data Suite wheel beside the exact Core wheel "
            "and exercise whole-workspace backup creation in an isolated profile."
        )
    )
    parser.add_argument("suite_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run installed whole-workspace backup acceptance from the command line."""
    arguments = build_parser().parse_args(argv)
    try:
        smoke_test_workspace_backup_wheel(
            arguments.suite_wheel,
            arguments.core_wheel,
        )
    except WorkspaceBackupSmokeTestError as error:
        print(f"Workspace backup smoke test failed: {error}", file=sys.stderr)
        return 1
    print("Workspace backup wheel smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
