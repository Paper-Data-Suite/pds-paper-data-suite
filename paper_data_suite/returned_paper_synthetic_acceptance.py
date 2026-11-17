"""#19E2: opt-in, exact synthetic two-page native PDF/QR witness.

This is an isolated *decode* acceptance aid, not a producer E2E test,
Core custody proof, release provenance attestation, or dispatch permission.
The fixture is intentionally synthetic and has no student information.
"""

from __future__ import annotations

import argparse
import hashlib
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from paper_data_suite.returned_paper_readonly_decode import (
    DecodedPage,
    DecodeLimits,
    DecoderBackendUnavailable,
    PageDecoder,
    decode_with_optional_backends,
)

FIXTURE_SHA256: Final[str] = (
    "21d18d5fc7f5451d4f661cf944fb0def41651e1d3a8d22d3dbb5876e869a9548"
)
FIXTURE_NAME: Final[str] = "issue19_two_page_synthetic_pds2.pdf"
_EXPECTED_QR: Final[tuple[str, str]] = (
    "PDS2|m=scoreform|c=english12_p4|w=essay|r=route_001",
    "PDS2|m=quillan|c=english12_p4|w=essay|r=route_002",
)
_EXPECTED_OWNERS: Final[tuple[str, str]] = ("scoreform", "quillan")
_MAX_BYTES: Final[int] = 1024 * 1024
_REPARSE: Final[int] = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

FixtureStatus = Literal[
    "fixture_invalid", "backend_unavailable", "decode_mismatch", "native_verified"
]
Parser = Callable[[str], object]


class SyntheticAcceptanceError(ValueError):
    """An invalid #19E2 observation or explicit fixture request."""


@dataclass(frozen=True, slots=True)
class SyntheticNativeWitnessV1:
    """No executable authority can be derived from this bounded observation."""

    status: FixtureStatus
    verified_pages: int = 0
    verified_owners: tuple[str, ...] = ()
    contract_version: Literal["1"] = "1"
    processing_status: Literal["preview_only"] = "preview_only"
    producer_dispatch_authorized: Literal[False] = False
    qualified_modules: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if (
            self.status not in {
                "fixture_invalid", "backend_unavailable", "decode_mismatch",
                "native_verified",
            }
            or self.contract_version != "1"
            or self.processing_status != "preview_only"
            or self.producer_dispatch_authorized is not False
            or type(self.qualified_modules) is not frozenset
            or self.qualified_modules
            or type(self.verified_pages) is not int
            or type(self.verified_owners) is not tuple
        ):
            raise SyntheticAcceptanceError("fixture witness cannot grant dispatch")
        success = self.status == "native_verified"
        if success != (self.verified_pages == 2
                       and self.verified_owners == _EXPECTED_OWNERS):
            raise SyntheticAcceptanceError("contradictory native fixture evidence")
        if not success and (self.verified_pages or self.verified_owners):
            raise SyntheticAcceptanceError("failed fixture cannot claim pages")


def _safe_fixture_bytes(path: Path) -> bytes:
    """Read only an exact pinned, non-linked synthetic test PDF."""
    if (
        not isinstance(path, Path) or not path.is_absolute()
        or path.name != FIXTURE_NAME or ".." in path.parts
    ):
        raise SyntheticAcceptanceError("explicit fixed fixture path required")
    try:
        for item in (path, *path.parents):
            meta = item.lstat()
            if stat.S_ISLNK(meta.st_mode) or (
                getattr(meta, "st_file_attributes", 0) & _REPARSE
            ):
                raise SyntheticAcceptanceError("fixture path has linked component")
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= _MAX_BYTES:
            raise SyntheticAcceptanceError("invalid synthetic PDF fixture")
        with path.open("rb") as source:
            data = source.read(_MAX_BYTES + 1)
        after = path.stat()
        if (
            len(data) != before.st_size
            or (before.st_size, before.st_mtime_ns, before.st_ino)
            != (after.st_size, after.st_mtime_ns, after.st_ino)
            or not data.startswith(b"%PDF-")
            or hashlib.sha256(data).hexdigest() != FIXTURE_SHA256
        ):
            raise SyntheticAcceptanceError("synthetic fixture changed or mismatched")
        return data
    except (OSError, RuntimeError, ValueError) as error:
        raise SyntheticAcceptanceError("synthetic fixture unavailable") from error


