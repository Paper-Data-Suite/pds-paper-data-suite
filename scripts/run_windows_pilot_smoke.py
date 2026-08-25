"""Run the final Windows synthetic teacher-pilot smoke for v0.1.0."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from paper_data_suite._version import __version__
from paper_data_suite.compatibility import load_release_compatibility_manifest
from paper_data_suite.release_tooling import load_release_tooling_contract

EXPECTED_CANDIDATE_VERSION = "0.1.0.dev0"


class WindowsPilotSmokeError(RuntimeError):
    """Raised when the Windows pilot smoke cannot prove one required gate."""


@dataclass(frozen=True, slots=True)
class SmokeStep:
    """One repository-owned installed-wheel acceptance command."""

    label: str
    script: str
    args: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float = 900.0,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=None if env is None else dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WindowsPilotSmokeError(
            f"Command could not complete: {' '.join(command)}: {error}"
        ) from error
    if result.returncode != 0:
        stdout = result.stdout[-4000:]
        stderr = result.stderr[-4000:]
        raise WindowsPilotSmokeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout tail:\n{stdout}\nstderr tail:\n{stderr}"
        )
    return result


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, destination)
    except (OSError, urllib.error.URLError) as error:
        raise WindowsPilotSmokeError(
            f"Could not download declared release artifact: {destination.name}"
        ) from error


def _download_release_artifacts(
    component_dir: Path,
    release_dir: Path,
) -> tuple[Path, ...]:
    manifest = load_release_compatibility_manifest()
    component_paths: list[Path] = []
    for component in manifest.components:
        release = component.release
        url = (
            f"https://github.com/{component.repository}"
            f"/releases/download/{release.tag}/{release.wheel}"
        )
        component_path = component_dir / release.wheel
        _download(url, component_path)
        observed = _sha256(component_path)
        if observed != release.sha256:
            raise WindowsPilotSmokeError(
                f"Component artifact SHA-256 mismatch: {release.wheel}"
            )
        shutil.copy2(component_path, release_dir / release.wheel)
        component_paths.append(component_path)

    tooling = load_release_tooling_contract()
    for tool in tooling.tools:
        tool_path = release_dir / tool.wheel
        _download(tool.url, tool_path)
        if _sha256(tool_path) != tool.sha256:
            raise WindowsPilotSmokeError(
                f"Release-tool artifact SHA-256 mismatch: {tool.wheel}"
            )
    return tuple(component_paths)


def _core_wheel(component_dir: Path) -> Path:
    manifest = load_release_compatibility_manifest()
    rows = tuple(
        component
        for component in manifest.components
        if component.component_id == "core"
    )
    if len(rows) != 1:
        raise WindowsPilotSmokeError(
            "Compatibility manifest does not declare exactly one Core."
        )
    path = component_dir / rows[0].release.wheel
    if not path.is_file():
        raise WindowsPilotSmokeError("Exact Core wheel is missing.")
    return path


def _candidate_wheel(dist_dir: Path) -> Path:
    wheels = tuple(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise WindowsPilotSmokeError(
            f"Expected one candidate suite wheel; found {len(wheels)}."
        )
    return wheels[0].resolve()


def _isolated_env(user_home: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.upper() in {"PYTHONPATH", "PDS_WORKSPACE_ROOT"}:
            env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["HOME"] = str(user_home)
    env["USERPROFILE"] = str(user_home)
    env["LOCALAPPDATA"] = str(user_home / "AppData" / "Local")
    env["APPDATA"] = str(user_home / "AppData" / "Roaming")
    env["XDG_CONFIG_HOME"] = str(user_home / ".config")
    return env


def _powershell() -> str:
    candidate = shutil.which("powershell.exe") or shutil.which("powershell")
    if candidate is None:
        raise WindowsPilotSmokeError("Windows PowerShell is unavailable.")
    return candidate


def _managed_bootstrap_smoke(
    *,
    repo: Path,
    suite_wheel: Path,
    suite_sha256: str,
    release_dir: Path,
    temp_root: Path,
) -> tuple[str, str]:
    target = temp_root / "managed-env"
    user_home = temp_root / "managed-user"
    run_dir = temp_root / "managed-run"
    workspace = temp_root / "managed-workspace"
    user_home.mkdir()
    run_dir.mkdir()

    bootstrap = repo / "scripts" / "bootstrap_windows.ps1"
    command = (
        _powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(bootstrap),
        "-SuiteWheel",
        str(suite_wheel),
        "-SuiteWheelSha256",
        suite_sha256,
        "-EnvironmentPath",
        str(target),
        "-AllComponents",
        "-ArtifactDirectory",
        str(release_dir),
        "-Apply",
        "-Yes",
    )
    _run(command, cwd=run_dir, timeout=1200.0)

    python = target / "Scripts" / "python.exe"
    pds = target / "Scripts" / "pds.exe"
    if not python.is_file() or not pds.is_file():
        raise WindowsPilotSmokeError(
            "Managed bootstrap did not create installed Python/pds launchers."
        )

    env = _isolated_env(user_home)
    _run((str(python), "-m", "pip", "check"), cwd=run_dir, env=env)

    version = _run((str(pds), "--version"), cwd=run_dir, env=env).stdout.strip()
    if version != f"pds {EXPECTED_CANDIDATE_VERSION}":
        raise WindowsPilotSmokeError(
            f"Unexpected managed suite version: {version!r}"
        )

    _run(
        (str(pds), "workspace", "set", str(workspace)),
        cwd=run_dir,
        env=env,
    )
    doctor = _run(
        (str(pds), "doctor", "--workspace", str(workspace)),
        cwd=run_dir,
        env=env,
    )
    if "No blockers" not in doctor.stdout:
        raise WindowsPilotSmokeError(
            "Managed doctor did not report a no-blocker result."
        )
    modules = _run((str(pds), "modules"), cwd=run_dir, env=env)
    if modules.stdout.count("Status: available") < 4:
        raise WindowsPilotSmokeError(
            "Managed module inventory did not expose all qualified applications."
        )

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        raise WindowsPilotSmokeError(
            "Host Windows PATH does not expose pdftoppm for real pilot discovery."
        )
    poppler = _run((pdftoppm, "-v"), cwd=run_dir, env=env)
    poppler_text = (poppler.stdout + poppler.stderr).strip()
    if not poppler_text:
        poppler_text = "pdftoppm executed successfully"

    if tuple(run_dir.iterdir()):
        raise WindowsPilotSmokeError(
            "Managed pilot commands created working-directory residue."
        )
    return str(Path(pdftoppm).resolve()), poppler_text.splitlines()[0]


def _workflow_steps(
    suite_wheel: Path,
    core_wheel: Path,
    component_dir: Path,
    release_tool_wheel: Path,
) -> tuple[SmokeStep, ...]:
    suite = str(suite_wheel)
    core = str(core_wheel)
    artifacts = str(component_dir)
    release_tool = str(release_tool_wheel)
    return (
        SmokeStep(
            "base installed wheel",
            "smoke_test_wheel.py",
            (suite, core, release_tool),
        ),
        SmokeStep(
            "workspace workflow",
            "smoke_test_workspace_wheel.py",
            (suite, core),
        ),
        SmokeStep(
            "shared classroom setup",
            "smoke_test_classroom_setup_wheel.py",
            (suite, core),
        ),
        SmokeStep(
            "workspace backup",
            "smoke_test_workspace_backup_wheel.py",
            (suite, core),
        ),
        SmokeStep(
            "workspace restore",
            "smoke_test_workspace_restore_wheel.py",
            (suite, core),
        ),
        SmokeStep(
            "suite settings",
            "smoke_test_settings_wheels.py",
            (suite, "--artifact-dir", artifacts),
        ),
        SmokeStep(
            "application inventory and launch",
            "smoke_test_application_wheels.py",
            (suite, "--artifact-dir", artifacts),
        ),
        SmokeStep(
            "combined installed suite",
            "smoke_test_combined_suite_wheels.py",
            (
                suite,
                "--artifact-dir",
                artifacts,
                "--release-tool-wheel",
                release_tool,
            ),
        ),
    )


def run_windows_pilot(repo: Path) -> dict[str, object]:
    repo = repo.resolve()
    if os.name != "nt" or sys.platform != "win32":
        raise WindowsPilotSmokeError(
            "The final v0.1.0 pilot smoke must run on Windows."
        )
    if __version__ != EXPECTED_CANDIDATE_VERSION:
        raise WindowsPilotSmokeError(
            f"Pilot smoke requires {EXPECTED_CANDIDATE_VERSION}; "
            f"running {__version__}."
        )

    with tempfile.TemporaryDirectory(
        prefix="pds-v010-windows-pilot-"
    ) as temporary:
        temp_root = Path(temporary)
        component_dir = temp_root / "components"
        release_dir = temp_root / "release-artifacts"
        dist_dir = temp_root / "dist"
        component_dir.mkdir()
        release_dir.mkdir()
        dist_dir.mkdir()

        print("[1/6] Downloading exact declared release artifacts...")
        _download_release_artifacts(component_dir, release_dir)

        print("[2/6] Building and validating candidate distributions...")
        _run(
            (
                sys.executable,
                "-m",
                "build",
                "--outdir",
                str(dist_dir),
            ),
            cwd=repo,
        )
        artifacts = tuple(sorted(dist_dir.iterdir()))
        if not artifacts:
            raise WindowsPilotSmokeError(
                "Candidate build produced no distribution artifacts."
            )
        _run(
            (
                sys.executable,
                "-m",
                "twine",
                "check",
                *(str(path) for path in artifacts),
            ),
            cwd=repo,
        )
        suite_wheel = _candidate_wheel(dist_dir)
        suite_sha256 = _sha256(suite_wheel)
        _run(
            (
                sys.executable,
                str(repo / "scripts" / "check_package.py"),
                str(suite_wheel),
            ),
            cwd=repo,
        )

        print("[3/6] Authenticating component and release-tool artifacts...")
        _run(
            (
                sys.executable,
                str(repo / "scripts" / "verify_compatibility_artifacts.py"),
                "--artifact-dir",
                str(release_dir),
            ),
            cwd=repo,
        )

        print("[4/6] Running real Windows managed-bootstrap/doctor smoke...")
        pdftoppm_path, poppler_version = _managed_bootstrap_smoke(
            repo=repo,
            suite_wheel=suite_wheel,
            suite_sha256=suite_sha256,
            release_dir=release_dir,
            temp_root=temp_root,
        )

        print("[5/6] Running installed teacher-workflow smoke suite...")
        core = _core_wheel(component_dir)
        tooling = load_release_tooling_contract()
        if len(tooling.tools) != 1:
            raise WindowsPilotSmokeError(
                "Release-tooling contract must declare exactly one tool."
            )
        release_tool_wheel = release_dir / tooling.tools[0].wheel
        if not release_tool_wheel.is_file():
            raise WindowsPilotSmokeError(
                "Qualified release-tooling wheel is missing."
            )

        passed_steps: list[str] = []
        for step in _workflow_steps(
            suite_wheel,
            core,
            component_dir,
            release_tool_wheel,
        ):
            print(f"  - {step.label}...")
            _run(
                (
                    sys.executable,
                    str(repo / "scripts" / step.script),
                    *step.args,
                ),
                cwd=repo,
                timeout=1200.0,
            )
            passed_steps.append(step.label)

        print("[6/6] Finalizing pilot evidence...")
        return {
            "record_type": "paper_data_suite_windows_pilot_smoke",
            "contract_version": "1",
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "suite_version": __version__,
            "suite_wheel": suite_wheel.name,
            "suite_wheel_sha256": suite_sha256,
            "core_wheel": core.name,
            "pdftoppm_path": pdftoppm_path,
            "pdftoppm_version": poppler_version,
            "managed_bootstrap": "PASS",
            "managed_doctor": "PASS",
            "qualified_applications": "PASS",
            "workflow_steps": passed_steps,
            "result": "PASS",
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_windows_pilot(args.repo)
    except WindowsPilotSmokeError as error:
        print(f"WINDOWS PILOT SMOKE: FAIL\n{error}", file=sys.stderr)
        return 1

    print(json.dumps(evidence, indent=2, sort_keys=True))
    print("WINDOWS PILOT SMOKE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
