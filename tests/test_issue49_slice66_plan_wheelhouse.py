"""Slice 66: signed complete wheel bytes must match the whole reviewed plan."""

from __future__ import annotations

import sys
import sysconfig
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice64_composition_review_plan as previous

import paper_data_suite.evergreen_plan_wheelhouse_preflight as module
from paper_data_suite.evergreen_composition_review_plan import (
    plan_authenticated_composition_review,
)
from paper_data_suite.evergreen_dependency_lock import DependencyLockError
from paper_data_suite.evergreen_plan_wheelhouse_preflight import (
    PlanWheelhousePreflightError,
    inspect_plan_bound_wheelhouse,
)
from paper_data_suite.evergreen_release_artifacts import VerifiedReleaseWheel

NOW = datetime(2026, 10, 25, 19, tzinfo=UTC)
PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"
PLATFORM = sysconfig.get_platform().lower()


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    snapshot, witnessed = previous.sample()
    requested: dict[str, str | None] = {"quillan": "0.10.0"}
    plan = plan_authenticated_composition_review(
        snapshot,
        witnessed,
        requested_targets=requested,
        python_minor=PYTHON,
        platform_tag=PLATFORM,
    )
    selected = {item.component_id: item for item in plan.modules if item.to_version}
    by_component = {doc.claims.component_id: doc for doc in snapshot.modules}
    actual = []
    for component, row in selected.items():
        assert row.to_version and row.to_wheel_sha256
        release = next(
            x
            for x in by_component[component].claims.releases
            if x.version == row.to_version
        )
        actual.append(
            SimpleNamespace(
                distribution=row.distribution,
                version=row.to_version,
                filename=release.wheel,
                sha256=row.to_wheel_sha256,
            )
        )
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    for wheel in actual:
        (wheelhouse / wheel.filename).write_bytes(b"test-only source wheel")
    module_envelopes = {key: key.encode("ascii") for key in selected}
    locked = SimpleNamespace(
        lock=SimpleNamespace(
            registry_payload_sha256=snapshot.registry.payload_sha256,
            python_minor=PYTHON,
            platform=PLATFORM,
            roots=tuple(sorted(x.distribution for x in actual)),
            payload_sha256="9" * 64,
            revision=4,
        ),
        inspection=SimpleNamespace(wheels=tuple(actual)),
    )
    calls: list[str] = []

    def check_registry(*args: Any, **kwargs: Any) -> Any:
        calls.append("registry")
        return snapshot.registry

    def check_lock(*args: Any, **kwargs: Any) -> Any:
        calls.append("lock")
        assert args == (wheelhouse,)
        assert kwargs["lock_envelope"] == b"signed lock"
        return locked

    def check_module(envelope: bytes, **kwargs: Any) -> Any:
        calls.append("publisher")
        return by_component[envelope.decode("ascii")]

    def check_release(path: Path, **kwargs: Any) -> VerifiedReleaseWheel:
        calls.append("wheel")
        item = next(x for x in actual if x.filename == path.name)
        doc = by_component[item.distribution.removeprefix("pds-")]
        return VerifiedReleaseWheel(
            doc.claims.component_id,
            item.distribution,
            item.version,
            item.filename,
            item.sha256,
            doc.payload_sha256,
            snapshot.registry.payload_sha256,
            (),
            item.distribution.removeprefix("pds-"),
            item.distribution.replace("-", "_") + ".cli:main",
        )

    monkeypatch.setattr(module, "verify_registry_document", check_registry)
    monkeypatch.setattr(module, "verify_signed_locked_wheelhouse", check_lock)
    monkeypatch.setattr(module, "verify_module_document", check_module)
    monkeypatch.setattr(module, "verify_signed_release_wheel", check_release)
    return {
        "args": dict(
            snapshot=snapshot,
            witnessed=witnessed,
            wheelhouse=wheelhouse,
            requested_targets=requested,
            python_minor=PYTHON,
            platform_tag=PLATFORM,
            registry_envelope=b"signed registry",
            lock_envelope=b"signed lock",
            module_envelopes=module_envelopes,
            trust=SimpleNamespace(),
            now=NOW,
        ),
        "locked": locked,
        "actual": actual,
        "calls": calls,
        "wheelhouse": wheelhouse,
    }


def run(ready: dict[str, Any], **changes: Any) -> Any:
    # The fake keyring is accepted only after monkeypatching exact type guard.
    return inspect_plan_bound_wheelhouse(**{**ready["args"], **changes})


