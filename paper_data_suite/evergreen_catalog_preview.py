"""Issue #49 Slice 58: explicit, offline, authenticated-catalog CLI preview.

No catalog preview is a statement about installed bytes, launch eligibility,
update readiness, protected key custody, or exact integration qualification.
The operator-supplied pin MUST have an independent provenance to be trusted.
No network, package installation, module import, or classroom workspace read.
"""

from __future__ import annotations

import stat
from datetime import datetime
from pathlib import Path

from paper_data_suite.evergreen_catalog_state import (
    CatalogSnapshot,
    CatalogStateError,
    load_catalog_cache,
)
from paper_data_suite.evergreen_trust_provisioning import (
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)

_MAX_TRUST_POLICY = 24 * 1024
_MAX_CATALOG_CACHE = 4 * 1024 * 1024


class CatalogPreviewError(ValueError):
    """Cannot independently validate the supplied offline catalog preview."""


def _read_regular(path: Path, maximum: int, label: str) -> bytes:
    """Read a bounded ordinary file; refuse symlinks and Windows reparse points."""
    if not isinstance(path, Path):
        raise CatalogPreviewError(f"{label} must be a filesystem Path")
    target = path.absolute()
    try:
        for member in (target, *target.parents):
            info = member.lstat()
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise CatalogPreviewError(f"unsafe {label} path")
        before = target.stat()
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= maximum:
            raise CatalogPreviewError(f"invalid {label} size or type")
        with target.open("rb") as handle:
            data = handle.read(maximum + 1)
        after = target.stat()
        if (
            len(data) != before.st_size
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or after.st_ino != before.st_ino
        ):
            raise CatalogPreviewError(f"{label} changed during read")
    except OSError as error:
        raise CatalogPreviewError(f"unavailable {label}") from error
    return data


def render_catalog_preview(snapshot: CatalogSnapshot) -> str:
    """Format previously verified *claims*, never an installed-state verdict."""
    if not isinstance(snapshot, CatalogSnapshot):
        raise CatalogPreviewError("verified catalog snapshot required")
    lines = [
        "Paper Data Suite — offline signed release catalog (diagnostic)",
        "",
        "CATALOG AUTHENTICATION IS NOT INSTALLATION OR LAUNCH APPROVAL.",
        "Installed bytes: NOT ASSESSED | Launch eligibility: NOT ASSESSED",
        "Update readiness: NOT ASSESSED | Exact integration: NOT ASSESSED",
        "The supplied trust-policy SHA-256 must come from an independent authority.",
        "",
        "Registry revision: " + str(snapshot.registry.claims.window.revision),
        "Registry expires: " + snapshot.registry.claims.window.expires_at.isoformat(),
        "Cache accepted: " + snapshot.accepted_at.isoformat(),
        "",
        "Registered components and delegated release claims:",
    ]
    by_component = {item.claims.component_id: item for item in snapshot.modules}
    for registered in sorted(
        snapshot.registry.claims.modules, key=lambda item: item.component_id
    ):
        lines.append(
            f"  {registered.component_id} ({registered.distribution}) "
            f"— {registered.repository}"
        )
        document = by_component.get(registered.component_id)
        if document is None:
            lines.append("    No current signed release document in cache")
            continue
        lines.append(f"    Publisher revision: {document.claims.window.revision}")
        for release in sorted(
            document.claims.releases,
            key=lambda item: tuple(
                int(x) for x in item.version.split(".post")[0].split(".")
            ),
        ):
            label = "REVOKED" if release.revoked else "SIGNED CLAIM ONLY"
            lines.append(f"    {release.version} — {label}")
            lines.append(f"      Wheel: {release.wheel}")
            lines.append(f"      SHA-256: {release.sha256}")
    lines.extend(("", "Signed integration claims (not installed-wheel qualified):"))
    if not snapshot.integrations:
        lines.append("  None in this cache")
    else:
        for integration_document in sorted(
            snapshot.integrations, key=lambda item: item.claims.feature_id
        ):
            lines.append(
                f"  {integration_document.claims.feature_id}: "
                f"signed result={integration_document.claims.result}; "
                "installed composition NOT VERIFIED"
            )
    lines.extend(
        (
            "",
            "No network access, state mutation, package execution, "
            "or launch was performed.",
        )
    )
    return "\n".join(lines) + "\n"


def inspect_offline_catalog_preview(
    *,
    catalog_cache: Path,
    trust_policy: Path,
    pinned_policy_sha256: str,
    now: datetime,
    compare_local_metadata: bool = False,
) -> str:
    """Read signed cached metadata under a supplied, separately pinned keyring.

    The command-line SHA-256 input is NOT independently authenticated by this
    function. Its origin must be verified outside the Suite process.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise CatalogPreviewError("timezone-aware current time is required")
    if (
        type(pinned_policy_sha256) is not str
        or len(pinned_policy_sha256) != 64
        or any(c not in "0123456789abcdef" for c in pinned_policy_sha256)
    ):
        raise CatalogPreviewError("independent trust-policy SHA-256 is required")
    raw_policy = _read_regular(trust_policy, _MAX_TRUST_POLICY, "trust policy")
    # Read the cache first to reject unsafe filesystem targets before any
    # cryptographic parsing. The catalog loader reads and verifies it again.
    _read_regular(catalog_cache, _MAX_CATALOG_CACHE, "signed catalog cache")
    try:
        pinned = load_digest_pinned_trust_policy(
            raw_policy, pinned_sha256=pinned_policy_sha256
        )
        snapshot = load_catalog_cache(catalog_cache, trust=pinned.keyring, now=now)
    except (TrustProvisioningError, CatalogStateError, ValueError, OSError) as error:
        raise CatalogPreviewError(
            "signed cached release metadata could not be authenticated"
        ) from error
    if snapshot is None:
        raise CatalogPreviewError("signed release cache is missing")
    output = render_catalog_preview(snapshot)
    if compare_local_metadata:
        from paper_data_suite.evergreen_catalog_local_metadata import (
            render_local_catalog_metadata,
        )

        output += render_local_catalog_metadata(snapshot)
    return output


__all__ = (
    "CatalogPreviewError",
    "inspect_offline_catalog_preview",
    "render_catalog_preview",
)
