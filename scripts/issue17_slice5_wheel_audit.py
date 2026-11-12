"""Suite #17: offline exact official-wheel metadata check, never installs wheels.

The recorded digests are release-asset observations, not publisher signatures.
Concord and Vitrine paper extras must not be force-installed together while
published pypdfium2 requirements conflict; Concord #170 owns that change.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import zipfile
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Final

from packaging.requirements import Requirement


@dataclass(frozen=True)
class WheelSpec:
    filename: str
    distribution: str
    version: str
    sha256: str
    routing_target: str | None
    routing_name: str | None


WHEELS: Final[tuple[WheelSpec, ...]] = (
    WheelSpec(
        "pds_core-0.6.6-py3-none-any.whl", "pds-core", "0.6.6",
        "d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301",
        None, None,
    ),
    WheelSpec(
        "scoreform-0.13.0-py3-none-any.whl", "scoreform", "0.13.0",
        "4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7",
        "scoreform.pds_module:get_module_profile", "scoreform",
    ),
    WheelSpec(
        "quillan-0.10.6-py3-none-any.whl", "quillan", "0.10.6",
        "7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb",
        "quillan.pds_module:get_module_profile", "quillan",
    ),
    WheelSpec(
        "pds_concord-0.3.4-py3-none-any.whl", "pds-concord", "0.3.4",
        "35fbebf4338420c83047f0cb4a09d06b22bb493abf4d67e6082e59ae4fc35b23",
        "concord.pds_module:get_module_profile", "concord",
    ),
    WheelSpec(
        "pds_vitrine-0.4.0-py3-none-any.whl", "pds-vitrine", "0.4.0",
        "0255f9ddad3a7b5216316a964e171271e10655f5822380e64a1254a7e439dfd2",
        "vitrine.pds_module:get_module_profile", "vitrine",
    ),
)

MAX_WHEEL_BYTES: Final[int] = 2_000_000
MAX_METADATA_BYTES: Final[int] = 256_000


class WheelAuditError(RuntimeError):
    """A pinned, metadata-only release check could not be qualified."""


class _CaseSensitiveConfigParser(configparser.ConfigParser):
    """Preserve exact entry-point name casing in wheel metadata."""

    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _wheel_parts(path: Path, spec: WheelSpec) -> tuple[bytes, str]:
    if path.is_symlink() or not path.is_file():
        raise WheelAuditError("official wheel missing or linked")
    if path.stat().st_size > MAX_WHEEL_BYTES:
        raise WheelAuditError("official wheel exceeds inspection bound")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != spec.sha256:
        raise WheelAuditError("official wheel SHA-256 mismatch")
    try:
        with zipfile.ZipFile(path) as archive:
            paths = archive.namelist()
            metadata_names = [p for p in paths if p.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise WheelAuditError("wheel metadata count is invalid")
            metadata_path = metadata_names[0]
            metadata_info = archive.getinfo(metadata_path)
            if metadata_info.file_size > MAX_METADATA_BYTES:
                raise WheelAuditError("wheel metadata too large")
            metadata = archive.read(metadata_path)
            ep_path = metadata_path.removesuffix("METADATA") + "entry_points.txt"
            entries = ""
            if ep_path in paths:
                entry_info = archive.getinfo(ep_path)
                if entry_info.file_size > MAX_METADATA_BYTES:
                    raise WheelAuditError("entry point metadata too large")
                entries = archive.read(ep_path).decode("utf-8")
            return metadata, entries
    except (OSError, zipfile.BadZipFile, UnicodeError) as error:
        raise WheelAuditError("official wheel metadata unreadable") from error


def _requirements(message: Message) -> tuple[Requirement, ...]:
    entries = message.get_all("Requires-Dist", [])
    return tuple(Requirement(value) for value in (entries or ()))


def _pdf_requirement(
    requirements: tuple[Requirement, ...], *, extra: str
) -> Requirement:
    matches = [
        requirement for requirement in requirements
        if requirement.name.lower().replace("_", "-") == "pypdfium2"
        and (
            requirement.marker is None
            or requirement.marker.evaluate({"extra": extra})
        )
    ]
    if len(matches) != 1:
        raise WheelAuditError("unexpected PDFium dependency declaration")
    return matches[0]


def audit_wheelhouse(root: Path) -> dict[str, object]:
    """Validate pinned official wheel *bytes* and metadata without installing."""
    if not root.is_dir() or root.is_symlink():
        raise WheelAuditError("wheelhouse directory unavailable")
    requirements_by_distribution: dict[str, tuple[Requirement, ...]] = {}
    rows: list[dict[str, object]] = []
    for spec in WHEELS:
        metadata, entries = _wheel_parts(root / spec.filename, spec)
        message = BytesParser(policy=default).parsebytes(metadata)
        if message["Name"] != spec.distribution or message["Version"] != spec.version:
            raise WheelAuditError("official wheel identity/version mismatch")
        parser = _CaseSensitiveConfigParser(interpolation=None)
        try:
            parser.read_string(entries or "[empty]\n")
        except configparser.Error as error:
            raise WheelAuditError("invalid entry-point metadata") from error
        if spec.routing_name is not None:
            if not parser.has_section("paper_data_suite.modules") or (
                parser.get("paper_data_suite.modules", spec.routing_name, fallback=None)
                != spec.routing_target
            ):
                raise WheelAuditError("official routing declaration mismatch")
        requirements_by_distribution[spec.distribution] = _requirements(message)
        rows.append({
            "distribution": spec.distribution,
            "version": spec.version,
            "sha256": spec.sha256,
            "routing_declared": spec.routing_name is not None,
            "official_release_asset_digest_checked": True,
        })

    concord = _pdf_requirement(requirements_by_distribution["pds-concord"], extra="")
    vitrine = _pdf_requirement(
        requirements_by_distribution["pds-vitrine"], extra="paper"
    )
    if (
        not concord.specifier.contains("4.30")
        or concord.specifier.contains("5.13")
        or vitrine.specifier.contains("4.30")
        or not vitrine.specifier.contains("5.13")
    ):
        raise WheelAuditError("PDFium conflict changed; re-audit producer releases")
    return {
        "schema_version": "1",
        "qualification": "exact-wheel-metadata-only",
        "wheel_count": len(rows),
        "wheels": rows,
        "concord_pdfium": str(concord.specifier),
        "vitrine_paper_pdfium": str(vitrine.specifier),
        "shared_pdfium_dependency_resolution": "blocked_by_concord_170",
        "combined_paper_wheel_installation_qualified": False,
        "provider_execution_performed": False,
        "publisher_signature_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline pinned Suite #17 wheel audit")
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit_wheelhouse(args.wheelhouse)
        args.evidence.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (WheelAuditError, OSError, ValueError):
        print("SUITE17_EXACT_WHEEL_AUDIT_NOT_QUALIFIED")
        return 1
    print("SUITE17_EXACT_WHEEL_METADATA_ACCEPTED_CONCORD170_OPEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
