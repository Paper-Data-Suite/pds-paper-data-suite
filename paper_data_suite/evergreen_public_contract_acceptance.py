"""Issue #49: opt-in, byte-checked staged public console target smoke.

This deliberately IMPORTS candidate code and is not an OS sandbox. An exact
signed *dependency* lock is not a delegated PDS publisher authorization, and a
successful import does not establish live-launch rights or API compatibility.
No normal `pds launch`, update discovery, doctor or installation path calls it.
"""

from __future__ import annotations

import hashlib
import os
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
from paper_data_suite.evergreen_candidate_acceptance import (
    CandidateAcceptanceError,
    _probe_environment,
    _run_check,
)
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    parse_unverified_prepared_record,
)
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_staged_install import (
    StageAuditError,
    _record_entries,
    _sha_file,
    _walk_stage,
    _wheel_expectations,
)
from paper_data_suite.evergreen_staged_runtime import (
    StagedRuntimeError,
    StagedRuntimeInspection,
    inspect_staged_virtualenv,
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

_MAX_LAUNCHERS: Final = 24
_MAX_TIMEOUT: Final = 60
# Fixed, non-user-supplied probe: never invokes CLI entry-point functions.
# -I ignores external Python startup customization; -B prevents bytecode files.
# We require the actual callable to be importable from this VENV's site-packages.
_CONTRACT_PROBE: Final = """\
import importlib, importlib.metadata, os, pathlib, sys
root = pathlib.Path(os.environ['PDS_EXPECTED_VENV_ROOT']).resolve()
site = pathlib.Path(os.environ['PDS_EXPECTED_SITE_PACKAGES']).resolve()
owner = os.environ['PDS_EXPECTED_OWNER']
name = os.environ['PDS_EXPECTED_CONSOLE']
target = os.environ['PDS_EXPECTED_TARGET']
if (pathlib.Path(sys.prefix).resolve() != root or sys.prefix == sys.base_prefix
        or not sys.flags.isolated or not sys.flags.no_user_site
        or not sys.flags.dont_write_bytecode):
    sys.exit(71)
try:
    dist = importlib.metadata.distribution(owner)
    if not pathlib.Path(dist.locate_file('')).resolve().is_relative_to(site):
        sys.exit(76)
    ep = [e for e in dist.entry_points if e.group == 'console_scripts'
          and e.name == name]
    if len(ep) != 1 or ep[0].value != target:
        sys.exit(72)
    module_name, qualified = target.split(':', 1)
    module = importlib.import_module(module_name)
    location = pathlib.Path(module.__file__).resolve(strict=True)
    if not location.is_relative_to(site):
        sys.exit(73)
    obj = module
    for attribute in qualified.split('.'):
        obj = getattr(obj, attribute)
    if not callable(obj):
        sys.exit(74)
except (ImportError, AttributeError, KeyError, OSError, ValueError, TypeError):
    sys.exit(75)
"""


class PublicContractAcceptanceError(ValueError):
    """Exact staged source bytes or opt-in public console target smoke failed."""


@dataclass(frozen=True, slots=True)
class ObservedPublicContractAcceptance:
    """Ephemeral import observation; no publisher or active-state authorization."""

    transaction_id: str
    journal_revision: int
    stage_relative_path: str
    native_payload_sha256: str
    site_inventory_sha256: str
    console_targets: tuple[tuple[str, str, str], ...]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _site_inventory(
    inspected: StagedRuntimeInspection, wheelhouse: Path, prepared_record: bytes
) -> str:
    """Match every restricted purelib staged code file to source wheel bytes.

    This layout intentionally refuses .data wheels and unrelated pip-produced
    files until those layouts have a separate reviewed, explicit acceptance.
    """
    prepared = parse_unverified_prepared_record(prepared_record)
    expected, records = _wheel_expectations(
        wheelhouse, tuple((w.filename, w.sha256) for w in prepared.wheels)
    )
    installed = _walk_stage(inspected.site_packages)
    if set(installed) != set(expected):
        raise PublicContractAcceptanceError("staged Python source inventory differs")
    observed: dict[str, tuple[str, int]] = {}
    inventory = hashlib.sha256()
    for relative, path in sorted(installed.items()):
        digest, size = _sha_file(path)
        expected_hash, expected_size = expected[relative]
        if expected_size >= 0 and (digest, size) != (expected_hash, expected_size):
            raise PublicContractAcceptanceError("staged Python source bytes changed")
        observed[relative] = digest, size
        inventory.update(relative.encode("utf-8") + b"\x00")
        inventory.update(digest.encode("ascii") + b"\x00")
        inventory.update(str(size).encode("ascii") + b"\x00")
    for name, owned in records.items():
        with installed[name].open("rb") as stream:
            entries = _record_entries(stream.read(2 * 1024 * 1024 + 1))
        if set(entries) != owned:
            raise PublicContractAcceptanceError("installed RECORD ownership mismatch")
        for relative, values in entries.items():
            correct = ("", -1) if relative == name else observed[relative]
            if values != correct:
                raise PublicContractAcceptanceError(
                    "installed RECORD integrity mismatch"
                )
    return inventory.hexdigest()


def _observe(
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
) -> tuple[str, str, tuple[tuple[str, str, str], ...], Path]:
    native = verify_signed_staged_native_evidence(
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
    observed = inspect_staged_virtualenv(
        stage,
        wheels,
        prepared_record=prepared_record,
        registry_envelope=registry_envelope,
        lock_envelope=lock_envelope,
        trust=trust,
        now=now,
        layout=layout,
    )
    if native.transaction_id != observed.transaction_id:
        raise PublicContractAcceptanceError("inconsistent staged transaction")
    roots = set(parse_unverified_prepared_record(prepared_record).roots)
    launchers = tuple(
        sorted(
            (entry.owner, entry.name, entry.target)
            for entry in observed.console_launchers
            if entry.owner in roots
        )
    )
    if not 1 <= len(launchers) <= _MAX_LAUNCHERS:
        raise PublicContractAcceptanceError("no bounded public root launchers")
    site_digest = _site_inventory(observed, wheels, prepared_record)
    return native.payload_sha256, site_digest, launchers, observed.site_packages


def accept_verified_candidate_public_contracts(
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
) -> ObservedPublicContractAcceptance:
    """Explicitly import authenticated-wheel public console targets (never call).

    Candidate code executes with the teacher's OS privileges, so approval and
    trustworthy provenance are external prerequisites. Only root-declared
    console targets from verified wheel metadata are probed. An observation
    is NOT a software receipt, integrated capability claim or launch authority.
    """
    host_layout = "windows" if os.name == "nt" else "posix"
    if (
        type(expected_revision) is not int
        or expected_revision != 1
        or type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= _MAX_TIMEOUT
        or layout not in (None, host_layout)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or any(
            type(item) is not bytes
            for item in (
                prepared_record,
                registry_envelope,
                lock_envelope,
                evidence_envelope,
            )
        )
    ):
        raise PublicContractAcceptanceError("invalid public acceptance parameters")
    try:
        root = _safe_root(software_root, classroom_workspace)
        _, _, recovery = _selection_paths(root, classroom_workspace)
        selection_lock, selection_fd = _selection_lock(root)
    except (UpdateJournalError, ActivationSlotError) as error:
        raise PublicContractAcceptanceError(
            "unsafe root or selection locked"
        ) from error
    try:
        try:
            journal_path, journal_lock = _journal_paths(root, transaction_id)
            journal_fd = _journal_lock(journal_lock)
        except UpdateJournalError as error:
            raise PublicContractAcceptanceError(
                "candidate journal unavailable"
            ) from error
        try:
            if _read_selection(recovery) is not None:
                raise PublicContractAcceptanceError("pending recovery prohibits import")
            journal = _read_journal(journal_path)
            if (
                journal is None
                or journal.transaction_id != transaction_id
                or journal.revision != expected_revision
                or journal.phase is not UpdatePhase.CANDIDATE_VERIFIED
                or journal.recorded_at > now.astimezone(timezone.utc)
            ):
                raise PublicContractAcceptanceError("exact unarmed journal required")
            for data, digest in (
                (prepared_record, journal.prepared_sha256),
                (registry_envelope, journal.registry_envelope_sha256),
                (lock_envelope, journal.lock_envelope_sha256),
                (evidence_envelope, journal.native_envelope_sha256),
            ):
                if _digest(data) != digest:
                    raise PublicContractAcceptanceError(
                        "candidate journal bytes differ"
                    )
            stage = root / journal.stage_relative_path
            wheels = root / journal.wheelhouse_relative_path
            _relative_child(root, stage)
            _relative_child(root, wheels)
            before = _observe(
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
            if (
                parse_unverified_prepared_record(prepared_record).transaction_id
                != transaction_id
            ):
                raise PublicContractAcceptanceError("candidate transaction mismatch")
            interpreter = stage / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            failure: CandidateAcceptanceError | None = None
            with tempfile.TemporaryDirectory(
                prefix=".pds-public-contract-", dir=root
            ) as temporary:
                working = Path(temporary)
                (working / "config").mkdir()
                (working / "cache").mkdir()
                environment = _probe_environment(stage, working)
                environment["PDS_EXPECTED_SITE_PACKAGES"] = str(before[3])
                for owner, console, target in before[2]:
                    environment["PDS_EXPECTED_OWNER"] = owner
                    environment["PDS_EXPECTED_CONSOLE"] = console
                    environment["PDS_EXPECTED_TARGET"] = target
                    try:
                        _run_check(
                            interpreter,
                            ("-I", "-B", "-c", _CONTRACT_PROBE),
                            working=working,
                            environment=environment,
                            timeout_seconds=timeout_seconds,
                        )
                    except CandidateAcceptanceError as error:
                        failure = error
                        break
            after = _observe(
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
                raise PublicContractAcceptanceError("candidate changed during import")
            if (
                _read_journal(journal_path) != journal
                or _read_selection(recovery) is not None
            ):
                raise PublicContractAcceptanceError(
                    "candidate journal changed during import"
                )
            if failure is not None:
                raise PublicContractAcceptanceError(
                    "public console import failed"
                ) from failure
            return ObservedPublicContractAcceptance(
                transaction_id,
                journal.revision,
                journal.stage_relative_path,
                after[0],
                after[1],
                after[2],
            )
        finally:
            _journal_unlock(journal_lock, journal_fd)
    except (
        UpdateJournalError,
        ActivationSlotError,
        NativeEvidenceError,
        StagedRuntimeError,
        StageAuditError,
        PreparedRecordError,
        OSError,
    ) as error:
        raise PublicContractAcceptanceError(
            "candidate public acceptance preflight failed"
        ) from error
    finally:
        os.close(selection_fd)
        selection_lock.unlink(missing_ok=True)


__all__ = (
    "ObservedPublicContractAcceptance",
    "PublicContractAcceptanceError",
    "accept_verified_candidate_public_contracts",
)
