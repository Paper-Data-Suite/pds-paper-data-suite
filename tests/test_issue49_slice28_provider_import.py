"""Issue #49 Slice 28: explicit staged provider import is not Core readiness."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice23_real_pip_direct_url as pip_fixture
import test_issue49_slice24_publisher_pip_preflight as publisher_fixture
from test_issue49_slice3_signature_verification import (
    NOW,
    _encode,
    _private,
    _ring,
)
from test_issue49_slice9_virtualenv_runtime import _console_wheel as _base_console_wheel

from paper_data_suite.evergreen_provider_import_probe import (
    ProviderImportError,
    ProviderImportStatus,
    probe_signed_provider_import,
)

_CONTEXT = b"pds-evergreen-staged-native-evidence-v1\x00"
_GROUP = "paper_data_suite.module_operations"


def _provider_wheel(
    path: Path,
    *,
    module_body: bytes | None = None,
) -> None:
    _base_console_wheel(path)
    stream = io.BytesIO(path.read_bytes())
    updated = io.BytesIO()
    with (
        zipfile.ZipFile(stream) as original,
        zipfile.ZipFile(updated, "w", compression=zipfile.ZIP_DEFLATED) as output,
    ):
        for item in original.infolist():
            if item.filename.endswith("/entry_points.txt"):
                continue
            content = (
                b"# trusted fixture package\n"
                if item.filename == "demo_app/__init__.py"
                else original.read(item)
            )
            output.writestr(item, content)
        output.writestr(
            "demo_app-1.0.0.dist-info/entry_points.txt",
            "[console_scripts]\ndemo = demo_app.cli:main\n\n"
            f"[{_GROUP}]\ndemo = demo_app.pds_operations:get_profile\n",
        )
        output.writestr(
            "demo_app/pds_operations.py",
            module_body
            if module_body is not None
            else (
                b"def get_profile():\n"
                b"    raise AssertionError('provider function must not run')\n"
            ),
        )
    path.write_bytes(updated.getvalue())


def _native_evidence(stage: Path, prepared: bytes) -> bytes:
    doc = json.loads(prepared)
    folder = "Scripts" if os.name == "nt" else "bin"
    names = [
        f"{folder}/python.exe" if os.name == "nt" else "bin/python",
        f"{folder}/demo.exe" if os.name == "nt" else "bin/demo",
    ]
    if os.name == "nt" and (stage / "Scripts/pythonw.exe").exists():
        names.append("Scripts/pythonw.exe")
    payload = _encode(
        {
            "record_type": "pds_evergreen_staged_native_evidence",
            "schema_version": 1,
            "revision": 1,
            "issued_at": "2026-10-17T16:00:00Z",
            "expires_at": "2026-11-17T16:00:00Z",
            "transaction_id": doc["transaction_id"],
            "registry_payload_sha256": doc["registry_payload_sha256"],
            "lock_payload_sha256": doc["lock_payload_sha256"],
            "trust_fingerprint": doc["trust_fingerprint"],
            "python_minor": doc["python_minor"],
            "platform": doc["platform"],
            "files": [
                {
                    "relative_path": name,
                    "sha256": hashlib.sha256((stage / name).read_bytes()).hexdigest(),
                    "size": (stage / name).stat().st_size,
                }
                for name in names
            ],
        }
    )
    return _encode(
        {
            "envelope_version": 1,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "signatures": [
                {
                    "key_id": "root-primary",
                    "algorithm": "ed25519",
                    "signature_b64": base64.b64encode(
                        _private("root-primary").sign(_CONTEXT + payload)
                    ).decode("ascii"),
                }
            ],
        }
    )


@pytest.fixture(scope="module")
def signed_provider_stage(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, ...]:
    root = tmp_path_factory.mktemp("signed-provider-import")
    patcher = pytest.MonkeyPatch()
    with patcher.context() as context:
        context.setattr(pip_fixture, "_console_wheel", _provider_wheel)
        stage, wheels, reg, lock, prepared, release = publisher_fixture._signed_stage(
            root, patcher
        )
    workspace = root.parent / (root.name + "-classroom-not-used")
    workspace.mkdir()
    return stage, wheels, reg, lock, prepared, release, workspace


@pytest.fixture(scope="module")
def signed_undeclared_stage(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Any, ...]:
    root = tmp_path_factory.mktemp("signed-no-provider-import")
    patcher = pytest.MonkeyPatch()
    try:
        stage, wheels, reg, lock, prepared, release = publisher_fixture._signed_stage(
            root, patcher
        )
    finally:
        patcher.undo()
    workspace = root.parent / (root.name + "-classroom-not-used")
    workspace.mkdir()
    return stage, wheels, reg, lock, prepared, release, workspace


def _inputs(base: tuple[Any, ...]) -> dict[str, Any]:
    stage, wheels, registry, lock, record, release, workspace = base
    return {
        "stage_root": stage,
        "wheelhouse": wheels,
        "classroom_workspace": workspace,
        "prepared_record": record,
        "registry_envelope": registry,
        "lock_envelope": lock,
        "evidence_envelope": _native_evidence(stage, record),
        "module_envelopes": {"demo": release},
        "component_id": "demo",
        "group": _GROUP,
        "trust": _ring(),
        "now": NOW,
        "allow_candidate_execution": True,
    }


def test_genuine_offline_pip_provider_imports_without_invoking_callable(
    signed_provider_stage: tuple[Any, ...],
) -> None:
    output = probe_signed_provider_import(**_inputs(signed_provider_stage))
    assert output.status is ProviderImportStatus.IMPORTABLE_NOT_CONTRACT_TESTED
    assert output.target == "demo_app.pds_operations:get_profile"
    assert output.transaction_id == "e" * 32
    assert len(output.pip_inventory_sha256) == 64
    assert len(output.native_payload_sha256) == 64
    assert not hasattr(output, "can_launch")
    assert not hasattr(output, "provider_ready")


def test_absent_optional_provider_never_executes(
    signed_undeclared_stage: tuple[Any, ...],
) -> None:
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        result = probe_signed_provider_import(**_inputs(signed_undeclared_stage))
    assert result.status is ProviderImportStatus.NOT_DECLARED
    assert result.target is None
    assert not hasattr(result, "can_launch")


def test_execution_requires_explicit_opt_in(
    signed_provider_stage: tuple[Any, ...],
) -> None:
    options = _inputs(signed_provider_stage)
    options.pop("allow_candidate_execution")
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ProviderImportError, match="explicit execution"):
            probe_signed_provider_import(**options)


@pytest.mark.parametrize("bad", [0, -1, 61, 2.5, True])
def test_invalid_timeout_never_executes(
    signed_provider_stage: tuple[Any, ...],
    bad: object,
) -> None:
    options = _inputs(signed_provider_stage)
    options["timeout_seconds"] = bad
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ProviderImportError, match="execution approval"):
            probe_signed_provider_import(**options)


def test_native_bytes_must_match_independently_signed_digest(
    signed_provider_stage: tuple[Any, ...],
) -> None:
    options = _inputs(signed_provider_stage)
    native = json.loads(options["evidence_envelope"])
    native["payload_b64"] = base64.b64encode(b"invalid").decode()
    options["evidence_envelope"] = _encode(native)
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ProviderImportError, match="signed provider"):
            probe_signed_provider_import(**options)


def test_unsigned_publisher_does_not_trigger_import(
    signed_provider_stage: tuple[Any, ...],
) -> None:
    options = _inputs(signed_provider_stage)
    options["module_envelopes"] = {}
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ProviderImportError):
            probe_signed_provider_import(**options)


def test_invalid_provider_scope_does_not_trigger_import(
    signed_provider_stage: tuple[Any, ...],
) -> None:
    options = _inputs(signed_provider_stage)
    options["group"] = "arbitrary.plugins"
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ProviderImportError):
            probe_signed_provider_import(**options)


def test_stage_package_change_disallows_import(
    signed_provider_stage: tuple[Any, ...],
    tmp_path: Path,
) -> None:
    stage = signed_provider_stage[0].parent / f"staged-{tmp_path.name}"
    shutil.copytree(signed_provider_stage[0], stage)
    values = list(signed_provider_stage)
    values[0] = stage
    site = pip_fixture._site(stage)
    (site / "demo_app/pds_operations.py").write_bytes(b"tampered\n")
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ProviderImportError):
            probe_signed_provider_import(**_inputs(tuple(values)))


def test_mutation_during_runtime_import_is_detected(
    signed_provider_stage: tuple[Any, ...],
    tmp_path: Path,
) -> None:
    stage = signed_provider_stage[0].parent / f"mutating-{tmp_path.name}"
    shutil.copytree(signed_provider_stage[0], stage)
    values = list(signed_provider_stage)
    values[0] = stage

    def mutate(*args: Any, **kwargs: Any) -> None:
        target = pip_fixture._site(stage) / "demo_app/pds_operations.py"
        target.write_bytes(target.read_bytes() + b"# mutation\n")

    with patch(
        "paper_data_suite.evergreen_provider_import_probe._run_check",
        side_effect=mutate,
    ):
        with pytest.raises(ProviderImportError):
            probe_signed_provider_import(**_inputs(tuple(values)))


def test_workspace_overlap_is_refused_before_import(
    signed_provider_stage: tuple[Any, ...],
) -> None:
    options = _inputs(signed_provider_stage)
    options["classroom_workspace"] = options["stage_root"]
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ProviderImportError, match="classroom boundary"):
            probe_signed_provider_import(**options)


def test_failed_subprocess_does_not_report_callable(
    signed_provider_stage: tuple[Any, ...],
) -> None:
    options = _inputs(signed_provider_stage)
    from paper_data_suite.evergreen_candidate_acceptance import (
        CandidateAcceptanceError,
    )

    with patch(
        "paper_data_suite.evergreen_provider_import_probe._run_check",
        side_effect=CandidateAcceptanceError("redacted failure"),
    ):
        with pytest.raises(
            ProviderImportError, match="isolated provider import failed"
        ):
            probe_signed_provider_import(**options)


def test_observation_never_writes_into_workspace(
    signed_provider_stage: tuple[Any, ...],
) -> None:
    workspace = signed_provider_stage[-1]
    assert list(workspace.rglob("*")) == []
    probe_signed_provider_import(**_inputs(signed_provider_stage))
    assert list(workspace.rglob("*")) == []
