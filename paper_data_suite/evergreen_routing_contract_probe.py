"""Issue #49: explicitly authorized staged Core PDS2 routing profile validation.

A factory call executes candidate code and is not sandboxed merely by Python
-I. No registration validators, scan handlers, routes, workspace data, launch
or activation rights are exercised or granted.
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

_GROUP: Final = "paper_data_suite.modules"
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
    if 'pds_core/module_profiles.py' not in owned:
        sys.exit(77)
    distribution = metadata.distribution(owner)
    points = [p for p in distribution.entry_points
              if p.group == 'paper_data_suite.modules' and p.name == name]
    if len(points) != 1 or points[0].value != target:
        sys.exit(72)
    import pds_core.module_profiles as core_contract
    if (os.path.normcase(os.path.abspath(core_contract.__file__))
            != os.path.normcase(os.path.abspath(core_dist.locate_file(
                'pds_core/module_profiles.py')))):
        sys.exit(78)
    from pds_core.module_profiles import (
        CORE_ROUTING_CONTRACT_VERSION,
        validate_module_profile,
    )
    factory = points[0].load()
    if not callable(factory):
        sys.exit(73)
    profile = validate_module_profile(factory())
    if profile.module_id != name:
        sys.exit(74)
    if (CORE_ROUTING_CONTRACT_VERSION
            not in profile.supported_core_routing_contract_versions):
        sys.exit(75)
    if ('PDS2' not in profile.supported_qr_schemas
            or '1' not in profile.supported_route_registration_schema_versions
            or 'active' not in profile.dispatchable_route_statuses):
        sys.exit(79)
except Exception:
    # Never expose module exception details or student data.
    sys.exit(76)
sys.exit(0)
"""


class RoutingContractError(ValueError):
    """Staged PDS2 routing profile could not be qualified for installed Core."""


class RoutingContractStatus(str, Enum):
    """Qualified profile structure only; not route execution or launch authority."""

    PDS2_PROFILE_VALID_NOT_DISPATCHED = "pds2_profile_valid_not_dispatched"
    NOT_DECLARED = "not_declared"


@dataclass(frozen=True, slots=True)
class ObservedRoutingContract:
    """Ephemeral exact installed-profile evidence, never an active receipt."""

    transaction_id: str
    component_id: str
    status: RoutingContractStatus
    provider_target: str | None
    pip_inventory_sha256: str
    native_payload_sha256: str
    provider_declaration_sha256: str


def probe_signed_routing_contract(
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
) -> ObservedRoutingContract:
    """Validate an authenticated PDS2 ModuleProfile against installed Core.

    Calls only the provider profile factory after explicit opt-in. The Core
    validator checks handler/validator callability but handlers are not called.
    The staged byte and native signature checks repeat after the factory call;
    even a successful result never authorizes execution of a live module.
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
        raise RoutingContractError(
            "explicit bounded routing contract execution required"
        )
    try:
        root = _safe_root(stage_root.parent, classroom_workspace)
        if _relative_child(root, stage_root) == _relative_child(root, wheelhouse):
            raise RoutingContractError("stage and wheelhouse overlap")
    except UpdateJournalError as error:
        raise RoutingContractError("unsafe software/classroom boundary") from error

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
            raise RoutingContractError("signed routing provider scope mismatch")
        if first.status is ProviderImportStatus.NOT_DECLARED:
            return ObservedRoutingContract(
                first.transaction_id,
                component_id,
                RoutingContractStatus.NOT_DECLARED,
                None,
                first.pip_inventory_sha256,
                first.native_payload_sha256,
                first.provider_declaration_sha256,
            )
        if (
            first.status is not ProviderImportStatus.IMPORTABLE_NOT_CONTRACT_TESTED
            or first.target is None
        ):
            raise RoutingContractError("routing provider import evidence incomplete")
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
            raise RoutingContractError("routing provider has no trusted distribution")
        executable = stage_root / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        failure: CandidateAcceptanceError | None = None
        with tempfile.TemporaryDirectory(
            prefix=".pds-routing-contract-", dir=root
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
            raise RoutingContractError("signed routing stage drifted during probe")
        if failure is not None:
            raise RoutingContractError(
                "staged Core routing contract validation failed"
            ) from failure
        return ObservedRoutingContract(
            first.transaction_id,
            component_id,
            RoutingContractStatus.PDS2_PROFILE_VALID_NOT_DISPATCHED,
            first.target,
            first.pip_inventory_sha256,
            first.native_payload_sha256,
            first.provider_declaration_sha256,
        )
    except (ProviderImportError, CatalogVerificationError) as error:
        raise RoutingContractError(
            "signed routing provider or installed Core preflight failed"
        ) from error


__all__ = (
    "ObservedRoutingContract",
    "RoutingContractError",
    "RoutingContractStatus",
    "probe_signed_routing_contract",
)
