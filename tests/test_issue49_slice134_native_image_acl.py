"""Slice 134: held service-image ACL inspection grants no installation authority."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "native/windows/bootstrap/service_image_linkage_probe.cpp"
HELPER = ROOT / "native/windows/bootstrap/qualify_native_admin_token.ps1"
MAIN = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-134-native-image-acl.md"


def test_exact_scope_and_main_gate_compatibility() -> None:
    for item in (CPP, HELPER, MAIN, DOC):
        assert item.is_file()
        assert 100 < item.stat().st_size < 30000
    assert len(MAIN.read_bytes().replace(b"\r\n", b"\n")) < 16000
    assert (
        MAIN.read_text(encoding="utf-8")
        .rstrip()
        .endswith(
            'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\n'
            "exit 0"
        )
    )


def test_held_handle_is_the_security_descriptor_subject() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        "observe_image_security(image.get(), found)",
        "GetSecurityInfo(image, SE_FILE_OBJECT,",
        "OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION",
        "OwnedSecurityDescriptor descriptor(raw_descriptor)",
        "(void)LocalFree(value_)",
        "READ_CONTROL | FILE_READ_ATTRIBUTES",
        "FILE_FLAG_OPEN_REPARSE_POINT",
        "attributes.nNumberOfLinks != 1",
        "GetFinalPathNameByHandleW(",
    ):
        assert phrase in source


def test_security_descriptor_and_ace_bounds_are_checked() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        "IsValidSecurityDescriptor(descriptor.get())",
        "GetSecurityDescriptorLength(descriptor.get()) > 8192",
        "IsValidSid(owner)",
        "GetSecurityDescriptorDacl(",
        "checked_dacl != dacl",
        "IsValidAcl(checked_dacl)",
        "GetAclInformation(",
        "size.AceCount > 128",
        "GetAce(checked_dacl, i, &raw_ace)",
        "GetSidLengthRequired(sid->SubAuthorityCount)",
        "sid_size > header->AceSize - kSidOffset",
    ):
        assert phrase in source


@pytest.mark.parametrize(
    "name",
    (
        "FILE_WRITE_DATA",
        "FILE_APPEND_DATA",
        "FILE_WRITE_EA",
        "FILE_WRITE_ATTRIBUTES",
        "DELETE",
        "WRITE_DAC",
        "WRITE_OWNER",
        "GENERIC_WRITE",
        "GENERIC_ALL",
    ),
)
def test_allow_ace_write_related_rights_are_only_observed(name: str) -> None:
    source = CPP.read_text(encoding="utf-8")
    assert name in source
    assert "image_mutation_allow_ace_observed" in source


@pytest.mark.parametrize(
    "forbidden",
    (
        "SetNamedSecurityInfoW(",
        "SetSecurityInfo(",
        "SetFileSecurityW(",
        "WriteFile(",
        "CreateServiceW(",
        "StartServiceW(",
        "AdjustTokenPrivileges(",
        "CreateProcessW(",
        "ImpersonateLoggedOnUser(",
    ),
)
def test_native_probe_has_no_privileged_mutation(forbidden: str) -> None:
    assert forbidden not in CPP.read_text(encoding="utf-8")


def test_output_is_observational_and_explicitly_non_authorizing() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        'image_owner_sid_observed\\":',
        'image_dacl_observed\\":',
        'image_mutation_allow_ace_observed\\":',
        'executable_custody_verified\\":false',
        'installed_service_identity_verified\\":false',
        'authorized_to_install\\":false',
        "SCM_PROCESS_IMAGE_LINKAGE_OBSERVED_UNVERIFIED",
        "REFUSED_UNSUPPORTED_SERVICE_IMAGE_ARGUMENT",
    ):
        assert phrase in source


def test_native_gate_requires_positive_acl_consistency_and_refusal() -> None:
    helper = HELPER.read_text(encoding="utf-8")
    for phrase in (
        "$image.image_owner_sid_observed -cne $imageObserved",
        "$image.image_dacl_observed -cne $imageObserved",
        "$image.image_mutation_allow_ace_observed -isnot [bool]",
        "$imageDenied.image_owner_sid_observed -cne $false",
        "$imageDenied.image_dacl_observed -cne $false",
        "SLICE134_NATIVE_HELD_IMAGE_ACL_NONAUTHORITY_PASSED_$Architecture",
        "@(& $imageExe --approve)",
        "SLICE133_NATIVE_SERVICE_IMAGE_NONAUTHORITY_PASSED_$Architecture",
    ):
        assert phrase in helper
    assert helper.rstrip().endswith(
        'Write-Host "SLICE130_NATIVE_SCM_NONAUTHORITY_PASSED_$Architecture"\nexit 0'
    )


def test_documentation_withholds_provisioning_and_effective_acl_assurance() -> None:
    note = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "held handle",
        "owner",
        "dacl",
        "not effective access",
        "ordinary teacher",
        "no provisioning",
        "no installation",
        "x64",
        "arm64",
    ):
        assert phrase in note
