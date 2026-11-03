"""Slice 143: external first-root approval precedes signed Quillan review."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_issue49_slice3_signature_verification import (
    NOW,
    _module,
    _registry,
    _signed,
)
from test_issue49_slice4_trust_and_cache import _policy

from paper_data_suite.evergreen_catalog_verification import RevisionCheckpoint
from paper_data_suite.evergreen_first_root_enrollment import (
    ExternalRootApproval,
    FirstRootEnrollmentError,
    review_first_root_quillan_candidate,
)


def _approval(policy: bytes | None = None) -> ExternalRootApproval:
    raw = _policy() if policy is None else policy
    return ExternalRootApproval(
        policy_sha256=hashlib.sha256(raw).hexdigest(),
        root_key_ids=("root-primary", "root-backup"),
        root_threshold=1,
        quillan_signing_key_ids=("quillan-primary",),
        minimum_policy_revision=1,
    )


def _review(
    *,
    approval: ExternalRootApproval | None = None,
    policy: bytes | None = None,
    registry: bytes | None = None,
    module: bytes | None = None,
    now=NOW,
    prior_registry: RevisionCheckpoint | None = None,
    prior_module: RevisionCheckpoint | None = None,
):
    return review_first_root_quillan_candidate(
        _policy() if policy is None else policy,
        approval=_approval() if approval is None else approval,
        registry_envelope=(
            _signed(_registry(), "root-primary") if registry is None else registry
        ),
        module_envelope=(
            _signed(_module(), "quillan-primary") if module is None else module
        ),
        now=now,
        prior_registry=prior_registry,
        prior_module=prior_module,
    )


def test_future_signed_quillan_version_reviews_without_new_suite() -> None:
    result = _review()
    assert result.policy_sha256 == hashlib.sha256(_policy()).hexdigest()
    assert result.root_signature_key_ids == ("root-primary",)
    assert result.quillan_signature_key_ids == ("quillan-primary",)
    assert result.signed_quillan_versions == ("0.10.7",)
    assert result.signed_wheel_sha256 == ("a" * 64,)
    assert result.registry_revision == result.module_revision == 1
    assert result.status == "EXTERNALLY_PINNED_SIGNED_QUILLAN_CANDIDATE_REVIEWED"


def test_verification_does_not_enroll_launch_install_or_attest() -> None:
    result = _review()
    assert not result.independent_approval_custody_verified
    assert not result.installed_wheel_bytes_verified
    assert not result.publisher_identity_officially_attested
    assert not result.authorized_to_enroll
    assert not result.authorized_to_install
    assert not result.authorized_to_launch
    assert result.authority.startswith("NO_INDEPENDENT_ROOT_")
    assert not hasattr(result, "can_launch")
    with pytest.raises(FrozenInstanceError):
        result.authorized_to_launch = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [
        {"policy_sha256": "0" * 64},
        {"root_key_ids": ("root-backup",)},
        {"root_threshold": 2},
        {"quillan_signing_key_ids": ("portia-primary",)},
        {"minimum_policy_revision": 2},
    ],
)
def test_independently_approved_details_must_match(changes: dict[str, object]) -> None:
    with pytest.raises(FirstRootEnrollmentError):
        _review(approval=replace(_approval(), **changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"policy_sha256": "ABC"},
        {"root_key_ids": ("root-primary", "root-primary")},
        {"root_threshold": True},
        {"root_threshold": 0},
        {"quillan_signing_key_ids": ("root-primary",)},
        {"quillan_signing_key_ids": ()},
        {"minimum_policy_revision": True},
        {"minimum_policy_revision": 0},
    ],
)
def test_malformed_external_approval_refused(changes: dict[str, object]) -> None:
    with pytest.raises(FirstRootEnrollmentError):
        replace(_approval(), **changes)


def test_candidate_self_signed_alternate_policy_cannot_displace_prior_pin() -> None:
    replacement = bytearray(_policy())
    replacement[-1] = ord(" ")
    with pytest.raises(FirstRootEnrollmentError):
        _review(policy=bytes(replacement))


@pytest.mark.parametrize("signer", ["quillan-primary", "attacker"])
def test_registry_must_have_real_root_signature(signer: str) -> None:
    with pytest.raises(FirstRootEnrollmentError):
        _review(registry=_signed(_registry(), signer))


@pytest.mark.parametrize("signer", ["root-primary", "portia-primary", "attacker"])
def test_quillan_release_must_have_approved_module_signature(signer: str) -> None:
    with pytest.raises(FirstRootEnrollmentError):
        _review(module=_signed(_module(), signer))


def test_registry_cannot_change_approved_quillan_repository() -> None:
    claim = copy.deepcopy(_registry())
    claim["modules"][0]["repository"] = "ForeignOrg/pds-quillan"
    with pytest.raises(FirstRootEnrollmentError):
        _review(registry=_signed(claim, "root-primary"))


def test_registry_cannot_delegate_quillan_to_unapproved_key() -> None:
    claim = copy.deepcopy(_registry())
    claim["modules"][0]["signing_key_ids"] = ["portia-primary"]
    with pytest.raises(FirstRootEnrollmentError):
        _review(registry=_signed(claim, "root-primary"))


def test_registry_can_authorize_other_module_without_forging_quillan() -> None:
    result = _review()
    assert result.quillan_signature_key_ids == ("quillan-primary",)


def test_quillan_signed_claim_cannot_be_swapped_for_portia() -> None:
    claim = copy.deepcopy(_module())
    claim["component_id"] = "portia"
    claim["repository"] = "Paper-Data-Suite/pds-portia"
    claim["distribution"] = "pds-portia"
    with pytest.raises(FirstRootEnrollmentError):
        _review(module=_signed(claim, "portia-primary"))


def test_signed_claim_version_can_advance_without_suite_revision() -> None:
    claim = copy.deepcopy(_module())
    claim["releases"][0]["version"] = "0.12.0"
    claim["releases"][0]["tag"] = "v0.12.0"
    claim["releases"][0]["wheel"] = "quillan-0.12.0-py3-none-any.whl"
    result = _review(module=_signed(claim, "quillan-primary"))
    assert result.signed_quillan_versions == ("0.12.0",)
    assert not result.authorized_to_install


def test_revoked_release_is_not_admitted_as_first_root_candidate() -> None:
    claim = copy.deepcopy(_module())
    claim["releases"][0]["revoked"] = True
    with pytest.raises(FirstRootEnrollmentError):
        _review(module=_signed(claim, "quillan-primary"))


def test_signed_unapproved_launcher_target_is_refused() -> None:
    claim = copy.deepcopy(_module())
    claim["releases"][0]["console_target"] = "unknown.cli:main"
    with pytest.raises(FirstRootEnrollmentError):
        _review(module=_signed(claim, "quillan-primary"))


def test_untrusted_bytes_or_missing_approval_refused() -> None:
    with pytest.raises(FirstRootEnrollmentError):
        review_first_root_quillan_candidate(
            _policy(),
            approval=None,  # type: ignore[arg-type]
            registry_envelope=_signed(_registry(), "root-primary"),
            module_envelope=_signed(_module(), "quillan-primary"),
            now=NOW,
        )
    with pytest.raises(FirstRootEnrollmentError):
        _review(registry=b"unsigned")
    with pytest.raises(FirstRootEnrollmentError):
        _review(module=b"unsigned")


def test_expired_and_not_yet_valid_registry_refuse() -> None:
    with pytest.raises(FirstRootEnrollmentError):
        _review(now=NOW + timedelta(days=50))
    with pytest.raises(FirstRootEnrollmentError):
        _review(now=NOW - timedelta(days=5))


def test_previous_checkpoint_is_enforced_not_silently_discarded() -> None:
    with pytest.raises(FirstRootEnrollmentError):
        _review(prior_registry=RevisionCheckpoint(3, "a" * 64))
    with pytest.raises(FirstRootEnrollmentError):
        _review(prior_module=RevisionCheckpoint(3, "a" * 64))


def test_no_file_writes_subprocess_network_or_workstation_authority() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "paper_data_suite/evergreen_first_root_enrollment.py"
    )
    text = source.read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "requests",
        "urllib",
        "os.open",
        ".write_bytes(",
        ".write_text(",
        "New-Service",
        "AuthorizedToLaunch = True",
    ):
        assert forbidden not in text
    assert "load_digest_pinned_trust_policy" in text
    assert "verify_registry_document" in text
    assert "verify_module_document" in text
