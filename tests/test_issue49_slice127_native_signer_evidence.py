"""Slice 127: claimed signer evidence is never trusted publisher custody."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native/windows/bootstrap/signature_probe.cpp"
COMPARE = ROOT / "native/windows/bootstrap/publisher_pin_evidence.h"
TEST_CPP = ROOT / "native/windows/bootstrap/publisher_pin_evidence_test.cpp"
CMAKE = ROOT / "native/windows/bootstrap/CMakeLists.txt"
GATE = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-127-native-signer-evidence.md"


def test_exact_seven_file_components() -> None:
    for path in (NATIVE, COMPARE, TEST_CPP, CMAKE, GATE, DOC):
        assert path.is_file()
        assert 100 < path.stat().st_size < 30000


def test_embedded_pkcs7_signer_is_located_in_own_executable() -> None:
    source = NATIVE.read_text(encoding="utf-8")
    for token in (
        "GetModuleFileNameW(nullptr, path.data()",
        "CryptQueryObject(",
        "CERT_QUERY_OBJECT_FILE",
        "CERT_QUERY_CONTENT_FLAG_PKCS7_SIGNED_EMBED",
        "CMSG_SIGNER_INFO_PARAM",
        "CertFindCertificateInStore(",
        "CERT_FIND_SUBJECT_CERT",
        "WinVerifyTrust(nullptr, &action, &request)",
        "WTD_STATEACTION_CLOSE",
    ):
        assert token in source
    assert "if (result != ERROR_SUCCESS) return false;" in source
    assert (
        "evidence_observed = inspect_embedded_signer_evidence(path.data());" in source
    )


def test_sha256_uses_der_certificate_and_encoded_spki() -> None:
    source = NATIVE.read_text(encoding="utf-8")
    for token in (
        'CryptHashCertificate2(L"SHA256"',
        "selected.context->pbCertEncoded",
        "selected.context->cbCertEncoded",
        "CryptEncodeObjectEx(",
        "X509_PUBLIC_KEY_INFO",
        "CRYPT_ENCODE_ALLOC_FLAG",
        "SubjectPublicKeyInfo",
        "valid_signer_evidence(",
    ):
        assert token in source
    assert "LocalFree(value)" in source
    assert "CertFreeCertificateContext(context)" in source
    assert "CryptMsgClose(message)" in source
    assert "CertCloseStore(store, 0)" in source


def test_signer_evidence_diagnostic_remains_no_authority() -> None:
    source = NATIVE.read_text(encoding="utf-8")
    for token in (
        'signer_evidence_observed\\":',
        'publisher_pin_verified\\":false',
        'authorized_to_install\\":false',
        "NATIVE_SIGNATURE_NOT_TRUSTED",
        "NATIVE_SIGNATURE_EVIDENCE_UNAVAILABLE",
        "NATIVE_WINDOWS_CHAIN_OBSERVED_PIN_UNPROVISIONED",
        "REFUSED_UNSUPPORTED_SIGNATURE_ARGUMENT",
        "return observed ? 2 : 1;",
    ):
        assert token in source
    assert "CryptHashCertificate2" in source
    assert "cert_sha256" in source
    assert "spki_sha256" in source
    assert "std::cout << cert_sha256" not in source
    assert "std::cout << spki_sha256" not in source


@pytest.mark.parametrize(
    "forbidden",
    (
        "WriteFile(",
        "CreateServiceW(",
        "StartServiceW(",
        "ShellExecuteW(",
        "CreateProcessW(",
        "SetFileSecurityW(",
        "CertAddCertificateContextToStore(",
    ),
    ids=("write", "service", "start", "elevate", "execute", "acl", "store"),
)
def test_native_signature_diagnostic_has_no_write_path(forbidden: str) -> None:
    assert forbidden not in NATIVE.read_text(encoding="utf-8")


def test_claim_comparison_explicitly_withholds_authority() -> None:
    source = COMPARE.read_text(encoding="utf-8")
    for token in (
        "publisher_pin_contract.h",
        "canonical_sha256",
        "valid_signer_evidence",
        "parse_claimed_pin(claimed_policy, pin)",
        "EvidenceComparison::invalid",
        "EvidenceComparison::claimed_mismatch",
        "EvidenceComparison::claimed_match_without_authority",
    ):
        assert token in source
    assert "authorized_to_install" not in source


def test_native_tests_cover_matching_and_mismatching_claims() -> None:
    source = TEST_CPP.read_text(encoding="utf-8")
    for text in (
        "matching-claim-does-not-authorize",
        "different-certificate",
        "different-spki",
        "untrusted-malformed-policy",
        "malformed-evidence",
        "noncanonical-policy",
        "SLICE127_NATIVE_PUBLISHER_EVIDENCE_TESTS_PASSED",
    ):
        assert text in source


def test_native_build_and_runtime_gate_enforces_new_target() -> None:
    cmake = CMAKE.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    assert "pds_publisher_pin_evidence_test publisher_pin_evidence_test.cpp" in cmake
    assert "pds_publisher_pin_evidence_test PRIVATE /W4 /WX /permissive- /sdl" in cmake
    assert "pds_publisher_pin_evidence_test PRIVATE -Wall -Wextra -Werror" in cmake
    assert "--target pds_publisher_pin_evidence_test --parallel 2" in gate
    assert "@(& $evidenceExe)" in gate
    assert "SLICE127_NATIVE_PUBLISHER_EVIDENCE_PASSED_$Architecture" in gate
    assert "$sig.signer_evidence_observed -cne $false" in gate
    assert "$sigDenied.signer_evidence_observed -cne $false" in gate
    assert gate.index("if ($Architecture -ne $hostArchitecture)") < gate.index(
        "@(& $evidenceExe)"
    )
    assert gate.rstrip().endswith(
        'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\nexit 0'
    )


def test_documentation_distinguishes_claims_from_trusted_provisioning() -> None:
    document = DOC.read_text(encoding="utf-8").lower()
    for token in (
        "spki",
        "certificate",
        "winverifytrust",
        "not independently provisioned",
        "not authorized",
        "x64",
        "arm64",
        "no installation",
    ):
        assert token in document
