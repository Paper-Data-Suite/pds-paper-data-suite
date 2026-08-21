"""Smoke-test installed backup verification and alternate-location restore."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class WorkspaceRestoreSmokeTestError(RuntimeError):
    """Raised when installed backup verification/restore acceptance fails."""


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    """Independent file facts used by the smoke test."""

    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class TreeSnapshot:
    """Independent directory/file snapshot for source/restore comparison."""

    directories: tuple[str, ...]
    files: tuple[FileSnapshot, ...]


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
        raise WorkspaceRestoreSmokeTestError(
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
    installed = Path(result.stdout.strip()).resolve()
    try:
        installed.relative_to(environment.resolve())
    except ValueError as error:
        raise WorkspaceRestoreSmokeTestError(
            "Smoke test imported paper_data_suite outside the isolated environment: "
            f"{installed}"
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
                raise WorkspaceRestoreSmokeTestError(
                    f"Synthetic smoke tree unexpectedly contains a symlink: {path}"
                )
            directories.append(_relative(root, path))
        for name in filenames:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise WorkspaceRestoreSmokeTestError(
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


def _assert_clean_directory(path: Path) -> None:
    contents = tuple(path.iterdir())
    if contents:
        raise WorkspaceRestoreSmokeTestError(
            "Workspace-restore smoke created working-directory artifacts: "
            + ", ".join(item.name for item in contents)
        )


def _assert_verify_help(output: str) -> None:
    normalized = " ".join(output.split()).replace("- ", "-")
    required = (
        "manifest",
        "SHA-256",
        "without modifying",
        "runtime-compatibility",
    )
    missing = [fragment for fragment in required if fragment not in normalized]
    if missing:
        raise WorkspaceRestoreSmokeTestError(
            "Installed verify help is missing expected content: "
            + ", ".join(missing)
        )


def _assert_restore_help(output: str) -> None:
    normalized = " ".join(output.split())
    required = (
        "--destination",
        "--yes",
        "must not already exist",
        "not selected automatically",
    )
    missing = [fragment for fragment in required if fragment not in normalized]
    if missing:
        raise WorkspaceRestoreSmokeTestError(
            "Installed restore help is missing expected content: "
            + ", ".join(missing)
        )


def _find_completed_backup(parent: Path) -> Path:
    completed = tuple(
        path
        for path in parent.iterdir()
        if path.is_dir() and path.name.startswith("pds-workspace-backup-")
    )
    if len(completed) != 1:
        raise WorkspaceRestoreSmokeTestError(
            f"Expected one completed backup, found {len(completed)}."
        )
    return completed[0]


def _assert_no_sibling_apps(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    code = """
from importlib import metadata

unexpected = (
    "pds-concord",
    "quillan",
    "scoreform",
    "pds-vitrine",
    "pds-meridian",
    "pds-portia",
)
installed = {
    item.metadata.get("Name", "").lower()
    for item in metadata.distributions()
}
present = [name for name in unexpected if name in installed]
if present:
    raise SystemExit("unexpected sibling PDS distributions: " + ", ".join(present))
