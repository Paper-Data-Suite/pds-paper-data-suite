"""Exact Suite #16 official-wheel evidence, without changing the live environment.

Default mode only inspects local wheel ZIP metadata and exact GitHub asset SHA-256
values. --fetch-official opts into network access. --profile-smoke opts into
executing installed package code in a disposable offline virtual environment.
Neither option is called by Suite startup or module discovery.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Final, Literal

GROUP: Final = "paper_data_suite.module_operations"
_MAX_WHEEL_BYTES = 24 * 1024 * 1024
_MAX_MEMBERS = 12000


class _CasePreservingConfigParser(configparser.ConfigParser):
    """Keep installed entry-point option spelling exact, not lowercased."""

    def optionxform(self, optionstr: str) -> str:
        return optionstr


@dataclass(frozen=True)
class OfficialWheel:
    component: str
    repository: str
    version: str
    distribution: str
    filename: str
    digest: str
    entry_point: str | None = None
    target: str | None = None

    @property
    def url(self) -> str:
        return (
            "https://github.com/Paper-Data-Suite/"
            f"{self.repository}/releases/download/v{self.version}/{self.filename}"
        )


# GitHub official release asset digests observed 2026-11-06.
# A release asset digest is not a separate publisher signing attestation.
OFFICIAL_WHEELS: Final[tuple[OfficialWheel, ...]] = (
    OfficialWheel(
        "core", "pds-core", "0.6.6", "pds-core",
        "pds_core-0.6.6-py3-none-any.whl",
        "d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301",
    ),
    OfficialWheel(
        "scoreform", "pds-scoreform", "0.13.0", "scoreform",
        "scoreform-0.13.0-py3-none-any.whl",
        "4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7",
        "scoreform", "scoreform.pds_operations:get_module_operations_profile",
    ),
    OfficialWheel(
        "quillan", "pds-quillan", "0.10.6", "quillan",
        "quillan-0.10.6-py3-none-any.whl",
        "7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb",
        "quillan", "quillan.pds_operations:get_module_operations_profile",
    ),
    OfficialWheel(
        "concord", "pds-concord", "0.3.4", "pds-concord",
        "pds_concord-0.3.4-py3-none-any.whl",
        "35fbebf4338420c83047f0cb4a09d06b22bb493abf4d67e6082e59ae4fc35b23",
        "concord", "concord.pds_operations:get_module_operations_profile",
    ),
    OfficialWheel(
        "meridian", "pds-meridian", "0.4.2", "pds-meridian",
        "pds_meridian-0.4.2-py3-none-any.whl",
        "484f0ba3d7ca47d392bae26573c299eb02089d23a5caa3bd11c3ce3ddb45ead5",
        "meridian", "meridian.pds_operations:get_module_operations_profile",
    ),
    OfficialWheel(
        "vitrine", "pds-vitrine", "0.4.0", "pds-vitrine",
        "pds_vitrine-0.4.0-py3-none-any.whl",
        "0255f9ddad3a7b5216316a964e171271e10655f5822380e64a1254a7e439dfd2",
        "vitrine", "vitrine.pds_operations:get_module_operations_profile",
    ),
    OfficialWheel(
        "portia", "pds-portia", "0.2.0", "pds-portia",
        "pds_portia-0.2.0-py3-none-any.whl",
        "7ae545e62740b4411736fc55e572a86384ed8714f1f65346d65e36a7943f3550",
        "portia", "portia.pds_operations:get_module_operations_profile",
    ),
)

WheelStatus = Literal[
    "not_supplied", "digest_mismatch", "invalid_archive", "invalid_metadata",
    "entry_point_missing", "entry_point_mismatch", "verified_metadata",
]


@dataclass(frozen=True)
class WheelEvidence:
    component: str
    version: str
    sha256: str
    status: WheelStatus


def _normalized(name: str) -> str:
    return "-".join(
        "".join(c if c.isalnum() else "-" for c in name.lower()).split("-")
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row(spec: OfficialWheel, status: WheelStatus) -> WheelEvidence:
    return WheelEvidence(spec.component, spec.version, spec.digest, status)


def inspect_official_wheel(directory: Path, spec: OfficialWheel) -> WheelEvidence:
    """Verify exact release bytes before parsing; never import provider code."""
    path = directory / spec.filename
    if not path.is_file() or path.is_symlink():
        return _row(spec, "not_supplied")
    if path.stat().st_size > _MAX_WHEEL_BYTES:
        return _row(spec, "invalid_archive")
    if _hash_file(path) != spec.digest:
        return _row(spec, "digest_mismatch")
    try:
        prefix = f"{spec.distribution.replace('-', '_')}-{spec.version}.dist-info/"
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > _MAX_MEMBERS or len(names) != len(set(names)):
                return _row(spec, "invalid_archive")
            metadata_name = prefix + "METADATA"
            if metadata_name not in names:
                return _row(spec, "invalid_metadata")
            raw = archive.read(metadata_name)
            if len(raw) > 128_000:
                return _row(spec, "invalid_metadata")
            fields = Parser().parsestr(raw.decode("utf-8"), headersonly=True)
            if (
                _normalized(fields.get("Name", ""))
                != _normalized(spec.distribution)
                or fields.get("Version") != spec.version
            ):
                return _row(spec, "invalid_metadata")
            if spec.entry_point is not None:
                entry_path = prefix + "entry_points.txt"
                if entry_path not in names:
                    return _row(spec, "entry_point_missing")
                ini = archive.read(entry_path)
                if len(ini) > 64_000:
                    return _row(spec, "invalid_metadata")
                config = _CasePreservingConfigParser(
                    interpolation=None, strict=True
                )
                config.read_file(io.StringIO(ini.decode("utf-8")))
                if (
                    not config.has_section(GROUP)
                    or not config.has_option(GROUP, spec.entry_point)
                ):
                    return _row(spec, "entry_point_missing")
                if config.get(GROUP, spec.entry_point).strip() != spec.target:
                    return _row(spec, "entry_point_mismatch")
    except (
        OSError, ValueError, UnicodeDecodeError, zipfile.BadZipFile,
        configparser.Error, KeyError, RuntimeError,
    ):
        return _row(spec, "invalid_archive")
    return _row(spec, "verified_metadata")


def inspect_wheelhouse(
    directory: Path, specs: tuple[OfficialWheel, ...] = OFFICIAL_WHEELS
) -> tuple[WheelEvidence, ...]:
    return tuple(inspect_official_wheel(directory, spec) for spec in specs)


def fetch_official_wheels(directory: Path) -> None:
    """Download only after a user explicitly requests this action."""
    directory.mkdir(parents=True, exist_ok=True)
    for spec in OFFICIAL_WHEELS:
        destination = directory / spec.filename
        if destination.is_symlink():
            raise ValueError(f"symlinked wheel path: {spec.component}")
        if destination.exists():
            if _hash_file(destination) != spec.digest:
                raise ValueError(
                    f"pre-existing wheel digest mismatch: {spec.component}"
                )
            continue
        handle, tmp_name = tempfile.mkstemp(
            prefix=".pds16-", suffix=".partial", dir=directory
        )
        try:
            with os.fdopen(handle, "wb") as output:
                with urllib.request.urlopen(spec.url, timeout=35) as remote:
                    total = 0
                    while chunk := remote.read(1024 * 1024):
                        total += len(chunk)
                        if total > _MAX_WHEEL_BYTES:
                            raise ValueError("download exceeds size limit")
                        output.write(chunk)
            if _hash_file(Path(tmp_name)) != spec.digest:
                raise ValueError(f"downloaded wheel digest mismatch: {spec.component}")
            os.replace(tmp_name, destination)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)


_PROFILE_SCRIPT = """
import json
from pds_core.provider_diagnostics import diagnose_core_providers
results = diagnose_core_providers(provider_kind='module_operations')
rows = []
for result in results:
    meta = result.metadata
    rows.append({'module': meta.entry_point_name, 'code': result.code})
