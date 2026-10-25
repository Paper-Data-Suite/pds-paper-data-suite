"""Issue #49 Slice 59: read-only correlation of signed releases with local metadata.

The catalog must already be signature-verified. Installed distribution metadata
is editable by the local interpreter user: it is NOT installed-wheel verification,
a trusted receipt, an active-composition claim, or permission to launch/update.
No module import, script execution, network access, or file mutation occurs here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from importlib import metadata

from paper_data_suite.evergreen_catalog_state import CatalogSnapshot

VersionLookup = Callable[[str], str]


class LocalCatalogMetadataError(ValueError):
    """Invalid signed-catalog input or unsupported local metadata observation."""


class LocalMetadataFinding(str, Enum):
    """Metadata observations only; no finding can grant execution authority."""

    NOT_REPORTED = "not_reported"
    SIGNED_RELEASE_DOCUMENT_ABSENT = "signed_release_document_absent"
    VERSION_NOT_IN_SIGNED_RELEASES = "version_not_in_signed_releases"
    SIGNED_VERSION_REVOKED = "signed_version_revoked"
    SIGNED_VERSION_MATCH = "signed_version_match"
    METADATA_UNREADABLE = "metadata_unreadable"


@dataclass(frozen=True, slots=True)
class LocalCatalogMetadataRow:
    """Comparison of a signed release *claim* and untrusted package metadata."""

    component_id: str
    distribution: str
    reported_version: str | None
    finding: LocalMetadataFinding
    signed_wheel_sha256: str | None


@dataclass(frozen=True, slots=True)
class LocalCatalogMetadataReport:
    """Read-only diagnostics; never evidence of actual installed wheel bytes."""

    rows: tuple[LocalCatalogMetadataRow, ...]
    authority: str = "NO_INSTALLED_BYTE_LAUNCH_UPDATE_OR_ACTIVATION_AUTHORITY"


def compare_local_catalog_metadata(
    snapshot: CatalogSnapshot,
    *,
    version_lookup: VersionLookup = metadata.version,
) -> LocalCatalogMetadataReport:
    """Compare signed catalog versions to local metadata without executing code.

    The signed registry is the only source of component/distribution identities.
    Local package-version fields are never used to infer wheel provenance.
    Metadata absence means only that *this interpreter* did not report a package.
    The injected lookup is intended for tests; production must use the standard
    ``importlib.metadata.version`` reader (not a module's self-assertion).
    """
    if not isinstance(snapshot, CatalogSnapshot) or not callable(version_lookup):
        raise LocalCatalogMetadataError(
            "authenticated catalog and metadata reader required"
        )
    docs = {item.claims.component_id: item for item in snapshot.modules}
    rows: list[LocalCatalogMetadataRow] = []
    for registered in sorted(
        snapshot.registry.claims.modules, key=lambda item: item.component_id
    ):
        version: str | None
        try:
            version = version_lookup(registered.distribution)
        except metadata.PackageNotFoundError:
            version = None
        except Exception:
            rows.append(
                LocalCatalogMetadataRow(
                    registered.component_id,
                    registered.distribution,
                    None,
                    LocalMetadataFinding.METADATA_UNREADABLE,
                    None,
                )
            )
            continue
        if version is not None and (
            type(version) is not str
            or not 1 <= len(version) <= 96
            or any(ord(character) < 33 or ord(character) > 126 for character in version)
        ):
            rows.append(
                LocalCatalogMetadataRow(
                    registered.component_id,
                    registered.distribution,
                    None,
                    LocalMetadataFinding.METADATA_UNREADABLE,
                    None,
                )
            )
            continue
        if version is None:
            finding = LocalMetadataFinding.NOT_REPORTED
            digest = None
        else:
            document = docs.get(registered.component_id)
            if document is None:
                finding = LocalMetadataFinding.SIGNED_RELEASE_DOCUMENT_ABSENT
                digest = None
            else:
                matching = next(
                    (
                        claim
                        for claim in document.claims.releases
                        if claim.version == version
                    ),
                    None,
                )
                if matching is None:
                    finding = LocalMetadataFinding.VERSION_NOT_IN_SIGNED_RELEASES
                    digest = None
                elif matching.revoked:
                    finding = LocalMetadataFinding.SIGNED_VERSION_REVOKED
                    digest = matching.sha256
                else:
                    finding = LocalMetadataFinding.SIGNED_VERSION_MATCH
                    digest = matching.sha256
        rows.append(
            LocalCatalogMetadataRow(
                registered.component_id,
                registered.distribution,
                version,
                finding,
                digest,
            )
        )
    return LocalCatalogMetadataReport(tuple(rows))


def render_local_catalog_metadata(
    snapshot: CatalogSnapshot,
    *,
    version_lookup: VersionLookup = metadata.version,
) -> str:
    """Make metadata-only correlation conspicuously non-authoritative."""
    report = compare_local_catalog_metadata(snapshot, version_lookup=version_lookup)
    lines = [
        "",
        "Local interpreter package metadata (UNVERIFIED, read-only):",
        "Version comparison is NOT installed-wheel byte verification.",
        "Active managed composition: NOT VERIFIED | Launch eligibility: NOT VERIFIED",
    ]
    labels = {
        LocalMetadataFinding.NOT_REPORTED: (
            "no package version reported by this interpreter"
        ),
        LocalMetadataFinding.SIGNED_RELEASE_DOCUMENT_ABSENT: (
            "no signed release document in cache"
        ),
        LocalMetadataFinding.VERSION_NOT_IN_SIGNED_RELEASES: (
            "version not listed in signed releases"
        ),
        LocalMetadataFinding.SIGNED_VERSION_REVOKED: (
            "matching signed release is REVOKED"
        ),
        LocalMetadataFinding.SIGNED_VERSION_MATCH: (
            "version matches signed claim; BYTES NOT CHECKED"
        ),
        LocalMetadataFinding.METADATA_UNREADABLE: (
            "package metadata could not be safely read"
        ),
    }
    for row in report.rows:
        lines.append(f"  {row.component_id} ({row.distribution})")
        display_version = row.reported_version or "not reported"
        lines.append(f"    Local version metadata: {display_version}")
        lines.append(f"    Correlation: {labels[row.finding]}")
        if row.signed_wheel_sha256 is not None:
            lines.append(f"    Claimed wheel SHA-256: {row.signed_wheel_sha256}")
    lines.extend(
        (
            "This report did not verify installed files, launchers, active receipts,",
            "witness checkpoints, or update readiness. No launch was attempted.",
        )
    )
    return "\n".join(lines) + "\n"


__all__ = (
    "LocalCatalogMetadataError",
    "LocalCatalogMetadataReport",
    "LocalCatalogMetadataRow",
    "LocalMetadataFinding",
    "compare_local_catalog_metadata",
    "render_local_catalog_metadata",
)
