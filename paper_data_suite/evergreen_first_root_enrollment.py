"""Issue #49 Slice 143: externally pinned first-root enrollment review.

This is a *read-only* verifier of an independent bootstrap approval against
signed registry and delegated module claims, not an authority issuer. An
administrator/installer must independently establish and protect the approval;
passing a self-computed policy digest is NEVER production authentication.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    RevisionCheckpoint,
    verify_module_document,
    verify_registry_document,
)
from paper_data_suite.evergreen_trust_provisioning import (
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)

_HASH: Final = re.compile(r"[0-9a-f]{64}\Z")
_KEY: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")
_MAX_REGISTRY: Final = 192 * 1024
_MAX_MODULE: Final = 192 * 1024
_NO_AUTHORITY: Final = (
    "NO_INDEPENDENT_ROOT_PROVENANCE_INSTALL_RECEIPT_OR_LAUNCH_AUTHORITY"
)


class FirstRootEnrollmentError(ValueError):
    """Candidate cannot be matched to an externally specified root approval."""


@dataclass(frozen=True, slots=True)
class ExternalRootApproval:
    """Facts that MUST originate outside the untrusted policy/catalog source.

    Construction of this object is *not* authentication. Its producer MUST be
    independently trusted and OS-protected by later installation code. There is
    intentionally no function here to derive approval from candidate bytes.
    """

    policy_sha256: str
    root_key_ids: tuple[str, ...]
    root_threshold: int
    quillan_signing_key_ids: tuple[str, ...]
    minimum_policy_revision: int

    def __post_init__(self) -> None:
        if type(self.policy_sha256) is not str or not _HASH.fullmatch(
            self.policy_sha256
        ):
            raise FirstRootEnrollmentError("invalid externally approved policy pin")
        if (
            type(self.root_key_ids) is not tuple
            or not 1 <= len(self.root_key_ids) <= 8
            or any(
                type(s) is not str or not _KEY.fullmatch(s) for s in self.root_key_ids
            )
            or len(set(self.root_key_ids)) != len(self.root_key_ids)
        ):
            raise FirstRootEnrollmentError("invalid externally approved root keys")
        if type(self.root_threshold) is not int or not 1 <= self.root_threshold <= len(
            self.root_key_ids
        ):
            raise FirstRootEnrollmentError("invalid approved root quorum")
        if (
            type(self.quillan_signing_key_ids) is not tuple
            or not 1 <= len(self.quillan_signing_key_ids) <= 8
            or any(
                type(s) is not str or not _KEY.fullmatch(s)
                for s in self.quillan_signing_key_ids
            )
            or len(set(self.quillan_signing_key_ids))
            != len(self.quillan_signing_key_ids)
            or set(self.quillan_signing_key_ids).intersection(self.root_key_ids)
        ):
            raise FirstRootEnrollmentError("invalid approved Quillan delegation")
        if (
            type(self.minimum_policy_revision) is not int
            or not 1 <= self.minimum_policy_revision <= 2**53 - 1
        ):
            raise FirstRootEnrollmentError("invalid minimum trust policy revision")


@dataclass(frozen=True, slots=True)
class FirstRootReview:
    """Cryptographic coherence only; explicitly non-authorizing."""

    policy_sha256: str
    policy_revision: int
    root_signature_key_ids: tuple[str, ...]
    registry_payload_sha256: str
    registry_revision: int
    quillan_signature_key_ids: tuple[str, ...]
    module_payload_sha256: str
    module_revision: int
    signed_quillan_versions: tuple[str, ...]
    signed_wheel_sha256: tuple[str, ...]
    status: str = "EXTERNALLY_PINNED_SIGNED_QUILLAN_CANDIDATE_REVIEWED"
    independent_approval_custody_verified: bool = False
    installed_wheel_bytes_verified: bool = False
    publisher_identity_officially_attested: bool = False
    authorized_to_enroll: bool = False
    authorized_to_install: bool = False
    authorized_to_launch: bool = False
    authority: str = _NO_AUTHORITY


def review_first_root_quillan_candidate(
    policy_bytes: bytes,
    *,
    approval: ExternalRootApproval,
    registry_envelope: bytes,
    module_envelope: bytes,
    now: datetime,
    prior_registry: RevisionCheckpoint | None = None,
    prior_module: RevisionCheckpoint | None = None,
) -> FirstRootReview:
    """Reverify externally specified roots, Quillan delegation and signatures.

    `approval` MUST come from a separately authenticated, protected installer;
    this function cannot verify that provenance. This is not an enrollment
    writer, cache, authority credential, installer preflight or launcher.
    """
    if not isinstance(approval, ExternalRootApproval):
        raise FirstRootEnrollmentError("independent root approval required")
    if (
        type(registry_envelope) is not bytes
        or not 1 <= len(registry_envelope) <= _MAX_REGISTRY
        or type(module_envelope) is not bytes
        or not 1 <= len(module_envelope) <= _MAX_MODULE
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or (
            prior_registry is not None
            and type(prior_registry) is not RevisionCheckpoint
        )
        or (prior_module is not None and type(prior_module) is not RevisionCheckpoint)
    ):
        raise FirstRootEnrollmentError("invalid enrollment review input")
    try:
        pinned = load_digest_pinned_trust_policy(
            policy_bytes, pinned_sha256=approval.policy_sha256
        )
        if (
            pinned.policy_revision < approval.minimum_policy_revision
            or pinned.keyring.root_key_ids != approval.root_key_ids
            or pinned.keyring.root_threshold != approval.root_threshold
        ):
            raise FirstRootEnrollmentError("root policy differs from prior approval")
        registry = verify_registry_document(
            registry_envelope,
            trust=pinned.keyring,
            now=now,
            checkpoint=prior_registry,
        )
        matching = tuple(
            module
            for module in registry.claims.modules
            if module.component_id == "quillan"
        )
        if len(matching) != 1 or (
            matching[0].repository,
            matching[0].distribution,
            matching[0].signing_key_ids,
        ) != (
            "Paper-Data-Suite/pds-quillan",
            "quillan",
            approval.quillan_signing_key_ids,
        ):
            raise FirstRootEnrollmentError("approved Quillan binding not established")
        module = verify_module_document(
            module_envelope,
            registry=registry,
            trust=pinned.keyring,
            now=now,
            checkpoint=prior_module,
        )
        if (
            module.claims.component_id != "quillan"
            or module.claims.repository != "Paper-Data-Suite/pds-quillan"
            or module.claims.distribution != "quillan"
        ):
            raise FirstRootEnrollmentError("signed module is not approved Quillan")
        if any(
            release.revoked
            or release.console_script != "quillan"
            or release.console_target != "quillan.cli:main"
            for release in module.claims.releases
        ):
            raise FirstRootEnrollmentError("Quillan release is revoked or misrouted")
        # No historical Suite version equality test: later signed versions can
        # enter review, but are NOT installed, approved or launchable here.
        return FirstRootReview(
            policy_sha256=pinned.sha256,
            policy_revision=pinned.policy_revision,
            root_signature_key_ids=registry.signer_ids,
            registry_payload_sha256=registry.payload_sha256,
            registry_revision=registry.checkpoint.revision,
            quillan_signature_key_ids=module.signer_ids,
            module_payload_sha256=module.payload_sha256,
            module_revision=module.checkpoint.revision,
            signed_quillan_versions=tuple(
                release.version for release in module.claims.releases
            ),
            signed_wheel_sha256=tuple(
                release.sha256 for release in module.claims.releases
            ),
        )
    except (TrustProvisioningError, CatalogVerificationError) as error:
        raise FirstRootEnrollmentError(
            "first-root policy or signed delegation verification refused"
        ) from error


__all__ = (
    "ExternalRootApproval",
    "FirstRootEnrollmentError",
    "FirstRootReview",
    "review_first_root_quillan_candidate",
)
