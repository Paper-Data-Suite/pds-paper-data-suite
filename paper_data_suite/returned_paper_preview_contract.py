"""Suite #17: typed, strictly observational returned-paper preflight contract.

This module defines no scanner, Core routing adapter, retention action, or
producer operation. Its records contain no raw QR strings, file paths or
producer-private targets; Core RouteLocator objects remain transient to the
later decoder/orchestrator and are deliberately not represented here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

PREVIEW_CONTRACT_VERSION: Final[str] = "1"

SourceStatus = Literal[
    "observed",
    "source_unavailable",
    "unsupported_format",
    "resource_limit",
    "backend_unavailable",
    "source_decode_failed",
]
PageStatus = Literal[
    "candidate_unverified",
    "missing_qr",
    "unreadable_qr",
    "invalid_or_foreign_qr",
    "ambiguous_qr",
    "page_decode_failed",
]
RegistrationStatus = Literal[
    "not_checked",
    "workspace_unavailable",
    "registration_not_found",
    "registration_invalid",
    "registration_inactive",
    "structurally_consistent",
]
RoutingMetadataStatus = Literal[
    "not_declared",
    "declared_unvalidated",
    "owner_mismatch",
    "ambiguous",
    "invalid_metadata",
    "inspection_unavailable",
]
RoutingProfileStatus = Literal[
    "not_evaluated",
    "profile_valid",
    "profile_invalid",
    "profile_unavailable",
    "core_incompatible",
]

_SOURCE_STATUSES: Final[frozenset[str]] = frozenset({
    "observed", "source_unavailable", "unsupported_format",
    "resource_limit", "backend_unavailable", "source_decode_failed",
})
_PAGE_STATUSES: Final[frozenset[str]] = frozenset({
    "candidate_unverified", "missing_qr", "unreadable_qr",
    "invalid_or_foreign_qr", "ambiguous_qr", "page_decode_failed",
})
_REGISTRATION_STATUSES: Final[frozenset[str]] = frozenset({
    "not_checked", "workspace_unavailable", "registration_not_found",
    "registration_invalid", "registration_inactive", "structurally_consistent",
})
_METADATA_STATUSES: Final[frozenset[str]] = frozenset({
    "not_declared", "declared_unvalidated", "owner_mismatch",
    "ambiguous", "invalid_metadata", "inspection_unavailable",
})
_PROFILE_STATUSES: Final[frozenset[str]] = frozenset({
    "not_evaluated", "profile_valid", "profile_invalid",
    "profile_unavailable", "core_incompatible",
})
_DIGEST: Final = re.compile(r"[0-9a-f]{64}\Z")
_MODULE_ID: Final = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def _positive(value: object, field: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be a positive integer")


@dataclass(frozen=True, slots=True)
class PagePreview:
    """One *physical*, one-based page observation; never a routing receipt."""

    page_number: int
    status: PageStatus
    candidate_module_id: str | None = None
    registration_status: RegistrationStatus = "not_checked"

    def __post_init__(self) -> None:
        _positive(self.page_number, "page_number")
        if self.status not in _PAGE_STATUSES:
            raise ValueError("unsupported page observation status")
        if self.registration_status not in _REGISTRATION_STATUSES:
            raise ValueError("unsupported registration observation status")
        if self.status == "candidate_unverified":
            if (
                type(self.candidate_module_id) is not str
                or not _MODULE_ID.fullmatch(self.candidate_module_id)
            ):
                raise ValueError("a valid candidate needs a safe Core module ID")
        elif self.candidate_module_id is not None:
            raise ValueError("noncandidate page cannot claim a module")
        if (
            self.status != "candidate_unverified"
            and self.registration_status != "not_checked"
        ):
            raise ValueError("only candidates may have a registration observation")


@dataclass(frozen=True, slots=True)
class SourcePreview:
    """A safe position-based source reference, not a path or retained scan."""

    source_number: int
    status: SourceStatus
    pages: tuple[PagePreview, ...] = ()
    sha256_advisory: str | None = None

    def __post_init__(self) -> None:
        _positive(self.source_number, "source_number")
        if self.status not in _SOURCE_STATUSES:
            raise ValueError("unsupported source observation status")
        if type(self.pages) is not tuple or any(
            not isinstance(page, PagePreview) for page in self.pages
        ):
            raise TypeError("pages must be a tuple of PagePreview records")
        if self.status != "observed" and self.pages:
            raise ValueError("an unsuccessful source cannot claim observed pages")
        if self.status == "observed" and not self.pages:
            raise ValueError("an observed source must list physical pages")
        if tuple(page.page_number for page in self.pages) != tuple(
            range(1, len(self.pages) + 1)
        ):
            raise ValueError("physical pages must be contiguous and one-based")
        if self.sha256_advisory is not None and (
            type(self.sha256_advisory) is not str
            or not _DIGEST.fullmatch(self.sha256_advisory)
        ):
            raise ValueError("advisory fingerprint must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ModuleRoutingPreview:
    """Separate declaration/profile state; neither conveys dispatch authority."""

    module_id: str
    metadata_status: RoutingMetadataStatus
    profile_status: RoutingProfileStatus = "not_evaluated"

    def __post_init__(self) -> None:
        if type(self.module_id) is not str or not _MODULE_ID.fullmatch(
            self.module_id
        ):
            raise ValueError("module_id must be a safe Core module ID")
        if self.metadata_status not in _METADATA_STATUSES:
            raise ValueError("invalid routing metadata status")
        if self.profile_status not in _PROFILE_STATUSES:
            raise ValueError("invalid routing profile status")
        if (
            self.metadata_status != "declared_unvalidated"
            and self.profile_status != "not_evaluated"
        ):
            raise ValueError("unqualified metadata cannot claim profile validation")


@dataclass(frozen=True, slots=True)
class IntakePreview:
    """Read-only summary; never persisted as custody or used as authorization."""

    sources: tuple[SourcePreview, ...]
    routing: tuple[ModuleRoutingPreview, ...]
    contract_version: Literal["1"] = "1"
    processing_performed: Literal[False] = False

    def __post_init__(self) -> None:
        if self.contract_version != PREVIEW_CONTRACT_VERSION:
            raise ValueError("unsupported preview contract version")
        if self.processing_performed is not False:
            raise ValueError("preview records cannot claim processing")
        if type(self.sources) is not tuple or any(
            not isinstance(source, SourcePreview) for source in self.sources
        ):
            raise TypeError("sources must be a tuple of SourcePreview records")
        if tuple(source.source_number for source in self.sources) != tuple(
            range(1, len(self.sources) + 1)
        ):
            raise ValueError("sources must be contiguous and one-based")
        if type(self.routing) is not tuple or any(
            not isinstance(row, ModuleRoutingPreview) for row in self.routing
        ):
            raise TypeError("routing must be a tuple of ModuleRoutingPreview records")
        if len({row.module_id for row in self.routing}) != len(self.routing):
            raise ValueError("duplicate routing module identities")