def _core_parser(value: str) -> object:
    from pds_core.pds2 import parse_pds2_payload

    return parse_pds2_payload(value)


def inspect_two_page_synthetic_fixture(
    fixture: Path,
    *,
    decoder: PageDecoder = decode_with_optional_backends,
    parse: Parser = _core_parser,
) -> SyntheticNativeWitnessV1:
    """Check actual PDFium/ZXing/Pillow path and Core PDS2 parser by default.

    Injectable decoder/parser are deterministic test seams only; an injected
    successful result never authorizes a handler or claims official provenance.
    """
    if not callable(decoder) or not callable(parse):
        raise SyntheticAcceptanceError("native fixture callbacks unavailable")
    try:
        data = _safe_fixture_bytes(fixture)
    except (Exception, KeyboardInterrupt):
        return SyntheticNativeWitnessV1("fixture_invalid")
    try:
        pages = decoder(data, "pdf", DecodeLimits())
    except DecoderBackendUnavailable:
        return SyntheticNativeWitnessV1("backend_unavailable")
    except (Exception, KeyboardInterrupt):
        return SyntheticNativeWitnessV1("decode_mismatch")
    if (
        type(pages) is not tuple or len(pages) != 2
        or any(not isinstance(p, DecodedPage) or p.failed or p.truncated
               for p in pages)
    ):
        return SyntheticNativeWitnessV1("decode_mismatch")
    for number, (page, exact) in enumerate(zip(pages, _EXPECTED_QR, strict=True)):
        if page.payloads != (exact,):
            return SyntheticNativeWitnessV1("decode_mismatch")
        try:
            locator = parse(exact)
            if getattr(locator, "module_id", None) != _EXPECTED_OWNERS[number]:
                raise SyntheticAcceptanceError("Core PDS2 owner mismatch")
        except (Exception, KeyboardInterrupt):
            return SyntheticNativeWitnessV1("decode_mismatch")
    return SyntheticNativeWitnessV1("native_verified", 2, _EXPECTED_OWNERS)


def render_synthetic_fixture_witness(result: SyntheticNativeWitnessV1) -> str:
    """Do not expose file paths or payloads in the acceptance report."""
    if not isinstance(result, SyntheticNativeWitnessV1):
        raise SyntheticAcceptanceError("typed fixture witness required")
    lines = [
        "PDS #19 - synthetic two-page native PDF acceptance (READ ONLY)",
        f"Native fixture status: {result.status}.",
        f"Verified physical pages: {result.verified_pages}.",
    ]
    if result.status == "native_verified":
        lines.append("Physical page owners: 1 scoreform; 2 quillan.")
    else:
        lines.append("The two-page native decoder acceptance did NOT pass.")
    lines.extend((
        "No Core retention, producer handlers, scoring or grades were written.",
        "No official installed-wheel provenance or producer E2E is attested.",
        "This witness is NEVER a qualified_modules or dispatch credential.",
    ))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Opt-in offline native acceptance: no workspace or network operation."""
    cli = argparse.ArgumentParser(description="Read-only PDS synthetic PDF witness")
    cli.add_argument("--fixture", type=Path, required=True)
    cli.add_argument("--wheelhouse", type=Path, required=True)
    args = cli.parse_args(argv)
    witness = inspect_two_page_synthetic_fixture(args.fixture)
    sys.stdout.write(render_synthetic_fixture_witness(witness))
    try:
        from paper_data_suite.returned_paper_action_time_readiness import (
            inspect_paper_action_time_readiness,
        )

        readiness = inspect_paper_action_time_readiness(args.wheelhouse)
        diagnostic_match = readiness.status == "diagnostic_match_not_admitted"
    except (Exception, KeyboardInterrupt):
        diagnostic_match = False
    sys.stdout.write(
        "Exact installed-runtime diagnostic match: "
        + ("yes" if diagnostic_match else "no") + ".\n"
        "No teacher dispatch is enabled by either acceptance check.\n"
    )
    return 0 if witness.status == "native_verified" and diagnostic_match else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "FIXTURE_NAME", "FIXTURE_SHA256", "FixtureStatus", "SyntheticAcceptanceError",
    "SyntheticNativeWitnessV1", "inspect_two_page_synthetic_fixture",
    "render_synthetic_fixture_witness", "main",
)
