"""Smoke-test the built Paper Data Suite wheel in a clean virtual environment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from packaging.utils import canonicalize_name

FORBIDDEN_SIBLING_DISTRIBUTIONS = frozenset(
    {
        "scoreform",
        "quillan",
        "pds-concord",
        "pds-meridian",
        "pds-vitrine",
        "pds-portia",
    }
)


class SmokeTestError(RuntimeError):
    """Raised when the clean-wheel smoke test fails."""


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SmokeTestError(
            "Command failed "
            f"({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _wheel_version(path: Path) -> str:
    with zipfile.ZipFile(path) as wheel:
        metadata_members = tuple(
            name
            for name in wheel.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        if len(metadata_members) != 1:
            raise SmokeTestError("Suite wheel has ambiguous METADATA.")
        text = wheel.read(metadata_members[0]).decode("utf-8")

    for line in text.splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    raise SmokeTestError("Suite wheel METADATA has no Version field.")


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
        raise SmokeTestError(
            f"Foundation command created working-directory artifacts: {names}"
        )


def _assert_no_sibling_distributions(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    code = (
        "import importlib.metadata as m, json; "
        "print(json.dumps(sorted("
        "d.metadata['Name'] for d in m.distributions() "
        "if d.metadata.get('Name'))))"
    )
    result = _run([str(python), "-c", code], cwd=cwd, env=env)
    installed = {
        canonicalize_name(name)
        for name in cast(list[str], json.loads(result.stdout))
    }
    forbidden = sorted(installed & FORBIDDEN_SIBLING_DISTRIBUTIONS)
    if forbidden:
        raise SmokeTestError(
            "Clean smoke environment contains sibling PDS distributions: "
            + ", ".join(forbidden)
        )


def _assert_import_boundary(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
    expected_version: str,
) -> None:
    code = """
import json
import sys
import paper_data_suite

tracked = [
    "pds_core",
    "scoreform",
    "quillan",
    "concord",
    "meridian",
    "vitrine",
]
print(json.dumps({
    "version": paper_data_suite.__version__,
    "loaded": {name: name in sys.modules for name in tracked},
}))
""".strip()
    result = _run([str(python), "-c", code], cwd=cwd, env=env)
    payload = cast(dict[str, object], json.loads(result.stdout))
    if payload.get("version") != expected_version:
        raise SmokeTestError("Installed package version does not match wheel.")

    loaded = cast(dict[str, bool], payload.get("loaded"))
    unexpectedly_loaded = sorted(name for name, value in loaded.items() if value)
    if unexpectedly_loaded:
        raise SmokeTestError(
            "Package import crossed owner boundaries: "
            + ", ".join(unexpectedly_loaded)
        )
    _assert_clean_directory(cwd)


def _assert_installed_package_location(
    python: Path,
    *,
    environment: Path,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    code = (
        "from pathlib import Path; import paper_data_suite; "
        "print(Path(paper_data_suite.__file__).resolve())"
    )
    result = _run([str(python), "-c", code], cwd=cwd, env=env)
    installed_path = Path(result.stdout.strip()).resolve()
    try:
        installed_path.relative_to(environment.resolve())
    except ValueError as error:
        raise SmokeTestError(
            "Smoke test imported paper_data_suite outside the isolated environment: "
            f"{installed_path}"
        ) from error
    _assert_clean_directory(cwd)


def _assert_installed_compatibility_manifest(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
    expected_version: str,
) -> None:
    code = """
import json
import socket
import sys
import urllib.request

def blocked_network(*args, **kwargs):
    raise AssertionError("compatibility loading attempted network access")

socket.create_connection = blocked_network
urllib.request.urlopen = blocked_network
urllib.request.urlretrieve = blocked_network

from paper_data_suite.compatibility import load_release_compatibility_manifest

manifest = load_release_compatibility_manifest()
tracked = [
    "pds_core",
    "scoreform",
    "quillan",
    "concord",
    "meridian",
    "vitrine",
]
print(json.dumps({
    "suite_version": manifest.suite.version,
    "component_ids": [
        component.component_id for component in manifest.components
    ],
    "loaded": {name: name in sys.modules for name in tracked},
}))
""".strip()
    result = _run([str(python), "-c", code], cwd=cwd, env=env)
    payload = cast(dict[str, object], json.loads(result.stdout))

    if payload.get("suite_version") != expected_version:
        raise SmokeTestError(
            "Installed compatibility manifest version does not match wheel."
        )
    if payload.get("component_ids") != [
        "concord",
        "core",
        "quillan",
        "scoreform",
        "vitrine",
    ]:
        raise SmokeTestError(
            "Installed compatibility manifest component set changed."
        )

    loaded = cast(dict[str, bool], payload.get("loaded"))
    unexpectedly_loaded = sorted(
        name for name, value in loaded.items() if value
    )
    if unexpectedly_loaded:
        raise SmokeTestError(
            "Compatibility loading imported PDS owner packages: "
            + ", ".join(unexpectedly_loaded)
        )
    _assert_clean_directory(cwd)


def _assert_doctor_output(output: str) -> None:
    required = (
        "Paper Data Suite doctor",
        "Runtime",
        "Suite",
        "Packages",
        "Dependencies",
        "Entry points",
        "Core",
        "Workspace",
        "Core registry",
        "Providers",
        "Modules",
        "Overall",
        "No accessible workspace currently exists at the resolved path.",
        "Routing/publication provider compatibility has reduced diagnostic fidelity.",
        "Shared module-reported readiness is not available.",
    )
    missing = [fragment for fragment in required if fragment not in output]
    if missing:
        raise SmokeTestError(
            "Installed doctor output is missing expected content: "
            + ", ".join(missing)
        )


def _assert_doctor_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    missing_workspace: Path,
) -> None:
    if missing_workspace.exists():
        raise SmokeTestError(
            f"Synthetic absent workspace unexpectedly exists: {missing_workspace}"
        )
    result = _run(command, cwd=cwd, env=env)
    _assert_doctor_output(result.stdout)
    if missing_workspace.exists():
        raise SmokeTestError("pds doctor created the synthetic absent workspace.")
    _assert_clean_directory(cwd)


def _assert_doctor_no_network(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
    missing_workspace: Path,
) -> None:
    code = """
