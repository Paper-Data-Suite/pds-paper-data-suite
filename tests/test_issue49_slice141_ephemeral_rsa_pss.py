"""Slice 141: cryptographic tests must never imply publisher authority."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "native/windows/bootstrap/qualify_sandbox_os_parent_ci.ps1"
SIGNER = ROOT / "native/windows/bootstrap/sandbox_ephemeral_signer.ps1"
VERIFIER = ROOT / "native/windows/bootstrap/sandbox_ephemeral_signature_verify.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-sandbox-os-parent-denial.yml"
DOC = ROOT / "docs/architecture/issue-49-slice-141-ephemeral-rsa-pss-signed-artifact.md"
OLD = ROOT / "native/windows/bootstrap/sandbox_protected_payload_probe.ps1"


def admin() -> str:
    return ADMIN.read_text(encoding="utf-8")


def signer() -> str:
    return SIGNER.read_text(encoding="utf-8")


def verifier() -> str:
    return VERIFIER.read_text(encoding="utf-8")


def test_exact_assets_and_existing_staging() -> None:
    for file in (ADMIN, SIGNER, VERIFIER, WORKFLOW, DOC, OLD):
        assert file.is_file()
        assert 300 < file.stat().st_size < 35000


@pytest.mark.parametrize("source", (signer, verifier))
def test_ephemeral_windows_only_and_actual_admin_token(
    source: Callable[[], str],
) -> None:
    text = source()
    for snippet in (
        "GITHUB_ACTIONS",
        "RUNNER_OS",
        "RUNNER_ENVIRONMENT",
        "github-hosted",
        "WindowsIdentity]::GetCurrent()",
        "WindowsBuiltInRole]::Administrator",
        "IsInRole(",
    ):
        assert snippet in text
    assert text.index("RUNNER_ENVIRONMENT") < text.index("$payloadPath =")


def test_signer_requires_explicit_consent() -> None:
    text = signer()
    assert "EPHEMERAL_RSA_PSS_TEST_ONLY" in text
    assert "$Acknowledge -cne" in text
    assert text.index("Acknowledge -cne") < text.index("WriteAllBytes(")


@pytest.mark.parametrize("source", (signer, verifier))
def test_os_known_parent_and_random_exact_sandbox(source: Callable[[], str]) -> None:
    text = source()
    for snippet in (
        "[Environment+SpecialFolder]::CommonApplicationData",
        "[IO.Path]::GetFullPath($SandboxRoot)",
        "pds-suite49-osparent-sbx-",
        "'^[0-9a-f]{32}$'",
        "root -cne $SandboxRoot",
        "FileAttributes]::ReparsePoint",
    ):
        assert snippet in text
    assert "$env:ProgramData" not in text
    assert "$env:TEMP" not in text


def test_two_fixed_protected_outputs_no_private_key_file() -> None:
    text = signer()
    for snippet in (
        "protected-state\\service-state",
        "test-only-publisher-public.spki",
        "test-only-payload.detached.sig",
        "[IO.File]::WriteAllBytes($publicPath, $public)",
        "[IO.File]::WriteAllBytes($signaturePath, $signature)",
        "ExportSubjectPublicKeyInfo()",
        "private_key_written_to_disk = $false",
    ):
        assert snippet in text
    assert "ExportPkcs8PrivateKey" not in text
    assert "ExportRSAPrivateKey" not in text
    assert "WriteAllBytes($private" not in text


def test_domain_separation_and_pss_sha256_agree() -> None:
    for text in (signer(), verifier()):
        assert "PDS_SUITE49_EPHEMERAL_TEST_SIGNATURE_V1" in text
        assert "PDS_SUITE49_SYNTHETIC_PAYLOAD_V1_NOT_A_SIGNED_RELEASE" in text
        assert "Pss" in text
        assert "SHA256" in text
    assert "[Security.Cryptography.RSA]::Create(3072)" in signer()
    assert "SignData(" in signer()
    assert "VerifyData(" in verifier()


def test_verifier_requires_exact_spki_consumption() -> None:
    text = verifier()
    for snippet in (
        "ImportSubjectPublicKeyInfo(spki, out int consumed)",
        "consumed != spki.Length",
        "rsa.KeySize != 3072",
        "signature.Length != 384",
        "RSASignaturePadding.Pss",
    ):
        assert snippet in text


def test_independent_process_verification_is_required() -> None:
    text = admin()
    for snippet in (
        "sandbox_ephemeral_signer.ps1",
        "sandbox_ephemeral_signature_verify.ps1",
        "& $pwsh -NoProfile -NonInteractive -File $signer",
        "& $pwsh -NoProfile -NonInteractive -File $verifier",
        "signedCode -ne 2",
        "verifiedCode -ne 2",
    ):
        assert snippet in text
    assert text.index("-File $signer") < text.index("-File $verifier")


def test_three_cryptographic_tamper_negative_controls() -> None:
    text = verifier()
    for snippet in (
        "[PdsEphemeralRsaPss141]::Verify($public, $payload, $signature)",
        "Verify($public, $badPayload, $signature)",
        "Verify($public, $payload, $badSignature)",
        "Verify($wrongKey, $payload, $signature)",
        "-bxor 1",
        "[Security.Cryptography.RSA]::Create(3072)",
    ):
        assert snippet in text


@pytest.mark.parametrize(
    "field",
    (
        "valid_signature_verified",
        "changed_payload_rejected",
        "changed_signature_rejected",
        "substituted_public_key_rejected",
    ),
)
def test_validator_explicitly_checks_verification_results(field: str) -> None:
    assert f"verifyReport.{field} -cne $true" in admin()
    assert f"{field} = $true" in verifier()


@pytest.mark.parametrize(
    "field",
    (
        "independent_publisher_provenance_verified",
        "trusted_release_artifact_verified",
        "production_rollback_protection_verified",
        "authorized_to_install",
    ),
)
def test_result_cannot_assert_production_authority(field: str) -> None:
    assert f"{field} = $false" in verifier()
    assert f"verifyReport.{field} -cne $false" in admin()


def test_signer_cannot_assert_publisher_authentication() -> None:
    text = signer()
    assert "independently_authenticated_publisher = $false" in text
    assert "trusted_production_key_provisioned = $false" in text
    assert "private_key_written_to_disk = $false" in text
    assert "authorized_to_install = $false" in text


def test_admin_readback_checks_public_signature_and_payload() -> None:
    text = admin()
    for snippet in (
        "Get-Acl -LiteralPath $trustPublicPath",
        "Get-Acl -LiteralPath $trustSigPath",
        "[IO.File]::ReadAllBytes($trustPublicPath)",
        "[IO.File]::ReadAllBytes($trustSigPath)",
        "Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256",
        "SLICE141_EPHEMERAL_RSA_PSS_VALID_AND_TAMPERS_REJECTED",
    ):
        assert snippet in text


def test_signer_replay_and_file_acl_checks() -> None:
    text = signer()
    assert "Test-Path -LiteralPath $publicPath" in text
    assert "Test-Path -LiteralPath $signaturePath" in text
    assert "test key files have unexpected ACLs" in text
    assert "S-1-5-18" in text
    assert "S-1-5-32-544" in text
    assert "[IO.File]::WriteAllBytes" in text


def test_workflow_triggers_all_new_crypto_files() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for snippet in (
        "sandbox_ephemeral_signer.ps1",
        "sandbox_ephemeral_signature_verify.ps1",
        "qualify_sandbox_os_parent_ci.ps1",
        "runs-on: windows-2022",
        "contents: read",
    ):
        assert snippet in text
    assert "schedule:" not in text


@pytest.mark.parametrize(
    "forbidden",
    (
        "New-Service",
        "Start-Service",
        "Remove-Item ",
        "Remove-LocalUser",
        "Set-Service",
        "Set-AuthenticodeSignature",
        "WriteAllBytes($private",
        "ExportRSAPrivateKey",
        "ProgramData\\Paper Data Suite",
        "publisher-pin-v1.json",
        "Invoke-Expression",
    ),
)
def test_crypto_scripts_never_write_real_production_state(forbidden: str) -> None:
    assert forbidden not in signer() + verifier()


def test_documentation_precise_nonproduction_limits() -> None:
    text = DOC.read_text(encoding="utf-8").lower()
    for snippet in (
        "ephemeral",
        "rsa-pss",
        "sha-256",
        "tampering",
        "not pds publisher authentication",
        "not an authenticode signing",
        "private key is never exported to disk",
        "externally pinned",
        "no cleanup",
        "no production",
    ):
        assert snippet in text