def test_verified_complete_wheelhouse_is_not_installation_authority(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:

    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    before = {p.name: p.read_bytes() for p in ready["wheelhouse"].iterdir()}
    with (
        patch("subprocess.run", side_effect=AssertionError("process")),
        patch("socket.create_connection", side_effect=AssertionError("network")),
    ):
        report = run(ready)
    assert len(report.pds_wheels) == 3
    assert report.signed_lock_revision == 4
    assert report.status == "SIGNED_CLOSED_WHEELHOUSE_OBSERVED_NOT_INSTALLED"
    assert (
        report.authority
        == "NO_DOWNLOAD_INSTALL_STAGE_ACTIVATION_RECEIPT_OR_LAUNCH_AUTHORITY"
    )
    assert report.external_wheels == ()
    assert ready["calls"].count("lock") == 2
    assert ready["calls"].count("wheel") == 6
    assert {p.name: p.read_bytes() for p in ready["wheelhouse"].iterdir()} == before
    for action in ("install", "activate", "launch", "stage", "commit"):
        assert not hasattr(report, action)


@pytest.mark.parametrize(
    "field,value",
    [
        ("snapshot", object()),
        ("witnessed", object()),
        ("wheelhouse", "not-a-path"),
        ("trust", None),
        ("module_envelopes", {}),
        ("now", datetime(2026, 10, 25, 19)),
    ],
)
def test_invalid_arguments_refuse_before_file_or_signature_checks(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(PlanWheelhousePreflightError, match="inputs"):
        run(ready, **{field: value})
    assert ready["calls"] == []


def test_real_trust_guard_refuses_unprovisioned_keyring(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanWheelhousePreflightError, match="inputs"):
        run(ready)
    assert ready["calls"] == []


def test_unregistered_request_refuses_before_signed_lock(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    with pytest.raises(PlanWheelhousePreflightError, match="plan"):
        run(ready, requested_targets={"foreign": "1.0.0"})
    assert ready["calls"] == []


def test_root_lock_must_describe_entire_selected_composition(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    ready["locked"].lock.roots = ("pds-quillan",)
    with pytest.raises(PlanWheelhousePreflightError, match="roots"):
        run(ready)


def test_signed_wheel_digest_mismatch_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    ready["actual"][0].sha256 = "0" * 64
    with pytest.raises(PlanWheelhousePreflightError, match="differs from signed lock"):
        run(ready)


def test_missing_pds_wheel_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    ready["locked"].inspection.wheels = ready["locked"].inspection.wheels[:-1]
    with pytest.raises(PlanWheelhousePreflightError, match="missing or extra"):
        run(ready)


def test_extra_registered_pds_wheel_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    extra = SimpleNamespace(
        distribution="pds-portia",
        version="0.2.0",
        filename="portia.whl",
        sha256="a" * 64,
    )
    ready["locked"].inspection.wheels += (extra,)
    with pytest.raises(PlanWheelhousePreflightError, match="missing or extra"):
        run(ready)


def test_unregistered_pds_like_dependency_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    extra = SimpleNamespace(
        distribution="pds-foreign",
        version="1.0.0",
        filename="foreign.whl",
        sha256="a" * 64,
    )
    ready["locked"].inspection.wheels += (extra,)
    with pytest.raises(PlanWheelhousePreflightError, match="unknown PDS"):
        run(ready)


def test_missing_publisher_envelope_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    envelopes = dict(ready["args"]["module_envelopes"])
    del envelopes["core"]
    with pytest.raises(PlanWheelhousePreflightError, match="signed publisher"):
        run(ready, module_envelopes=envelopes)


def test_signed_catalog_cache_mismatch_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    monkeypatch.setattr(
        module, "verify_registry_document", lambda *args, **kwargs: SimpleNamespace()
    )
    with pytest.raises(PlanWheelhousePreflightError, match="signed cache"):
        run(ready)


def test_signed_lock_refusal_is_not_silently_downgraded(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)

    def reject(*args: Any, **kwargs: Any) -> None:
        raise DependencyLockError("untrusted lock")

    monkeypatch.setattr(module, "verify_signed_locked_wheelhouse", reject)
    with pytest.raises(PlanWheelhousePreflightError, match="verification refused"):
        run(ready)


def test_nonregular_selected_wheel_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    (ready["wheelhouse"] / ready["actual"][0].filename).unlink()
    with pytest.raises(PlanWheelhousePreflightError, match="wheel missing"):
        run(ready)


def test_second_audit_drift_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    first = module.verify_signed_locked_wheelhouse
    calls = 0

    def changed(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        evidence = first(*args, **kwargs)
        if calls == 2:
            return SimpleNamespace(
                lock=replace_fake(evidence.lock), inspection=evidence.inspection
            )
        return evidence

    monkeypatch.setattr(module, "verify_signed_locked_wheelhouse", changed)
    with pytest.raises(PlanWheelhousePreflightError, match="changed during audit"):
        run(ready)


def replace_fake(lock: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(**{**vars(lock), "payload_sha256": "7" * 64})
