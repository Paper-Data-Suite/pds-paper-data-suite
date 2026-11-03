"""Slice 126: claimed native publisher pins are not provisioned trust."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "native/windows/bootstrap/publisher_pin_contract.h"
NATIVE_TEST = ROOT / "native/windows/bootstrap/publisher_pin_contract_test.cpp"
CMAKE = ROOT / "native/windows/bootstrap/CMakeLists.txt"
GATE = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-126-publisher-pin-contract.md"


def test_exact_native_source_contract_files_present() -> None:
    for file in (HEADER, NATIVE_TEST, CMAKE, GATE, DOC):
        assert file.is_file()
        assert 100 < file.stat().st_size < 24000


def test_canonical_publisher_pin_parser_requires_exact_fields() -> None:
    header = HEADER.read_text(encoding="utf-8")
    for text in (
        'reader.field("certificate_sha256")',
        'reader.field("spki_sha256")',
        'reader.field("revision")',
        'reader.field("schema")',
        "schema == 1",
        "reader.complete()",
        "kMaxBytes = 512",
        "kMaxRevision = 9007199254740991ULL",
        "lowercase_sha256",
    ):
        assert text in header


def test_claimed_transition_refuses_equivocation_and_rollback() -> None:
    header = HEADER.read_text(encoding="utf-8")
    for phrase in (
        "new_pin.revision < old_pin.revision",
        "new_pin.revision == old_pin.revision",
        "new_pin.certificate_sha256 == old_pin.certificate_sha256",
        "new_pin.spki_sha256 == old_pin.spki_sha256",
        "ClaimedTransition::invalid",
        "ClaimedTransition::identical_claim_only",
        "ClaimedTransition::rotation_claim_requires_independent_native_custody",
    ):
        assert phrase in header


@pytest.mark.parametrize(
    "forbidden",
    (
        "CreateFileW(",
        "WriteFile(",
        "WinVerifyTrust(",
        "SetFileSecurityW(",
        "CreateServiceW(",
        "CertAddCertificateContextToStore(",
        "authorized_to_install = true",
        "approved = true",
    ),
    ids=(
        "create",
        "write",
        "wintrust",
        "acl",
        "service",
        "cert-store",
        "install",
        "approve",
    ),
)
def test_pure_parser_has_no_native_mutation_or_authorization(forbidden: str) -> None:
    assert forbidden not in HEADER.read_text(encoding="utf-8")


def test_native_negative_cases_are_exercised() -> None:
    source = NATIVE_TEST.read_text(encoding="utf-8")
    for phrase in (
        "strict-valid",
        "rotation-claim-only",
        "equal-revision-equivocation",
        "revision-rollback",
        "uppercase-cert",
        "zero-cert",
        "zero-spki",
        "duplicate-key",
        "noncanonical-space",
        "oversized",
        "extra-key",
        "SLICE126_NATIVE_PUBLISHER_PIN_CONTRACT_TESTS_PASSED",
    ):
        assert phrase in source


def test_cmake_target_is_standalone_and_warnings_are_errors() -> None:
    source = CMAKE.read_text(encoding="utf-8")
    assert (
        "add_executable(pds_publisher_pin_contract_test "
        "publisher_pin_contract_test.cpp)" in source
    )
    assert "pds_publisher_pin_contract_test PRIVATE cxx_std_17" in source
    assert "pds_publisher_pin_contract_test PRIVATE /W4 /WX /permissive- /sdl" in source
    assert "pds_publisher_pin_contract_test PRIVATE -Wall -Wextra -Werror" in source
    assert "pds_windows_signature_probe PRIVATE wintrust crypt32" in source


def test_real_native_runtime_gate_is_mandatory_on_matching_architecture() -> None:
    source = GATE.read_text(encoding="utf-8")
    assert "--target pds_publisher_pin_contract_test --parallel 2" in source
    assert "@(& $pinContractExe)" in source
    assert "$pinCode -ne 0" in source
    assert "SLICE126_NATIVE_PUBLISHER_PIN_CONTRACT_TESTS_PASSED" in source
    assert "SLICE126_NATIVE_PUBLISHER_PIN_CONTRACT_PASSED_$Architecture" in source
    assert source.index("if ($Architecture -ne $hostArchitecture)") < source.index(
        "@(& $pinContractExe)"
    )
    assert source.rstrip().endswith(
        'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\nexit 0'
    )


def test_documentation_requires_independent_native_provisioning() -> None:
    content = DOC.read_text(encoding="utf-8").lower()
    for text in (
        "claimed policy",
        "not an authenticated publisher",
        "not a provisioned trust root",
        "independent native custody",
        "x64",
        "arm64",
        "no installation",
        "revision rollback",
    ):
        assert text in content