print('_PDS16_RESULT=' + json.dumps(rows, sort_keys=True))
"""


def run_disposable_profile_smoke(directory: Path) -> tuple[str, ...]:
    """Explicit zero-argument profile execution in a disposable offline venv.

    The venv is *not* an OS sandbox. No actual readiness/attention is invoked.
    Missing third-party wheels may prevent complete profile qualification.
    """
    if any(row.status != "verified_metadata" for row in inspect_wheelhouse(directory)):
        raise ValueError("all seven exact release wheels must be verified")
    with tempfile.TemporaryDirectory(prefix="pds16-wheel-smoke-") as scratch:
        root = Path(scratch)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        # Never inherit PDS workspace pointers or Python module search paths.
        env = {
            key: value for key, value in os.environ.items()
            if not key.upper().startswith(("PDS_", "PAPER_DATA_SUITE_"))
            and key.upper() not in {"PYTHONPATH", "PYTHONHOME"}
        }
        env.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "TMP": str(root), "TEMP": str(root), "TMPDIR": str(root),
            "HOME": str(root), "USERPROFILE": str(root),
            "APPDATA": str(root), "LOCALAPPDATA": str(root),
        })
        install = subprocess.run(
            [
                str(python), "-I", "-m", "pip", "install", "--isolated",
                "--no-index", "--no-deps", "--no-compile",
                *(str(directory / spec.filename) for spec in OFFICIAL_WHEELS),
            ],
            cwd=root, env=env, capture_output=True, text=True,
            timeout=150, check=False,
        )
        if install.returncode:
            return ("install_failed",)
        executed = subprocess.run(
            [str(python), "-I", "-B", "-c", _PROFILE_SCRIPT],
            cwd=root, env=env, capture_output=True, text=True,
            timeout=90, check=False,
        )
        if executed.returncode:
            return ("profile_import_or_diagnosis_failed",)
        lines = [
            line for line in executed.stdout.splitlines()
            if line.startswith("_PDS16_RESULT=")
        ]
        if len(lines) != 1:
            return ("profile_result_unavailable",)
        try:
            records = json.loads(lines[0].partition("=")[2])
            if not isinstance(records, list) or len(records) > 128:
                return ("profile_result_invalid",)
            results = {
                row["module"]: row["code"] for row in records
                if isinstance(row, dict)
                and type(row.get("module")) is str
                and type(row.get("code")) is str
            }
        except (ValueError, KeyError, TypeError):
            return ("profile_result_invalid",)
        allowed = [
            spec.component for spec in OFFICIAL_WHEELS
            if spec.component != "core"
        ]
        return tuple(
            f"{name}:{results.get(name, 'not_observed')}" for name in allowed
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument(
        "--fetch-official", action="store_true",
        help="explicitly download seven fixed GitHub release assets",
    )
    parser.add_argument(
        "--require-complete", action="store_true",
        help="fail unless all seven wheel digests and metadata match",
    )
    parser.add_argument(
        "--profile-smoke", action="store_true",
        help="execute Core profile factories in an offline disposable venv",
    )
    args = parser.parse_args(argv)
    wheelhouse = args.wheelhouse.resolve()
    try:
        if args.fetch_official:
            fetch_official_wheels(wheelhouse)
        if not wheelhouse.is_dir():
            raise ValueError("wheelhouse directory does not exist")
        evidence = inspect_wheelhouse(wheelhouse)
        for row in evidence:
            print(
                f"PDS16_WHEEL {row.component} {row.version} "
                f"{row.status} sha256={row.sha256}"
            )
        complete = all(row.status == "verified_metadata" for row in evidence)
        if args.profile_smoke:
            if not complete:
                raise ValueError("profile smoke requires seven verified wheel files")
            outcomes = run_disposable_profile_smoke(wheelhouse)
            for outcome in outcomes:
                print("PDS16_INSTALLED_PROFILE " + outcome)
            expected = {
                f"{spec.component}:provider.valid" for spec in OFFICIAL_WHEELS
                if spec.component != "core"
            }
            return 0 if len(outcomes) == 6 and set(outcomes) == expected else 1
        if args.require_complete and not complete:
            return 1
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        # No raw subprocess stderr, stack traces, or private local paths.
        print(
            "PDS16_WHEEL_PROBE_REFUSED: " + error.__class__.__name__,
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
