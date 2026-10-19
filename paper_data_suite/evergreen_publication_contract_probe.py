"""Issue #49: opt-in staged Core publication-producer profile validation.

A factory call executes candidate code and is not sandboxed merely by Python
-I. No records are published, readers or routing callbacks invoked, or classroom
workspace data accessed. This probe grants no launch or activation rights.
"""

from __future__ import annotations

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
    CatalogVerificationError,
    RevisionCheckpoint,
    TrustedKeyring,
    verify_registry_document,
)
from paper_data_suite.evergreen_provider_import_probe import (
    ObservedProviderImport,
    ProviderImportError,
    ProviderImportStatus,
    probe_signed_provider_import,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    _relative_child,
    _safe_root,
)

_GROUP: Final = "paper_data_suite.publication_producers"
_MAX_SECONDS: Final = 60
_CONTRACT_SCRIPT: Final = """\
import importlib.metadata as metadata
import os
import sys

owner, name, target = sys.argv[1:4]
expected_root = os.environ['PDS_EXPECTED_VENV_ROOT']
if (os.path.normcase(os.path.abspath(sys.prefix))
        != os.path.normcase(os.path.abspath(expected_root))):
    sys.exit(70)
if (sys.prefix == sys.base_prefix or not sys.flags.isolated
        or not sys.flags.no_user_site):
    sys.exit(71)
try:
    core_dist = metadata.distribution('pds-core')
    owned = {str(path).replace('\\\\', '/') for path in (core_dist.files or ())}
    if not {'pds_core/publication_compatibility.py',
            'pds_core/publication_records.py'} <= owned:
        sys.exit(77)
    distribution = metadata.distribution(owner)
    points = [p for p in distribution.entry_points
              if p.group == 'paper_data_suite.publication_producers'
              and p.name == name]
    if len(points) != 1 or points[0].value != target:
        sys.exit(72)
    import pds_core.publication_compatibility as core_contract
    if (os.path.normcase(os.path.abspath(core_contract.__file__))
            != os.path.normcase(os.path.abspath(core_dist.locate_file(
                'pds_core/publication_compatibility.py')))):
        sys.exit(78)
    from pds_core.publication_compatibility import (
        validate_publication_producer_profile,
    )
    import pds_core.publication_records as record_contract
    if (os.path.normcase(os.path.abspath(record_contract.__file__))
            != os.path.normcase(os.path.abspath(core_dist.locate_file(
                'pds_core/publication_records.py')))):
        sys.exit(80)
    from pds_core.publication_records import (
        PUBLICATION_RECORD_SCHEMA_VERSION,
    )
    factory = points[0].load()
    if not callable(factory):
        sys.exit(73)
    profile = validate_publication_producer_profile(factory())
    if profile.module_id != name:
        sys.exit(74)
    if (PUBLICATION_RECORD_SCHEMA_VERSION
            not in profile.supported_core_publication_schema_versions):
        sys.exit(75)
    if not profile.publication_contracts:
        sys.exit(79)
except Exception:
    # Never expose module exception details or student data.
    sys.exit(76)
sys.exit(0)
"""


class PublicationContractError(ValueError):
    """Staged publication-producer profile could not be qualified for installed Core."""


class PublicationContractStatus(str, Enum):
    """Qualified profile metadata only; not publishing or launch authority."""

    PROFILE_VALID_NOT_PUBLISHED = "profile_valid_not_published"
    NOT_DECLARED = "not_declared"


@dataclass(frozen=True, slots=True)
class ObservedPublicationContract:
    """Ephemeral exact installed-profile evidence, never an active receipt."""

    transaction_id: str
    component_id: str
    status: PublicationContractStatus
    provider_target: str | None
    pip_inventory_sha256: str
    native_payload_sha256: str
    provider_declaration_sha256: str


def probe_signed_publication_contract(
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
    trust: TrustedKeyring,
    now: datetime,
    allow_candidate_execution: bool = False,
    timeout_seconds: int = 20,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> ObservedPublicationContract:
    """Validate a publisher-authenticated PublicationProducerProfile with Core.

    The factory runs only with explicit opt-in. The Core structural validator
    checks compatibility metadata but creates no publication and invokes no
    reader. All signed stage evidence is checked before and after execution.
    A valid profile is not proof that a publication exists or is readable.
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
        raise PublicationContractError(
            "explicit bounded publication contract execution required"
        )
    try:
        root = _safe_root(stage_root.parent, classroom_workspace)
        if _relative_child(root, stage_root) == _relative_child(root, wheelhouse):
            raise PublicationContractError("stage and wheelhouse overlap")
    except UpdateJournalError as error:
        raise PublicationContractError("unsafe software/classroom boundary") from error

    def observe() -> ObservedProviderImport:
        return probe_signed_provider_import(
            stage_root,
            wheelhouse,
            classroom_workspace=classroom_workspace,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            evidence_envelope=evidence_envelope,
            module_envelopes=module_envelopes,
            component_id=component_id,
            group=_GROUP,
            trust=trust,
            now=now,
            allow_candidate_execution=True,
            timeout_seconds=timeout_seconds,
            registry_checkpoint=registry_checkpoint,
            lock_checkpoint=lock_checkpoint,
            layout=layout,
        )

    try:
        first = observe()
        if first.component_id != component_id or first.group != _GROUP:
            raise PublicationContractError("signed publication provider scope mismatch")
        if first.status is ProviderImportStatus.NOT_DECLARED:
            return ObservedPublicationContract(
                first.transaction_id,
                component_id,
                PublicationContractStatus.NOT_DECLARED,
                None,
                first.pip_inventory_sha256,
                first.native_payload_sha256,
                first.provider_declaration_sha256,
            )
        if (
            first.status is not ProviderImportStatus.IMPORTABLE_NOT_CONTRACT_TESTED
            or first.target is None
        ):
            raise PublicationContractError(
                "publication provider import evidence incomplete"
            )
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
            raise PublicationContractError(
                "publication provider has no trusted distribution"
            )
        executable = stage_root / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        failure: CandidateAcceptanceError | None = None
        with tempfile.TemporaryDirectory(
            prefix=".pds-publication-contract-", dir=root
        ) as temporary:
            work = Path(temporary)
            (work / "config").mkdir()
            (work / "cache").mkdir()
            try:
                _run_check(
                    executable,
                    (
                        "-I",
                        "-B",
                        "-c",
                        _CONTRACT_SCRIPT,
                        component.distribution,
                        component_id,
                        first.target,
                    ),
                    working=work,
                    environment=_probe_environment(stage_root, work),
                    timeout_seconds=timeout_seconds,
                )
            except CandidateAcceptanceError as error:
                failure = error
        second = observe()
        if first != second:
            raise PublicationContractError(
                "signed publication stage drifted during probe"
            )
        if failure is not None:
            raise PublicationContractError(
                "staged Core publication contract validation failed"
            ) from failure
        return ObservedPublicationContract(
            first.transaction_id,
            component_id,
            PublicationContractStatus.PROFILE_VALID_NOT_PUBLISHED,
            first.target,
            first.pip_inventory_sha256,
            first.native_payload_sha256,
            first.provider_declaration_sha256,
        )
    except (ProviderImportError, CatalogVerificationError) as error:
        raise PublicationContractError(
            "signed publication provider or installed Core preflight failed"
        ) from error


__all__ = (
    "ObservedPublicationContract",
    "PublicationContractError",
    "PublicationContractStatus",
    "probe_signed_publication_contract",
)
