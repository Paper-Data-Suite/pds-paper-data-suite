"""Issue #49 Slice 68: explicitly consented, isolated, offline pip wheel stage.

This mutates ONLY a new transaction-specific, unselected candidate directory.
Publisher/root-signed wheels are reverified before invoking pip and afterwards.
The resulting Python executable is not root-signed, protected or authorized to
launch. An independent native inventory, Slice-67 installed-stage audit,
recovery journal and activation authority are REQUIRED in later stages.

Caller MUST independently provision publisher trust and a fresh baseline witness;
these Python observation objects are NOT themselves authorization credentials.
No scheduled, startup, normal modules/doctor/launch or implicit execution path.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
)
from paper_data_suite.evergreen_activation_slots import (
    _lock as _selection_lock,
)
from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    prepare_composition_record,
    serialize_prepared_record,
)
from paper_data_suite.evergreen_plan_staged_candidate import (
    PlanStagedCandidateError,
    _match_prepared,
)
from paper_data_suite.evergreen_plan_wheelhouse_preflight import (
    PlanWheelhousePreflight,
    PlanWheelhousePreflightError,
    inspect_plan_bound_wheelhouse,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    PublisherPipPreflightError,
    audit_publisher_bound_pip_candidate,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    _relative_child,
    _safe_root,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_CONSENT: Final = "INSTALL_AUTHENTICATED_WHEELS_IN_NEW_ISOLATED_STAGE"
_MAX_WHEELS: Final = 128


class PlanStageInstallError(ValueError):
    """No complete, safely isolated candidate installation could be established."""


@dataclass(frozen=True, slots=True)
class IsolatedPlanStageResult:
    """Unselected staged bytes only; native/signing/activation remain pending."""

    transaction_id: str
    stage_root: Path
    prepared_record: bytes
    pip_inventory_sha256: str
    baseline_transaction_id: str
    baseline_witness_revision: int
    signed_lock_payload_sha256: str
    status: str = "PIP_CANDIDATE_INSTALLED_NATIVE_EVIDENCE_STILL_REQUIRED"
    authority: str = "NO_ACTIVE_RECEIPT_SWITCH_OR_LAUNCH_AUTHORITY"


def _host_python() -> Path:
    """Use the running Suite interpreter only, never a caller-selected executable."""
    executable = Path(sys.executable).resolve(strict=True)
    if not executable.is_file():
        raise PlanStageInstallError("running Suite interpreter is unsafe")
    return executable


def _environment(root: Path) -> dict[str, str]:
    """Disable ambient Python/pip configuration, proxies, indexes and caches."""
    inherited = (
        "SystemRoot",
        "WINDIR",
        "SYSTEMDRIVE",
        "COMSPEC",
        "PATHEXT",
        "LANG",
        "LC_ALL",
    )
    env = {name: os.environ[name] for name in inherited if name in os.environ}
    env.update(
        {
            "PATH": os.defpath,
            "HOME": str(root),
            "USERPROFILE": str(root),
            "APPDATA": str(root),
            "LOCALAPPDATA": str(root),
            "TEMP": str(root),
            "TMP": str(root),
            "TMPDIR": str(root),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_NO_INDEX": "1",
            "PIP_NO_CACHE_DIR": "1",
            "PIP_NO_INPUT": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CONFIG_FILE": os.devnull,
        }
    )
    return env


def _execute(
    arguments: tuple[str, ...], *, cwd: Path, env: dict[str, str], timeout: int
) -> None:
    try:
        result = subprocess.run(
            list(arguments),
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise PlanStageInstallError(
            "isolated offline stage subprocess refused"
        ) from error
    if result.returncode != 0:
        raise PlanStageInstallError("isolated offline stage subprocess failed")


def install_authenticated_plan_to_isolated_stage(
    snapshot: CatalogSnapshot,
    witnessed: WitnessSelectedStageObservation,
    software_root: Path,
    *,
    classroom_workspace: Path,
    wheelhouse: Path,
    transaction_id: str,
    explicit_consent: str,
    requested_targets: dict[str, str | None],
    python_minor: str,
    platform_tag: str,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    now: datetime,
) -> IsolatedPlanStageResult:
    """Make ONE new isolated venv and install exact previously signed local wheels.

    No third-party package-index access, resolver, direct URL other than the
    signed local wheels, source build, editable install or arbitrary script path.
    No retries, cleanup of ambiguous paths, install into live interpreter,
    active selection, classroom writes, receipt, native signing or module launch.

    A failed install may leave an INCOMPLETE, UNTRUSTED directory for manual
    recovery; it never becomes selected. The caller must authenticate the
    witnessed baseline afresh at the protected activation transaction boundary.
    """
    if (
        type(explicit_consent) is not str
        or explicit_consent != _CONSENT
        or type(transaction_id) is not str
        or _TX.fullmatch(transaction_id) is None
        or not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(witnessed, WitnessSelectedStageObservation)
        or not isinstance(software_root, Path)
        or not isinstance(classroom_workspace, Path)
        or not isinstance(wheelhouse, Path)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or type(requested_targets) is not dict
        or type(registry_envelope) is not bytes
        or type(lock_envelope) is not bytes
        or type(module_envelopes) is not dict
        or any(
            type(k) is not str or type(v) is not bytes
            for k, v in module_envelopes.items()
        )
        or python_minor != f"{sys.version_info.major}.{sys.version_info.minor}"
        or platform_tag != sysconfig.get_platform().lower()
    ):
        raise PlanStageInstallError("explicit consent or signed stage inputs invalid")
    try:
        host = _host_python()
        root = _safe_root(software_root, classroom_workspace)
        wheels = wheelhouse.absolute()
        _relative_child(root, wheels)
        folder = root / "candidate-builds"
        candidate = folder / transaction_id
        if folder == wheels or folder in wheels.parents or wheels in folder.parents:
            raise PlanStageInstallError("wheelhouse and candidate builds overlap")
        if candidate.exists() or candidate.is_symlink():
            raise PlanStageInstallError(
                "transaction candidate directory already exists"
            )
        if folder.exists() or folder.is_symlink():
            _relative_child(root, folder)
        # A new folder is created only after the signed artifact preflight.

        def authenticate() -> PlanWheelhousePreflight:
            check = inspect_plan_bound_wheelhouse(
                snapshot,
                witnessed,
                wheels,
                requested_targets=requested_targets,
                python_minor=python_minor,
                platform_tag=platform_tag,
                registry_envelope=registry_envelope,
                lock_envelope=lock_envelope,
                module_envelopes=module_envelopes,
                trust=trust,
                now=now,
            )
            if (
                check.baseline_transaction_id != witnessed.transaction_id
                or check.baseline_witness_revision != witnessed.witness_revision
                or check.registry_payload_sha256 != snapshot.registry.payload_sha256
                or check.python_minor != python_minor
                or check.platform_tag != platform_tag
            ):
                raise PlanStageInstallError("signed plan baseline changed")
            return check

        locked, descriptor = _selection_lock(root)
        try:
            first = authenticate()
            count = len(first.pds_wheels) + len(first.external_wheels)
            if not 1 <= count <= _MAX_WHEELS:
                raise PlanStageInstallError("signed wheel count outside limits")
            if folder.exists() or folder.is_symlink():
                _relative_child(root, folder)
            else:
                folder.mkdir(mode=0o700)
            if candidate.exists() or candidate.is_symlink():
                raise PlanStageInstallError("candidate appeared before staging")
            record = prepare_composition_record(
                wheels,
                lock_envelope=lock_envelope,
                registry_envelope=registry_envelope,
                trust=trust,
                now=now,
                transaction_id=transaction_id,
            )
            _match_prepared(first, record)
            prepared = serialize_prepared_record(record)
            second = authenticate()
            if first != second:
                raise PlanStageInstallError("signed plan changed before installation")
            candidate.mkdir(mode=0o700)
            _relative_child(root, candidate)
            # Only EXACT files named in the previously authenticated prepared lock.
            sources = tuple(str(wheels / wheel.filename) for wheel in record.wheels)
            if len(sources) != len(set(sources)):
                raise PlanStageInstallError("duplicate signed local wheel path")
            env = _environment(root)
            _execute(
                (str(host), "-m", "venv", "--copies", "--without-pip", str(candidate)),
                cwd=root,
                env=env,
                timeout=120,
            )
            python_name = "Scripts/python.exe" if os.name == "nt" else "bin/python"
            python = candidate / python_name
            if not python.is_file() or python.is_symlink():
                raise PlanStageInstallError("candidate Python missing or unsafe")
            # pip --python supports fresh --without-pip virtualenvs; it does not
            # leave its own dist-info package in the staged site-packages.
            _execute(
                (
                    str(host),
                    "-m",
                    "pip",
                    "--python",
                    str(python),
                    "install",
                    "--no-index",
                    "--no-deps",
                    "--no-cache-dir",
                    "--no-compile",
                    "--disable-pip-version-check",
                    "--no-input",
                    *sources,
                ),
                cwd=root,
                env=env,
                timeout=300,
            )
            inspected = audit_publisher_bound_pip_candidate(
                candidate,
                wheels,
                prepared_record=prepared,
                registry_envelope=registry_envelope,
                lock_envelope=lock_envelope,
                module_envelopes=module_envelopes,
                trust=trust,
                now=now,
            )
            expected_console_owners = {
                str(canonicalize_name(item.distribution))
                for item in first.pds_wheels
                if item.console_script
            }
            actual_console_owners = {
                str(canonicalize_name(distribution))
                for distribution, _, _ in inspected.root_console_targets
            }
            if (
                inspected.transaction_id != transaction_id
                or inspected.stage_root != candidate
                or inspected.wheelhouse != wheels
                or inspected.registry_payload_sha256 != first.registry_payload_sha256
                or inspected.lock_payload_sha256 != first.signed_lock_payload_sha256
                or actual_console_owners != expected_console_owners
            ):
                raise PlanStageInstallError(
                    "installed candidate differs from signed plan"
                )
            third = authenticate()
            if first != third:
                raise PlanStageInstallError("signed wheelhouse changed during install")
            return IsolatedPlanStageResult(
                transaction_id,
                candidate,
                prepared,
                inspected.pip_inventory_sha256,
                witnessed.transaction_id,
                witnessed.witness_revision,
                first.signed_lock_payload_sha256,
            )
        finally:
            os.close(descriptor)
            locked.unlink(missing_ok=True)
    except (
        ActivationSlotError,
        UpdateJournalError,
        PlanWheelhousePreflightError,
        PreparedRecordError,
        PlanStagedCandidateError,
        PublisherPipPreflightError,
        OSError,
    ) as error:
        raise PlanStageInstallError("authenticated isolated stage refused") from error


__all__ = (
    "IsolatedPlanStageResult",
    "PlanStageInstallError",
    "install_authenticated_plan_to_isolated_stage",
)
