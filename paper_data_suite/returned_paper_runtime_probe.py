"""#19A3: explicit isolated installed-paper diagnostic; never dispatch authority.

Call only in a deliberately selected disposable qualification environment.
This imports installed native decoder libraries and producer profile factories;
it is NOT safe to invoke on Teacher Home startup, help, or read-only previews.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from importlib import import_module, metadata
from pathlib import Path
from typing import Final, Literal

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from paper_data_suite.returned_paper_admission import (
    PaperAdmissionV1,
    inspect_paper_admission,
)
from paper_data_suite.returned_paper_installed_wheels import qualify_installed_profiles
from paper_data_suite.returned_paper_payload_audit import (
    InstalledPayloadAuditV1,
    audit_installed_paper_payloads,
)

RUNTIME_PROBE_VERSION: Final[str] = "1"
_EXPECTED_PROFILES: Final[tuple[str, str]] = ("quillan", "scoreform")
# Windows and Ubuntu Python 3.11 native #18 installed-wheel validation.
_NATIVE_CONTRACT: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("pypdfium2", ">=5.13,<6", "pypdfium2", "PdfDocument"),
    ("zxing-cpp", ">=2.3,<3", "zxingcpp", "read_barcodes"),
    ("Pillow", ">=11,<13", "PIL.Image", "open"),
)

RuntimeProbeStatus = Literal[
    "runtime_unqualified",
    "candidate_unqualified",
    "payload_unverified",
    "native_unverified",
    "profiles_unverified",
    "diagnostic_match",
]


class RuntimeProbeError(ValueError):
    """The explicit runtime probe received invalid caller input."""


@dataclass(frozen=True, slots=True)
class InstalledPaperRuntimeProbeV1:
    """A bounded observation, never a processing authorization or bearer token."""

    status: RuntimeProbeStatus
    payload_matched: bool
    native_contract_observed: bool
    core_profiles_observed: bool
    native_versions: tuple[tuple[str, str], ...] = ()
    contract_version: Literal["1"] = "1"
    processing_status: Literal["preview_only"] = "preview_only"
    qualified_modules: frozenset[str] = frozenset()
    producer_dispatch_authorized: Literal[False] = False

    def __post_init__(self) -> None:
        allowed = {
            "runtime_unqualified", "candidate_unqualified",
            "payload_unverified", "native_unverified",
            "profiles_unverified", "diagnostic_match",
        }
        if self.status not in allowed or self.contract_version != RUNTIME_PROBE_VERSION:
            raise RuntimeProbeError("unknown runtime-probe status or version")
        if (
            self.processing_status != "preview_only"
            or self.producer_dispatch_authorized is not False
            or self.qualified_modules
        ):
            raise RuntimeProbeError("runtime observation cannot authorize dispatch")
        if any(type(x) is not bool for x in (
            self.payload_matched,
            self.native_contract_observed,
            self.core_profiles_observed,
        )):
            raise RuntimeProbeError("invalid runtime-probe evidence flag")
        if type(self.native_versions) is not tuple or any(
            type(row) is not tuple or len(row) != 2
            or any(type(item) is not str or not item for item in row)
            for row in self.native_versions
        ):
            raise RuntimeProbeError("invalid native dependency evidence")
        expected_flags: dict[str, tuple[bool, bool, bool]] = {
            "runtime_unqualified": (False, False, False),
            "candidate_unqualified": (False, False, False),
            "payload_unverified": (False, False, False),
            "native_unverified": (True, False, False),
            "profiles_unverified": (True, True, False),
            "diagnostic_match": (True, True, True),
        }
        if (
            self.payload_matched,
            self.native_contract_observed,
            self.core_profiles_observed,
        ) != expected_flags[self.status]:
            raise RuntimeProbeError("runtime evidence contradicts stage")
        if self.native_contract_observed:
            if tuple(name for name, _ in self.native_versions) != (
                "pypdfium2", "zxing-cpp", "Pillow"
            ):
                raise RuntimeProbeError("native dependency evidence incomplete")
        elif self.native_versions:
            raise RuntimeProbeError("native versions claimed before native check")


def _isolated_supported_runtime() -> bool:
    """Match only the already-rehearsed host and a distinct active venv."""
    return (
        sys.platform in {"win32", "linux"}
        and sys.version_info[:2] == (3, 11)
        and Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve()
        and Path(sys.executable).absolute().is_relative_to(Path(sys.prefix).absolute())
    )


def _native_versions_and_symbols() -> tuple[tuple[str, str], ...]:
    """Check exact rehearsal dependency ranges and native import surface.

    An imported symbol is not a successful scan. The caller is responsible for
    running full native synthetic PDF acceptance in a disposable environment.
    """
    observed: list[tuple[str, str]] = []
    for distribution, specifier, module_name, symbol in _NATIVE_CONTRACT:
        version = metadata.version(distribution)
        if Version(version) not in SpecifierSet(specifier):
            raise RuntimeProbeError("native dependency version unqualified")
        module = import_module(module_name)
        if not callable(getattr(module, symbol, None)):
            raise RuntimeProbeError("native dependency API unavailable")
        observed.append((distribution, version))
    return tuple(observed)


def inspect_installed_paper_runtime(
    wheelhouse: Path,
) -> InstalledPaperRuntimeProbeV1:
    """Explicit one-shot diagnostic of a controlled isolated installed venv.

    Never convert the returned object into #18's qualified_modules. All profile
    imports run only AFTER exact A1 version, A2 payload and native checks.
    Unexpected import/metadata errors become safe status codes, not tracebacks.
    No producer handler or teacher scan is called and no consent is generated.
    """
    if not isinstance(wheelhouse, Path):
        raise RuntimeProbeError("a local wheelhouse Path is required")
    if not _isolated_supported_runtime():
        return InstalledPaperRuntimeProbeV1("runtime_unqualified", False, False, False)
    try:
        candidate = inspect_paper_admission()
        correct = (
            isinstance(candidate, PaperAdmissionV1)
            and candidate.core_state == "exact_release_candidate"
            and candidate.exact_release_candidates == ("scoreform", "quillan")
            and candidate.processing_status == "preview_only"
            and not candidate.qualified_modules
        )
    except (Exception, KeyboardInterrupt):
        correct = False
    if not correct:
        return InstalledPaperRuntimeProbeV1(
            "candidate_unqualified", False, False, False,
        )
    try:
        payload = audit_installed_paper_payloads(wheelhouse)
        if not isinstance(payload, InstalledPayloadAuditV1):
            raise RuntimeProbeError("installed payload evidence is not typed")
        if payload.producer_dispatch_authorized is not False:
            raise RuntimeProbeError("installed payload audit claimed authorization")
        if tuple(row.distribution for row in payload.wheels) != (
            "pds-core", "scoreform", "quillan"
        ):
            raise RuntimeProbeError("installed wheel identity mismatch")
    except (Exception, KeyboardInterrupt):
        return InstalledPaperRuntimeProbeV1("payload_unverified", False, False, False)
    try:
        versions = _native_versions_and_symbols()
    except (Exception, KeyboardInterrupt):
        return InstalledPaperRuntimeProbeV1("native_unverified", True, False, False)
    try:
        profiles = qualify_installed_profiles()
        if profiles != _EXPECTED_PROFILES:
            raise RuntimeProbeError("installed profile membership mismatch")
    except (Exception, KeyboardInterrupt):
        return InstalledPaperRuntimeProbeV1(
            "profiles_unverified", True, True, False, versions,
        )
    return InstalledPaperRuntimeProbeV1(
        "diagnostic_match", True, True, True, versions,
    )


__all__ = (
    "RUNTIME_PROBE_VERSION",
    "RuntimeProbeError",
    "InstalledPaperRuntimeProbeV1",
    "inspect_installed_paper_runtime",
)
