"""Slice 142: coherent alternate-signing keys must fail session-bound pin checks.

This is TEST-ONLY, not publisher authentication or production trust anchoring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "native/windows/bootstrap/qualify_sandbox_os_parent_ci.ps1"
VERIFIER = ROOT / "native/windows/bootstrap/sandbox_ephemeral_signature_verify.ps1"
SIGNER = ROOT / "native/windows/bootstrap/sandbox_ephemeral_signer.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-sandbox-os-parent-denial.yml"
DOC = ROOT / "docs/architecture/issue-49-slice-142-session-key-pin.md"


def admin() -> str:
    return ADMIN.read_text(encoding="utf-8")


def verifier() -> str:
    return VERIFIER.read_text(encoding="utf-8")


def test_exact_sources_are_reviewable() -> None:
    for path in (ADMIN, VERIFIER, SIGNER, WORKFLOW, DOC):
        assert path.is_file()
        assert 300 < path.stat().st_size < 39000


def test_session_pin_is_captured_before_verifier_process() -> None:
    source = admin()
    for text in (
        "$publicBefore = [IO.File]::ReadAllBytes($trustPublicPath)",
        "$sessionPublicKeySha256 = [Convert]::ToHexString(",
        "[Security.Cryptography.SHA256]::HashData($publicBefore)",
        "-ExpectedPublicKeySha256 $sessionPublicKeySha256",
        "& $pwsh -NoProfile -NonInteractive -File $verifier",
    ):
        assert text in source
    assert source.index("$sessionPublicKeySha256 =") < source.index(
        "$verified = @(& $pwsh"
    )
    assert source.index("$signed = @(& $pwsh") < source.index(
        "$sessionPublicKeySha256 ="
    )


def test_verifier_requires_separately_supplied_exact_lowercase_digest() -> None:
    source = verifier()
    for text in (
        "[Parameter(Mandatory = $true)] [string] $ExpectedPublicKeySha256",
        "-cnotmatch '^[0-9a-f]{64}$'",
        "[Security.Cryptography.SHA256]::HashData($public)",
        "sessionPublicKeySha256 -cne $ExpectedPublicKeySha256",
        "candidate public key differs from session pin",
    ):
        assert text in source
    assert source.index("candidate public key differs from session pin") < (
        source.index("Add-Type -TypeDefinition")
    )


def test_pinned_crypto_compares_raw_hash_bytes_in_constant_time() -> None:
    source = verifier()
    for text in (
        "public static bool VerifyPinned(byte[] spki, byte[] payload",
        "Convert.FromHexString(expectedSha256)",
        "SHA256.HashData(spki)",
        "CryptographicOperations.FixedTimeEquals(expected, actual)",
        "return Verify(spki, payload, signature);",
        "catch (FormatException)",
    ):
        assert text in source
    assert source.index("FixedTimeEquals") < source.index(
        "return Verify(spki, payload, signature);"
    )


def test_positive_original_signature_and_pin_must_both_pass() -> None:
    source = verifier()
    assert "Verify($public, $payload, $signature)" in source
    assert "-not [PdsEphemeralRsaPss141]::VerifyPinned(" in source
    assert "$public, $payload, $signature, $ExpectedPublicKeySha256" in source


def test_changed_pin_fails_even_with_valid_signature() -> None:
    source = verifier()
    assert "VerifyPinned(" in source
    assert "('0' * 64)" in source
    assert "invalid session pin was accepted" in source


def test_alternate_key_has_valid_own_signature_positive_control() -> None:
    source = verifier()
    for text in (
        "[Security.Cryptography.RSA]::Create(3072)",
        "$wrongKey = $alternate.ExportSubjectPublicKeyInfo()",
        "$alternateSignature = $alternate.SignData(",
        "EPHEMERAL_TEST_SIGNATURE_V1",
        "Verify(" + "\n                $wrongKey, $payload, $alternateSignature)",
        "self-signed alternate-pair positive control failed",
    ):
        assert text in source


def test_alternate_valid_pair_denied_by_session_pin() -> None:
    source = verifier()
    for text in (
        "VerifyPinned(" + "\n                $wrongKey, $payload, $alternateSignature,",
        "$ExpectedPublicKeySha256))",
        "self-signed alternate key substituted across session pin",
    ):
        assert text in source


@pytest.mark.parametrize(
    "flag",
    (
        "session_public_key_sha256_match",
        "self_signed_alternate_key_pair_rejected_by_pin",
    ),
)
def test_admin_requires_new_positive_proofs(flag: str) -> None:
    assert f"{flag} = $true" in verifier()
    assert f"verifyReport.{flag} -cne $true" in admin()


@pytest.mark.parametrize(
    "flag",
    (
        "independently_provisioned_publisher_pin_verified",
        "independent_publisher_provenance_verified",
        "trusted_release_artifact_verified",
        "production_rollback_protection_verified",
        "authorized_to_install",
    ),
)
def test_no_authority_fields_stay_explicitly_false(flag: str) -> None:
    assert f"{flag} = $false" in verifier()
    assert f"verifyReport.{flag} -cne $false" in admin()


def test_hosted_ci_only_and_no_private_key_export() -> None:
    for content in (admin(), verifier(), SIGNER.read_text(encoding="utf-8")):
        assert "github-hosted" in content
        assert "WindowsBuiltInRole]::Administrator" in content
    for content in (admin(), verifier()):
        for unsafe in (
            "Remove-LocalUser",
            "DeleteFile(",
            "Remove-Item ",
            "New-Service",
            "Set-Service",
            "ExportRSAPrivateKey",
            "ProgramData\\Paper Data Suite",
        ):
            assert unsafe not in content


def test_workflow_triggers_both_revised_scripts() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "qualify_sandbox_os_parent_ci.ps1" in content
    assert "sandbox_ephemeral_signature_verify.ps1" in content
    assert "runs-on: windows-2022" in content


def test_ci_success_marker_in_admin() -> None:
    assert "SLICE142_EPHEMERAL_SESSION_PIN_BLOCKS_SELF_SIGNED_SUBSTITUTION" in admin()


def test_docs_state_scope_and_limits() -> None:
    content = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "session pin",
        "self-signed",
        "separate verifier process",
        "not publisher authentication",
        "not a production trust root",
        "rollback",
        "ordinary user",
        "no production",
    ):
        assert phrase in content
