"""Issue #49: explicitly invoked, bounded candidate runtime smoke acceptance.

This opt-in probe EXECUTES authenticated candidate interpreter bytes; unlike
metadata inspections it is not purely read-only. It never runs during normal
launch, update discovery or doctor, never activates a selected installation,
and is not a sandbox against malicious same-user code. The signed stage is
reverified before and after execution, with cooperating update locks held.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
)
from paper_data_suite.evergreen_activation_slots import (
    _lock as _selection_lock,
)
from paper_data_suite.evergreen_activation_slots import (
    _paths as _selection_paths,
)
from paper_data_suite.evergreen_activation_slots import (
    _read as _read_selection,
)
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    VerifiedNativeEvidence,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
)
from paper_data_suite.evergreen_update_journal import (
    _lock as _journal_lock,
)
from paper_data_suite.evergreen_update_journal import (
    _paths as _journal_paths,
)
from paper_data_suite.evergreen_update_journal import (
    _read as _read_journal,
)
from paper_data_suite.evergreen_update_journal import (
    _unlock as _journal_unlock,
)

_MAX_PROBE_SECONDS: Final = 60
_IDENTITY_SCRIPT: Final = (
    "import os,sys;"
    "norm=lambda p: os.path.normcase(os.path.abspath(p));"
    "root=norm(os.environ['PDS_EXPECTED_VENV_ROOT']);"
    "folder='Scripts' if os.name=='nt' else 'bin';"
    "okay=(norm(sys.prefix)==root and norm(sys.base_prefix)!=root "
    "and norm(os.path.dirname(sys.executable))==norm(os.path.join(root,folder)) "
    "and sys.flags.isolated==1 and sys.flags.no_user_site==1);"
    "sys.exit(0 if okay else 72)"
)


class CandidateAcceptanceError(ValueError):
    """The explicit candidate interpreter acceptance probe cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ObservedCandidateAcceptance:
    """One ephemeral smoke observation; no durable receipt or launch right."""

    transaction_id: str
    stage_relative_path: str
    journal_revision: int
    native_payload_sha256: str
    checks: tuple[str, ...] = ("isolated_python_identity", "offline_pip_check")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify(
    stage: Path,
    wheels: Path,
    *,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None,
) -> VerifiedNativeEvidence:
    try:
        return verify_signed_staged_native_evidence(
            stage,
            wheels,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            evidence_envelope=evidence_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
    except NativeEvidenceError as error:
        raise CandidateAcceptanceError(
            "signed candidate failed byte verification"
        ) from error


def _probe_environment(stage: Path, temp: Path) -> dict[str, str]:
    """Construct a minimal subprocess environment, not an OS security sandbox."""
    inherited = (
        "SystemRoot",
        "WINDIR",
        "SYSTEMDRIVE",
        "COMSPEC",
        "PATHEXT",
        "LANG",
        "LC_ALL",
    )
    values = {name: os.environ[name] for name in inherited if name in os.environ}
    scripts = stage / ("Scripts" if os.name == "nt" else "bin")
    values["PATH"] = str(scripts) + os.pathsep + os.defpath
    values.update(
        {
            "HOME": str(temp),
            "USERPROFILE": str(temp),
            "APPDATA": str(temp / "config"),
            "LOCALAPPDATA": str(temp / "cache"),
            "TEMP": str(temp),
            "TMP": str(temp),
            "TMPDIR": str(temp),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_NO_INDEX": "1",
            "PIP_NO_CACHE_DIR": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PDS_EXPECTED_VENV_ROOT": str(stage),
        }
    )
    return values


def _run_check(
    python: Path,
    args: tuple[str, ...],
    *,
    working: Path,
    environment: dict[str, str],
    timeout_seconds: int,
) -> None:
    try:
        result = subprocess.run(
            [str(python), *args],
            cwd=working,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise CandidateAcceptanceError("candidate runtime probe timed out") from error
    except (OSError, ValueError) as error:
        raise CandidateAcceptanceError("candidate interpreter could not run") from error
    if result.returncode != 0:
        raise CandidateAcceptanceError("candidate runtime smoke check failed")


def accept_verified_candidate_runtime(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    expected_revision: int,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    timeout_seconds: int = 30,
    layout: str | None = None,
) -> ObservedCandidateAcceptance:
    """Run explicit, bounded interpreter identity and offline pip-check probes.

    The journal must be at candidate_verified before arming any update. All
    signed evidence is checked before AND after candidate process execution.
    This returns no install receipt, activation or launch authorization. A
    compromised candidate may access same-user files: callers must obtain
    informed user approval for code execution and use a trusted OS boundary.
    """
    host_layout = "windows" if os.name == "nt" else "posix"
    if (
        type(expected_revision) is not int
        or expected_revision != 1
        or type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= _MAX_PROBE_SECONDS
        or layout not in (None, host_layout)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
    ):
        raise CandidateAcceptanceError("invalid acceptance parameters or host layout")
    if not all(
        type(item) is bytes
        for item in (
            prepared_record,
            registry_envelope,
            lock_envelope,
            evidence_envelope,
        )
    ):
        raise CandidateAcceptanceError("exact candidate evidence bytes required")
    try:
        root = _safe_root(software_root, classroom_workspace)
        _, _, recovery_path = _selection_paths(root, classroom_workspace)
        selection_lock, selection_fd = _selection_lock(root)
    except (UpdateJournalError, ActivationSlotError) as error:
        raise CandidateAcceptanceError(
            "software root unsafe or selection locked"
        ) from error
    try:
        try:
            journal_path, journal_lock = _journal_paths(root, transaction_id)
            journal_fd = _journal_lock(journal_lock)
        except UpdateJournalError as error:
            raise CandidateAcceptanceError(
                "candidate journal locked or missing"
            ) from error
        try:
            if _read_selection(recovery_path) is not None:
                raise CandidateAcceptanceError("pending recovery forbids runtime probe")
            journal = _read_journal(journal_path)
            if (
                journal is None
                or journal.transaction_id != transaction_id
                or journal.revision != expected_revision
                or journal.phase is not UpdatePhase.CANDIDATE_VERIFIED
                or journal.recorded_at > now.astimezone(timezone.utc)
            ):
                raise CandidateAcceptanceError(
                    "exact unarmed candidate journal required"
                )
            for raw, digest in (
                (prepared_record, journal.prepared_sha256),
                (registry_envelope, journal.registry_envelope_sha256),
                (lock_envelope, journal.lock_envelope_sha256),
                (evidence_envelope, journal.native_envelope_sha256),
            ):
                if _digest(raw) != digest:
                    raise CandidateAcceptanceError("journal evidence mismatch")
            stage = root / journal.stage_relative_path
            wheels = root / journal.wheelhouse_relative_path
            _relative_child(root, stage)
            _relative_child(root, wheels)
            before = _verify(
                stage,
                wheels,
                prepared_record=prepared_record,
                registry_envelope=registry_envelope,
                lock_envelope=lock_envelope,
                evidence_envelope=evidence_envelope,
                trust=trust,
                now=now,
                layout=layout,
            )
            if before.transaction_id != transaction_id or before.stage_root != stage:
                raise CandidateAcceptanceError("signed candidate transaction mismatch")
            interpreter_name = "Scripts/python.exe" if os.name == "nt" else "bin/python"
            interpreter = stage / interpreter_name
            failure: CandidateAcceptanceError | None = None
            with tempfile.TemporaryDirectory(
                prefix=".pds-candidate-acceptance-", dir=root
            ) as temporary:
                temp = Path(temporary)
                (temp / "config").mkdir()
                (temp / "cache").mkdir()
                environment = _probe_environment(stage, temp)
                try:
                    _run_check(
                        interpreter,
                        ("-I", "-c", _IDENTITY_SCRIPT),
                        working=temp,
                        environment=environment,
                        timeout_seconds=timeout_seconds,
                    )
                    _run_check(
                        interpreter,
                        ("-I", "-m", "pip", "check"),
                        working=temp,
                        environment=environment,
                        timeout_seconds=timeout_seconds,
                    )
                except CandidateAcceptanceError as error:
                    failure = error
            after = _verify(
                stage,
                wheels,
                prepared_record=prepared_record,
                registry_envelope=registry_envelope,
                lock_envelope=lock_envelope,
                evidence_envelope=evidence_envelope,
                trust=trust,
                now=now,
                layout=layout,
            )
            if before != after:
                raise CandidateAcceptanceError(
                    "candidate evidence changed during probe"
                )
            if failure is not None:
                raise failure
            return ObservedCandidateAcceptance(
                transaction_id,
                journal.stage_relative_path,
                journal.revision,
                after.payload_sha256,
            )
        finally:
            _journal_unlock(journal_lock, journal_fd)
    except (UpdateJournalError, ActivationSlotError) as error:
        raise CandidateAcceptanceError(
            "candidate acceptance root became unsafe"
        ) from error
    finally:
        os.close(selection_fd)
        selection_lock.unlink(missing_ok=True)


__all__ = (
    "CandidateAcceptanceError",
    "ObservedCandidateAcceptance",
    "accept_verified_candidate_runtime",
)
