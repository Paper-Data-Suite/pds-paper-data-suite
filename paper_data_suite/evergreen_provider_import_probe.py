"""Issue #49: explicitly requested, publisher-bound Core provider import smoke.

Loading a provider may run arbitrary module initialization. This is NOT an OS
sandbox or Core contract acceptance: the callable is not invoked. Always verify
publisher-approved wheels, installed pip files, and root-signed native bytes
before and after; never run during discovery, doctor, or ordinary launching.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_candidate_acceptance import (
    CandidateAcceptanceError,
    _probe_environment,
    _run_check,
)
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
    verify_registry_document,
)
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    VerifiedNativeEvidence,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_provider_declarations import (
    DeclarationStatus,
    ObservedProviderDeclaration,
    ProviderDeclarationError,
    inspect_authenticated_provider_declaration,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    _relative_child,
    _safe_root,
)

_MAX_SECONDS: Final = 60
_PROBE_SCRIPT: Final = """\
import importlib
import importlib.metadata
import os
import sys

owner, group, name, target = sys.argv[1:5]
expected_root = os.environ['PDS_EXPECTED_VENV_ROOT']
if (os.path.normcase(os.path.abspath(sys.prefix))
        != os.path.normcase(os.path.abspath(expected_root))):
    sys.exit(70)
if (sys.prefix == sys.base_prefix or not sys.flags.isolated
        or not sys.flags.no_user_site):
    sys.exit(71)
try:
    distribution = importlib.metadata.distribution(owner)
    owned = [
        point for point in distribution.entry_points
        if point.group == group and point.name == name
    ]
    if len(owned) != 1 or owned[0].value != target:
        sys.exit(72)
    module, attribute = target.split(':', 1)
    value = importlib.import_module(module)
    for segment in attribute.split('.'):
        value = getattr(value, segment)
    if not callable(value):
        sys.exit(73)
except (ImportError, AttributeError, KeyError, ValueError, TypeError):
    sys.exit(74)
sys.exit(0)
"""


class ProviderImportError(ValueError):
    """The staged provider import could not be safely accepted."""


class ProviderImportStatus(str, Enum):
    """Import evidence, never approval of Core behavior or live launching."""

    IMPORTABLE_NOT_CONTRACT_TESTED = "importable_not_contract_tested"
    NOT_DECLARED = "not_declared"


@dataclass(frozen=True, slots=True)
class ObservedProviderImport:
    """Ephemeral observation tied to signed bytes, no authority to launch."""

    transaction_id: str
    component_id: str
    group: str
    status: ProviderImportStatus
    target: str | None
    pip_inventory_sha256: str
    native_payload_sha256: str
    provider_declaration_sha256: str


def _check_native(
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


def probe_signed_provider_import(
    stage_root: Path,
    wheelhouse: Path,
    *,
    classroom_workspace: Path,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    module_envelopes: dict[str, bytes],
    component_id: str,
    group: str,
    trust: TrustedKeyring,
    now: datetime,
    allow_candidate_execution: bool = False,
    timeout_seconds: int = 20,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> ObservedProviderImport:
    """Explicitly probe a publisher-verified provider's importable callable.

    No provider function is invoked. A module *import* itself can be hostile:
    callers must obtain user approval and use an appropriate OS isolation
    boundary. No journal or active-receipt authority is established here.
    """
    if (
        allow_candidate_execution is not True
        or type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= _MAX_SECONDS
        or layout not in (None, "windows" if os.name == "nt" else "posix")
        or not isinstance(stage_root, Path)
        or not isinstance(wheelhouse, Path)
        or not isinstance(classroom_workspace, Path)
    ):
        raise ProviderImportError(
            "explicit execution approval and host layout required"
        )
    if not all(
        type(value) is bytes
        for value in (
            prepared_record,
            registry_envelope,
            lock_envelope,
            evidence_envelope,
        )
    ):
        raise ProviderImportError("exact signed provider inputs required")
    try:
        software_root = _safe_root(stage_root.parent, classroom_workspace)
        stage_path = software_root / _relative_child(software_root, stage_root)
        wheel_path = software_root / _relative_child(software_root, wheelhouse)
    except UpdateJournalError as error:
        raise ProviderImportError(
            "provider stage and classroom boundary unsafe"
        ) from error
    if stage_path == wheel_path:
        raise ProviderImportError("wheelhouse and executable stage cannot overlap")

    def observe() -> tuple[ObservedProviderDeclaration, VerifiedNativeEvidence]:
        declaration = inspect_authenticated_provider_declaration(
            stage_path,
            wheel_path,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            module_envelopes=module_envelopes,
            component_id=component_id,
            group=group,
            trust=trust,
            now=now,
            registry_checkpoint=registry_checkpoint,
            lock_checkpoint=lock_checkpoint,
            layout=layout,
        )
        native = _check_native(
            stage_path,
            wheel_path,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            evidence_envelope=evidence_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
        if (
            native.transaction_id != declaration.transaction_id
            or native.stage_root != stage_path
        ):
            raise ProviderImportError("signed provider/native transaction differs")
        return declaration, native

    try:
        before = observe()
        first, native = before
        if first.status is DeclarationStatus.DECLARED_NOT_TESTED:
            if first.target is None:
                raise ProviderImportError("provider target missing despite declaration")
            registry = verify_registry_document(
                registry_envelope,
                trust=trust,
                now=now,
                checkpoint=registry_checkpoint,
            )
            component = next(
                (
                    item
                    for item in registry.claims.modules
                    if item.component_id == component_id
                ),
                None,
            )
            if component is None:
                raise ProviderImportError("provider has no registered distribution")
            executable = stage_path / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            failure: CandidateAcceptanceError | None = None
            with tempfile.TemporaryDirectory(
                prefix=".pds-provider-import-", dir=software_root
            ) as directory:
                temp = Path(directory)
                (temp / "config").mkdir()
                (temp / "cache").mkdir()
                try:
                    _run_check(
                        executable,
                        (
                            "-I",
                            "-B",
                            "-c",
                            _PROBE_SCRIPT,
                            component.distribution,
                            group,
                            component_id,
                            first.target,
                        ),
                        working=temp,
                        environment=_probe_environment(stage_path, temp),
                        timeout_seconds=timeout_seconds,
                    )
                except CandidateAcceptanceError as error:
                    failure = error
            after = observe()
            if before != after:
                raise ProviderImportError(
                    "provider or native bytes changed during import"
                )
            if failure is not None:
                raise ProviderImportError(
                    "isolated provider import failed"
                ) from failure
            status = ProviderImportStatus.IMPORTABLE_NOT_CONTRACT_TESTED
        else:
            after = observe()
            if before != after:
                raise ProviderImportError(
                    "provider or native bytes changed during audit"
                )
            status = ProviderImportStatus.NOT_DECLARED
        return ObservedProviderImport(
            first.transaction_id,
            component_id,
            group,
            status,
            first.target,
            first.pip_inventory_sha256,
            native.payload_sha256,
            hashlib.sha256(
                (first.entry_points_sha256 + first.wheel_sha256).encode("ascii")
            ).hexdigest(),
        )
    except (
        ProviderDeclarationError,
        NativeEvidenceError,
        ValueError,
        OSError,
    ) as error:
        if isinstance(error, ProviderImportError):
            raise
        raise ProviderImportError("signed provider import preflight failed") from error


__all__ = (
    "ObservedProviderImport",
    "ProviderImportError",
    "ProviderImportStatus",
    "probe_signed_provider_import",
)
