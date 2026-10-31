"""Issue #49 Slice 101: signed Quillan *lab-only* launch acceptance.

This deliberately cannot grant production launch/activation authority. It reads
an isolated disposable venv, verifies independently pinned signed release
claims and installed wheel bytes, checks its runtime dependency closure and
console launcher owner, then MAY execute only ``quillan --help`` on opt-in.
No mutation, package installation, arbitrary arguments or classroom workspace.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Final

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_installed_launch_eligibility import (
    InstalledLaunchEvidenceError,
    _verify_installed_bytes,
)
from paper_data_suite.evergreen_release_artifacts import (
    ReleaseArtifactError,
    verify_signed_release_wheel,
)
from paper_data_suite.evergreen_staged_runtime import (
    StagedRuntimeError,
    _wrapper,
)
from paper_data_suite.evergreen_trust_provisioning import (
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)

_MAX_POLICY: Final = 24 * 1024
_MAX_ENVELOPE: Final = 256 * 1024
_MAX_CONFIG: Final = 16 * 1024
_EXPECTED_NAME: Final = "historical_suite_010_quillan_0106_FULL_DEPS_LAB"
_VERSION: Final = re.compile(r"(3\.\d{1,2})(?:\.\d+)?\Z")


class SignedLabLaunchError(ValueError):
    """Isolated lab proof is incomplete; never dispatch an application."""


@dataclass(frozen=True, slots=True)
class SignedLabObservation:
    distribution: str
    version: str
    wheel_sha256: str
    policy_sha256: str
    files_checked: int
    dependency_distributions_checked: int
    console_script: str
    wrapper_sha256: str
    status: str = "SIGNED_INSTALLED_LAB_MATCH_NO_PRODUCTION_LAUNCH_AUTHORITY"
    native_executable_authenticated: bool = False


def _ordinary(path: Path, *, directory: bool) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SignedLabLaunchError("required lab path missing") from exc
    if (
        bool(getattr(info, "st_file_attributes", 0) & 0x400)
        or stat.S_ISLNK(info.st_mode)
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    ):
        raise SignedLabLaunchError("lab path is reparse point or wrong file type")


def _read(path: Path, limit: int) -> bytes:
    _ordinary(path, directory=False)
    if path.stat().st_size > limit:
        raise SignedLabLaunchError("lab evidence file exceeds size limit")
    try:
        result = path.read_bytes()
    except OSError as exc:
        raise SignedLabLaunchError("lab evidence could not be read") from exc
    if not result or len(result) > limit:
        raise SignedLabLaunchError("lab evidence file outside limits")
    return result


def _version(root: Path) -> str:
    try:
        lines = _read(root / "pyvenv.cfg", _MAX_CONFIG).decode("utf-8-sig").splitlines()
    except UnicodeError as exc:
        raise SignedLabLaunchError("invalid pyvenv configuration encoding") from exc
    data: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise SignedLabLaunchError("malformed pyvenv configuration")
        key, value = [part.strip() for part in line.split("=", 1)]
        if key.lower() in data:
            raise SignedLabLaunchError("duplicate pyvenv configuration key")
        data[key.lower()] = value
    if data.get("include-system-site-packages", "").lower() != "false":
        raise SignedLabLaunchError("lab may not inherit system packages")
    raw = data.get("version", "")
    match = _VERSION.fullmatch(raw)
    if match is None:
        raise SignedLabLaunchError("missing lab interpreter version")
    return match.group(1)


def _packages(site: Path) -> dict[str, metadata.Distribution]:
    packages: dict[str, metadata.Distribution] = {}
    for dist in metadata.distributions(path=[str(site)]):
        info = getattr(dist, "_path", None)
        if not isinstance(info, Path) or info.parent != site:
            raise SignedLabLaunchError("ambiguous installed distribution location")
        _ordinary(info, directory=True)
        name = canonicalize_name(dist.metadata["Name"] or "")
        if not name or name in packages:
            raise SignedLabLaunchError("missing or duplicate distribution identity")
        packages[name] = dist
    return packages


def _dependency_closure(
    packages: dict[str, metadata.Distribution],
    *,
    root: str,
    python_minor: str,
) -> int:
    environment: dict[str, str] = {
        key: str(value) for key, value in default_environment().items()
    }
    environment["python_version"] = python_minor
    environment["python_full_version"] = python_minor + ".0"
    pending: list[tuple[str, str]] = [(root, "")]
    seen: set[tuple[str, str]] = set()
    while pending:
        name, extra = pending.pop()
        if (name, extra) in seen:
            continue
        seen.add((name, extra))
        if len(seen) > 512:
            raise SignedLabLaunchError("runtime dependency graph exceeds bounds")
        dist = packages.get(name)
        if dist is None:
            raise SignedLabLaunchError("required distribution missing from lab")
        requires_python = dist.metadata["Requires-Python"]
        try:
            if requires_python and not SpecifierSet(requires_python).contains(
                python_minor + ".0"
            ):
                raise SignedLabLaunchError("lab Python incompatible with distribution")
        except InvalidSpecifier as exc:
            raise SignedLabLaunchError("malformed installed Requires-Python") from exc
        environment["extra"] = extra
        for raw in dist.requires or ():
            try:
                required = Requirement(raw)
            except InvalidRequirement as exc:
                raise SignedLabLaunchError("invalid installed dependency") from exc
            if required.marker and not required.marker.evaluate(environment):
                continue
            if required.url is not None:
                raise SignedLabLaunchError("direct-URL dependency is not lab qualified")
            dependency = canonicalize_name(required.name)
            target = packages.get(dependency)
            if target is None:
                raise SignedLabLaunchError("required runtime dependency missing")
            if required.specifier and not required.specifier.contains(target.version):
                raise SignedLabLaunchError("installed dependency version mismatch")
            pending.append((dependency, ""))
            for selected_extra in required.extras:
                pending.append((dependency, selected_extra))
    return len({name for name, _ in seen})


def inspect_signed_quillan_lab(
    lab: Path,
    *,
    wheel: Path,
    policy: Path,
    independent_policy_sha256: str,
    registry: Path,
    module: Path,
    now: datetime,
) -> SignedLabObservation:
    """Read-only signed/installed correlation; input pin must be independent.

    Only the named disposable Quillan acceptance environment is permitted.
    This proof DOES NOT authenticate the native Windows EXE or transitive wheel
    provenance and cannot be converted to a production permission token.
    """
    if not isinstance(lab, Path) or lab.name != _EXPECTED_NAME:
        raise SignedLabLaunchError("refusing non-lab environment")
    root = lab.absolute()
    if root == Path(sys.prefix).absolute():
        raise SignedLabLaunchError("cannot inspect running Python as external lab")
    site = root / "Lib" / "site-packages"
    scripts = root / "Scripts"
    for directory in (root, root / "Lib", site, scripts):
        _ordinary(directory, directory=True)
    _ordinary(scripts / "python.exe", directory=False)
    minor = _version(root)
    packages = _packages(site)
    try:
        pinned = load_digest_pinned_trust_policy(
            _read(policy, _MAX_POLICY), pinned_sha256=independent_policy_sha256
        )
        signed = verify_signed_release_wheel(
            wheel,
            registry_envelope=_read(registry, _MAX_ENVELOPE),
            module_envelope=_read(module, _MAX_ENVELOPE),
            trust=pinned.keyring,
            now=now,
            version="0.10.6",
        )
    except (TrustProvisioningError, ReleaseArtifactError) as exc:
        raise SignedLabLaunchError("signed release evidence refused") from exc
    if (
        signed.component_id != "quillan"
        or canonicalize_name(signed.distribution) != "quillan"
        or signed.version != "0.10.6"
        or signed.console_script != "quillan"
        or signed.console_target != "quillan.cli:main"
    ):
        raise SignedLabLaunchError("wrong signed Quillan identity")
    quillan = packages.get("quillan")
    if quillan is None or quillan.version != signed.version:
        raise SignedLabLaunchError("installed Quillan version mismatches release")
    scripts_named = [
        (name, ep)
        for name, dist in packages.items()
        for ep in dist.entry_points
        if ep.group == "console_scripts" and ep.name.casefold() == "quillan"
    ]
    if (
        len(scripts_named) != 1
        or scripts_named[0][0] != "quillan"
        or scripts_named[0][1].name != "quillan"
        or scripts_named[0][1].value != signed.console_target
    ):
        raise SignedLabLaunchError("installed console-script ownership mismatch")
    _ordinary(scripts / "quillan.exe", directory=False)
    try:
        count = _verify_installed_bytes(wheel, quillan, root)
        wrapper_sha = _wrapper(
            scripts / "quillan.exe", signed.console_target, windows=True
        )
    except (InstalledLaunchEvidenceError, StagedRuntimeError, OSError) as exc:
        raise SignedLabLaunchError("installed wheel or wrapper bytes refused") from exc
    dependency_count = _dependency_closure(packages, root="quillan", python_minor=minor)
    return SignedLabObservation(
        distribution="quillan",
        version="0.10.6",
        wheel_sha256=signed.sha256,
        policy_sha256=pinned.sha256,
        files_checked=count,
        dependency_distributions_checked=dependency_count,
        console_script="quillan",
        wrapper_sha256=wrapper_sha,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-venv", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--trust-policy", type=Path, required=True)
    parser.add_argument("--trust-sha256", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument(
        "--execute-help", action="store_true", help="opt in to quillan --help only"
    )
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("this lab acceptance path requires Windows")
    try:
        observation = inspect_signed_quillan_lab(
            args.lab_venv,
            wheel=args.wheel,
            policy=args.trust_policy,
            independent_policy_sha256=args.trust_sha256,
            registry=args.registry,
            module=args.module,
            now=datetime.now(timezone.utc),
        )
        import json
        from dataclasses import asdict

        print(json.dumps(asdict(observation), indent=2, sort_keys=True))
        if not args.execute_help:
            print("SIGNED_LAB_INSPECTED_NO_EXECUTION")
            return 0
        env = os.environ.copy()
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE"):
            env.pop(name, None)
        env["PYTHONNOUSERSITE"] = "1"
        root = args.lab_venv.absolute()
        result = subprocess.run(
            [str(root / "Scripts" / "quillan.exe"), "--help"],
            cwd=root,
            env=env,
            check=False,
            timeout=30,
        )
        if result.returncode:
            raise SignedLabLaunchError("verified lab Quillan help failed")
        print("SIGNED_QUILLAN_0106_HELP_EXECUTED_IN_DISPOSABLE_LAB")
        return 0
    except (SignedLabLaunchError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