import socket
import urllib.request


def blocked_network(*args, **kwargs):
    raise AssertionError("pds doctor attempted network access")


socket.create_connection = blocked_network
urllib.request.urlopen = blocked_network
urllib.request.urlretrieve = blocked_network

from paper_data_suite.cli import main
raise SystemExit(main(("doctor",)))
""".strip()
    _assert_doctor_command(
        [str(python), "-c", code],
        cwd=cwd,
        env=env,
        missing_workspace=missing_workspace,
    )


def smoke_test(suite_wheel: Path, core_wheel: Path) -> None:
    """Install and exercise the suite wheel beside only Core."""
    suite_wheel = suite_wheel.resolve()
    core_wheel = core_wheel.resolve()
    if not suite_wheel.is_file():
        raise SmokeTestError(f"Suite wheel does not exist: {suite_wheel}")
    if not core_wheel.is_file():
        raise SmokeTestError(f"Core wheel does not exist: {core_wheel}")

    expected_version = _wheel_version(suite_wheel)

    with tempfile.TemporaryDirectory(prefix="pds-suite-smoke-") as temporary:
        temp_root = Path(temporary)
        environment = temp_root / "venv"
        run_directory = temp_root / "run"
        missing_workspace = run_directory / "synthetic-missing-workspace"
        run_directory.mkdir()

        venv.EnvBuilder(with_pip=True).create(environment)
        python = _venv_python(environment)

        command_env = dict(os.environ)
        command_env["PYTHONDONTWRITEBYTECODE"] = "1"
        command_env["PYTHONNOUSERSITE"] = "1"
        command_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        command_env["PIP_NO_INDEX"] = "1"
        command_env["PDS_WORKSPACE_ROOT"] = str(missing_workspace)
        command_env.pop("PYTHONPATH", None)

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                str(core_wheel),
            ],
            cwd=run_directory,
            env=command_env,
        )
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                str(suite_wheel),
            ],
            cwd=run_directory,
            env=command_env,
        )
        _run(
            [str(python), "-m", "pip", "check"],
            cwd=run_directory,
            env=command_env,
        )

        _assert_no_sibling_distributions(
            python, cwd=run_directory, env=command_env
        )
        _assert_import_boundary(
            python,
            cwd=run_directory,
            env=command_env,
            expected_version=expected_version,
        )
        _assert_installed_package_location(
            python,
            environment=environment,
            cwd=run_directory,
            env=command_env,
        )
        _assert_installed_compatibility_manifest(
            python,
            cwd=run_directory,
            env=command_env,
            expected_version=expected_version,
        )

        module_version = _run(
            [
                str(python),
                "-m",
                "paper_data_suite",
                "--version",
            ],
            cwd=run_directory,
            env=command_env,
        )
        if module_version.stdout.strip() != f"pds {expected_version}":
            raise SmokeTestError("Unexpected module --version output.")
        _assert_clean_directory(run_directory)

        module_help = _run(
            [str(python), "-m", "paper_data_suite", "--help"],
            cwd=run_directory,
            env=command_env,
        )
        if "usage: pds" not in module_help.stdout:
            raise SmokeTestError("Module help does not identify pds.")
        _assert_clean_directory(run_directory)

        _assert_doctor_command(
            [str(python), "-m", "paper_data_suite", "doctor"],
            cwd=run_directory,
            env=command_env,
            missing_workspace=missing_workspace,
        )
        _assert_doctor_no_network(
            python,
            cwd=run_directory,
            env=command_env,
            missing_workspace=missing_workspace,
        )

        scripts = _scripts_directory(
            python, cwd=run_directory, env=command_env
        )
        launcher = scripts / ("pds.exe" if os.name == "nt" else "pds")
        if not launcher.is_file():
            raise SmokeTestError(
                f"Installed pds launcher does not exist: {launcher}"
            )

        console_version = _run(
            [str(launcher), "--version"],
            cwd=run_directory,
            env=command_env,
        )
        if console_version.stdout.strip() != f"pds {expected_version}":
            raise SmokeTestError("Unexpected installed pds --version output.")
        _assert_clean_directory(run_directory)

        console_help = _run(
            [str(launcher), "--help"],
            cwd=run_directory,
            env=command_env,
        )
        if "usage: pds" not in console_help.stdout:
            raise SmokeTestError("Installed pds help does not identify pds.")
        _assert_clean_directory(run_directory)

        _assert_doctor_command(
            [str(launcher), "doctor"],
            cwd=run_directory,
            env=command_env,
            missing_workspace=missing_workspace,
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the installed-wheel smoke-test argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Install the built Paper Data Suite wheel beside an exact Core wheel "
            "and exercise installed package/CLI acceptance outside the source tree."
        )
    )
    parser.add_argument("suite_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the built-wheel smoke test from the command line."""
    arguments = build_parser().parse_args(argv)
    try:
        smoke_test(arguments.suite_wheel, arguments.core_wheel)
    except SmokeTestError as error:
        print(f"Smoke test failed: {error}", file=sys.stderr)
        return 1
    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
