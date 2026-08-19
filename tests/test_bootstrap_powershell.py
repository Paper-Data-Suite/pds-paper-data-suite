from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_windows.ps1"


def test_powershell_contract_authenticates_before_inspection_install() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    hash_index = text.index("Get-FileHash -Algorithm SHA256")
    install_index = text.index("Install authenticated suite for inspection")
    assert hash_index < install_index
    assert "--no-deps" in text
    assert "--no-index" in text
    assert "--upgrade" not in text
    assert "[switch]$Apply" in text
    assert "[switch]$Yes" in text


def test_powershell_contract_uses_guarded_temp_cleanup() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    assert '"pds-suite-bootstrap-"' in text
    assert "Refusing cleanup outside OS temp" in text
    assert "Refusing protected cleanup" in text
    assert "ReparsePoint" in text
    assert "Remove-Item -LiteralPath $Resolved -Recurse -Force" in text
    assert "Remove-Item -LiteralPath $EnvironmentPath" not in text
    assert "Remove-Item -LiteralPath $ArtifactDirectory" not in text


def test_powershell_artifacts_come_from_authenticated_requirements() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    requirements_index = text.index("'artifact-requirements'")
    download_index = text.index("Invoke-WebRequest")
    verification_index = text.index("'verify-artifacts'")
    assert requirements_index < download_index < verification_index
    assert "-Uri $Requirement.url" in text
    assert "-OutFile $ArtifactPath" in text
    assert "/releases/download/" not in text
    assert "/latest/" not in text
    assert "pds-constraints.txt" in text


def test_caller_artifact_directory_is_reuse_only() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    assert "[string]$ArtifactDirectory" in text
    assert "caller-supplied read-only directory" in text
    assert "Required local artifact is missing" in text
    assert "$UsingCallerArtifactDirectory" in text


@pytest.mark.parametrize("host", ["powershell", "pwsh"])
def test_script_parses_on_available_powershell_host(host: str) -> None:
    executable = shutil.which(host)
    if executable is None:
        pytest.skip(f"{host} is not available")

    command = (
        "$ErrorActionPreference='Stop'; "
        f"[scriptblock]::Create((Get-Content -Raw -LiteralPath '{_SCRIPT}')) "
        "| Out-Null"
    )
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_apply_contract_authenticates_before_target_creation() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    verify_index = text.index("'verify-artifacts'")
    create_target_index = text.index('"Create target environment"')
    assert verify_index < create_target_index
    assert "'-m', 'venv', $TargetEnvironment" in text


def test_apply_contract_installs_in_safe_pds_order() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    core_index = text.index('"Install exact authenticated Core"')
    suite_index = text.index('"Install exact authenticated suite"')
    optional_index = text.index(
        '"Install exact authenticated $($PackagePlan.display_name)"'
    )
    pip_check_index = text.index('"pip check"')
    finalize_index = text.index("'finalize-environment'")

    assert core_index < suite_index < optional_index
    assert optional_index < pip_check_index < finalize_index
    assert "'--no-deps'" in text
    assert "'--no-index'" in text
    assert "'--constraint', $ConstraintsPath" in text
    assert "--upgrade" not in text


def test_marker_finalization_occurs_only_after_pip_check() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    pip_check_index = text.index('Invoke-Required "pip check"')
    finalize_index = text.index("'finalize-environment'")
    success_index = text.index('"Bootstrap completed successfully."')

    assert pip_check_index < finalize_index < success_index




def test_apply_cleanup_requires_per_run_ownership_sentinel() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    assert "Initialize-OwnedTargetRoot" in text
    assert ".pds-bootstrap-owned.tmp" in text
    assert "TargetOwnershipNonce" in text
    assert "Refusing target cleanup without ownership proof" in text
    assert "Refusing target cleanup without ownership sentinel" in text
    assert "invalid ownership sentinel" in text
    assert "Target ownership sentinel changed before completion" in text


def test_target_path_contract_rejects_repository_and_system_overlap() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    safety_index = text.index("Assert-SafeTargetEnvironmentPath $TargetEnvironment")
    plan_index = text.index("$CommonPlanArguments = @(")
    assert safety_index < plan_index
    assert "Refusing protected target environment path" in text
    assert "Refusing system target environment path" in text
    assert "Refusing repository-overlapping target environment path" in text
    assert "Refusing reparse-point target environment path" in text
    assert '$CurrentPhase = "target-validation"' in text


@pytest.mark.parametrize("host", ["powershell", "pwsh"])
def test_wrong_suite_hash_stops_before_python_or_target_mutation(
    host: str,
    tmp_path: Path,
) -> None:
    executable = shutil.which(host)
    if executable is None:
        pytest.skip(f"{host} is not available")

    fake_wheel = tmp_path / "paper_data_suite-0.1.0.dev0-py3-none-any.whl"
    fake_wheel.write_bytes(b"not an authenticated suite wheel")
    target = tmp_path / "must-not-exist"

    def powershell_literal(value: object) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    common_arguments = [
        "-SuiteWheel",
        str(fake_wheel),
        "-SuiteWheelSha256",
        "0" * 64,
        "-PythonExe",
        "definitely-not-a-python-command",
        "-EnvironmentPath",
        str(target),
    ]
    if host == "powershell":
        invocation = " ".join(
            [
                "&",
                powershell_literal(_SCRIPT),
                "-SuiteWheel",
                powershell_literal(fake_wheel),
                "-SuiteWheelSha256",
                powershell_literal("0" * 64),
                "-PythonExe",
                powershell_literal("definitely-not-a-python-command"),
                "-EnvironmentPath",
                powershell_literal(target),
            ]
        )
        command = [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            invocation,
        ]
        expected_returncode = 1
    else:
        command = [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(_SCRIPT),
            *common_arguments,
        ]
        expected_returncode = 4

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == expected_returncode
    assert "Suite wheel SHA-256 mismatch:" in result.stderr
    assert "No suite code was executed" in result.stderr
    assert "definitely-not-a-python-command" not in result.stderr
    assert not target.exists()


def test_new_target_failure_cleanup_is_guarded_and_existing_target_is_preserved(
) -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    assert "$CreatedTargetEnvironment" in text
    assert "Remove-ValidatedCreatedTargetEnvironment" in text
    assert "Refusing protected target environment path" in text
    assert "Refusing reparse-point target cleanup root" in text
    assert (
        "$CreatedTargetEnvironment -and -not $InstallationSucceeded"
        in text
    )


def test_success_output_includes_activation_and_direct_launch_guidance() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    assert 'Scripts\\Activate.ps1' in text
    assert 'Write-Host "Activate:' in text
    assert "Scripts\\pds.exe" in text
    assert '"Launch: "' in text