""".strip()
    _run([str(python), "-c", code], cwd=cwd, env=env)


def smoke_test_workspace_restore_wheel(
    suite_wheel: Path,
    core_wheel: Path,
) -> None:
    """Exercise installed verify/restore beside the exact Core wheel only."""
    suite_wheel = suite_wheel.resolve()
    core_wheel = core_wheel.resolve()
    if not suite_wheel.is_file():
        raise WorkspaceRestoreSmokeTestError(
            f"Suite wheel does not exist: {suite_wheel}"
        )
    if not core_wheel.is_file():
        raise WorkspaceRestoreSmokeTestError(
            f"Core wheel does not exist: {core_wheel}"
        )

    with tempfile.TemporaryDirectory(prefix="pds-restore-smoke-") as temporary:
        temp_root = Path(temporary)
        environment = temp_root / "venv"
        run_directory = temp_root / "run"
        user_home = temp_root / "user"
        workspace = temp_root / "workspace"
        backup_parent = temp_root / "backups"
        restore_destination = temp_root / "recovery" / "restored-workspace"
        cancel_destination = temp_root / "cancelled" / "restored-workspace"
        existing_destination = temp_root / "existing-restore"
        tampered_parent = temp_root / "tampered"
        incomplete_parent = temp_root / "incomplete"
        run_directory.mkdir()
        user_home.mkdir()

        venv.EnvBuilder(with_pip=True).create(environment)
        python = _venv_python(environment)
        env = _isolated_command_env(os.environ, user_home=user_home)

        _run(
            [str(python), "-m", "pip", "install", "--no-deps", str(core_wheel)],
            cwd=run_directory,
            env=env,
        )
        _run(
            [str(python), "-m", "pip", "install", "--no-deps", str(suite_wheel)],
            cwd=run_directory,
            env=env,
        )
        _run(
            [str(python), "-m", "pip", "check"],
            cwd=run_directory,
            env=env,
        )
        _assert_installed_suite_location(
            python,
            environment=environment,
            cwd=run_directory,
            env=env,
        )
        _assert_no_sibling_apps(python, cwd=run_directory, env=env)

        scripts = _scripts_directory(
            python,
            cwd=run_directory,
            env=env,
        )
        launcher = scripts / ("pds.exe" if os.name == "nt" else "pds")
        if not launcher.is_file():
            raise WorkspaceRestoreSmokeTestError(
                f"Installed pds launcher does not exist: {launcher}"
            )

        module_verify_help = _run(
            [
                str(python),
                "-m",
                "paper_data_suite",
                "backup",
                "verify",
                "--help",
            ],
            cwd=run_directory,
            env=env,
        )
        console_restore_help = _run(
            [str(launcher), "backup", "restore", "--help"],
            cwd=run_directory,
            env=env,
        )
        _assert_verify_help(module_verify_help.stdout)
        _assert_restore_help(console_restore_help.stdout)

        _run(
            [str(launcher), "workspace", "set", str(workspace)],
            cwd=run_directory,
            env=env,
        )
        (workspace / "future-module" / "empty").mkdir(parents=True)
        (workspace / "future-module" / "opaque.bin").write_bytes(
            b"\x00\xffsynthetic"
        )
        (workspace / ".hidden").write_text(
            "synthetic hidden",
            encoding="utf-8",
        )
        (workspace / "zero.dat").write_bytes(b"")
        sensitive = workspace / "student-private.csv"
        sensitive.write_text("synthetic-only", encoding="utf-8")
        source_before = _snapshot_tree(workspace)
        workspace_show_before = _run(
            [str(launcher), "workspace", "show"],
            cwd=run_directory,
            env=env,
        ).stdout

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
            env=env,
        )
        if "Workspace backup complete" not in created.stdout:
            raise WorkspaceRestoreSmokeTestError(
                "Installed backup creation did not report completion."
            )
        backup_root = _find_completed_backup(backup_parent)
        manifest_path = backup_root / "manifest.json"
        manifest_hash = _sha256(manifest_path)

        module_verified = _run(
            [
                str(python),
                "-m",
                "paper_data_suite",
                "backup",
                "verify",
                str(backup_root),
            ],
            cwd=run_directory,
            env=env,
        )
        console_verified = _run(
            [str(launcher), "backup", "verify", str(backup_root)],
            cwd=run_directory,
            env=env,
        )
        for output in (module_verified.stdout, console_verified.stdout):
            if "Workspace backup verified" not in output:
                raise WorkspaceRestoreSmokeTestError(
                    "Installed backup verify did not report success."
                )
            if f"Manifest SHA-256: {manifest_hash}" not in output:
                raise WorkspaceRestoreSmokeTestError(
                    "Installed verify reported the wrong manifest SHA-256."
                )
            if sensitive.name in output:
                raise WorkspaceRestoreSmokeTestError(
                    "Normal verify output leaked a payload filename."
                )

        cancelled = _run(
            [
                str(python),
                "-m",
                "paper_data_suite",
                "backup",
                "restore",
                str(backup_root),
                "--destination",
                str(cancel_destination),
            ],
            cwd=run_directory,
            env=env,
            input_text="Q\n",
        )
        if "Workspace restore cancelled" not in cancelled.stdout:
            raise WorkspaceRestoreSmokeTestError(
                "Installed module-form restore cancellation was not reported."
            )
        if cancel_destination.exists():
            raise WorkspaceRestoreSmokeTestError(
                "Restore cancellation created the final destination."
            )

        active_refusal = _run(
            [
                str(launcher),
                "backup",
                "restore",
                str(backup_root),
                "--destination",
                str(workspace),
                "--yes",
            ],
            cwd=run_directory,
            env=env,
            expected_returncode=1,
        )
        if "Restore refused" not in active_refusal.stderr:
            raise WorkspaceRestoreSmokeTestError(
                "Restore did not clearly refuse the active workspace destination."
            )

        restored = _run(
            [
                str(launcher),
                "backup",
                "restore",
                str(backup_root),
                "--destination",
                str(restore_destination),
                "--yes",
            ],
            cwd=run_directory,
            env=env,
        )
        if "Workspace restore complete" not in restored.stdout:
            raise WorkspaceRestoreSmokeTestError(
                "Installed restore did not report verified completion."
            )
        if "was not selected automatically" not in restored.stdout:
            raise WorkspaceRestoreSmokeTestError(
                "Restore completion omitted the workspace-selection boundary."
            )
        if sensitive.name in restored.stdout:
            raise WorkspaceRestoreSmokeTestError(
                "Normal restore output leaked a payload filename."
            )
        if not restore_destination.is_dir():
            raise WorkspaceRestoreSmokeTestError(
                "Restore did not publish the explicit destination."
            )
        if (restore_destination / "manifest.json").exists():
            raise WorkspaceRestoreSmokeTestError(
                "Restore injected backup manifest.json into the workspace."
            )
        if _snapshot_tree(restore_destination) != source_before:
            raise WorkspaceRestoreSmokeTestError(
                "Restored workspace bytes/tree do not match the source snapshot."
            )
        if _snapshot_tree(workspace) != source_before:
            raise WorkspaceRestoreSmokeTestError(
                "Verification/restore modified the active source workspace."
            )

        workspace_show_after = _run(
            [str(launcher), "workspace", "show"],
            cwd=run_directory,
            env=env,
        ).stdout
        if workspace_show_after != workspace_show_before:
            raise WorkspaceRestoreSmokeTestError(
                "Restore changed Core's selected workspace."
            )

        existing_destination.mkdir()
        sentinel = existing_destination / "sentinel.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        existing_refusal = _run(
            [
                str(launcher),
                "backup",
                "restore",
                str(backup_root),
                "--destination",
                str(existing_destination),
                "--yes",
            ],
            cwd=run_directory,
            env=env,
            expected_returncode=1,
        )
        if "Restore refused" not in existing_refusal.stderr:
            raise WorkspaceRestoreSmokeTestError(
                "Existing restore destination was not clearly refused."
            )
        if sentinel.read_text(encoding="utf-8") != "preserve":
            raise WorkspaceRestoreSmokeTestError(
                "Existing-destination refusal modified the sentinel."
            )

        incomplete_parent.mkdir()
        incomplete = incomplete_parent / (
            f".{backup_root.name}.incomplete-synthetic"
        )
        shutil.copytree(backup_root, incomplete)
        incomplete_result = _run(
            [str(launcher), "backup", "verify", str(incomplete)],
            cwd=run_directory,
            env=env,
            expected_returncode=1,
        )
        if "Backup verification failed" not in incomplete_result.stderr:
            raise WorkspaceRestoreSmokeTestError(
                "Incomplete backup was not clearly refused."
            )

        tampered_parent.mkdir()
        tampered = tampered_parent / backup_root.name
        shutil.copytree(backup_root, tampered)
        tampered_file = tampered / "workspace" / "future-module" / "opaque.bin"
        original = tampered_file.read_bytes()
        tampered_file.write_bytes(bytes((value ^ 1) for value in original))
        tampered_result = _run(
            [
                str(python),
                "-m",
                "paper_data_suite",
                "backup",
                "verify",
                str(tampered),
            ],
            cwd=run_directory,
            env=env,
            expected_returncode=1,
        )
        if "Backup verification failed" not in tampered_result.stderr:
            raise WorkspaceRestoreSmokeTestError(
                "Tampered backup was not clearly refused."
            )

        incomplete_staging = tuple(
            restore_destination.parent.glob(".*.pds-restore.incomplete-*")
        )
        if incomplete_staging:
            raise WorkspaceRestoreSmokeTestError(
                "Successful restore left incomplete staging state."
            )
        _assert_clean_directory(run_directory)


def build_parser() -> argparse.ArgumentParser:
    """Build the installed backup verification/restore smoke-test parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Install the built Paper Data Suite wheel beside the exact Core wheel "
            "and exercise backup verification plus alternate-location restore."
        )
    )
    parser.add_argument("suite_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run installed backup verification/restore acceptance."""
    arguments = build_parser().parse_args(argv)
    try:
        smoke_test_workspace_restore_wheel(
            arguments.suite_wheel,
            arguments.core_wheel,
        )
    except WorkspaceRestoreSmokeTestError as error:
        print(f"Workspace restore smoke test failed: {error}", file=sys.stderr)
        return 1
    print("Workspace restore wheel smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
