"""Inspect one candidate PDS release wheel without installing or importing it."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import zipfile
from collections.abc import Sequence
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import cast


class _CaseSensitiveConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


class WheelInspectionError(RuntimeError):
    """Raised when a candidate wheel cannot be inspected safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _single_member(names: Sequence[str], suffix: str) -> str:
    matches = tuple(name for name in names if name.endswith(suffix))
    if len(matches) != 1:
        raise WheelInspectionError(
            f"expected exactly one wheel member ending with {suffix!r}; "
            f"found {len(matches)}"
        )
    return matches[0]


def inspect_wheel(path: Path) -> dict[str, object]:
    """Return deterministic release metadata for one ordinary wheel file."""
    if not path.is_file() or path.suffix != ".whl":
        raise WheelInspectionError(f"candidate wheel does not exist: {path}")

    try:
        with zipfile.ZipFile(path) as archive:
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise WheelInspectionError(
                    f"wheel contains corrupt member: {corrupt_member}"
                )
            names = tuple(archive.namelist())
            metadata_member = _single_member(names, ".dist-info/METADATA")
            entry_member_matches = tuple(
                name
                for name in names
                if name.endswith(".dist-info/entry_points.txt")
            )
            metadata = BytesParser(policy=policy.default).parsebytes(
                archive.read(metadata_member)
            )

            entry_points: dict[str, dict[str, str]] = {}
            if entry_member_matches:
                if len(entry_member_matches) != 1:
                    raise WheelInspectionError(
                        "wheel contains ambiguous entry_points.txt files"
                    )
                parser = _CaseSensitiveConfigParser(
                    interpolation=None,
                    strict=True,
                )
                parser.read_string(
                    archive.read(entry_member_matches[0]).decode("utf-8")
                )
                entry_points = {
                    section: dict(sorted(parser.items(section)))
                    for section in sorted(parser.sections())
                }
    except zipfile.BadZipFile as error:
        raise WheelInspectionError("candidate is not a readable wheel ZIP") from error

    name = metadata.get("Name")
    version = metadata.get("Version")
    requires_python = metadata.get("Requires-Python")
    if not all(isinstance(value, str) and value for value in (name, version)):
        raise WheelInspectionError("wheel metadata lacks Name or Version")

    return {
        "filename": path.name,
        "sha256": _sha256(path),
        "distribution": name,
        "version": version,
        "requires_python": requires_python,
        "entry_points": entry_points,
        "requires_dist": sorted(
            str(item) for item in metadata.get_all("Requires-Dist", [])
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", nargs="+", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    wheels = cast(list[Path], args.wheels)
    result = [inspect_wheel(path.resolve()) for path in wheels]
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
