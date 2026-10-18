"""Issue #49 Slice 24: publisher-bound full pip stage evidence, no execution."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice23_real_pip_direct_url as pip_fixture
from test_issue49_slice3_signature_verification import (
    NOW,
    _encode,
    _module,
    _registry,
    _ring,
    _signed,
)
from test_issue49_slice7_signed_lock_and_records import _claims

from paper_data_suite.evergreen_publisher_pip_preflight import (
    PublisherPipPreflightError,
    audit_publisher_bound_pip_candidate,
)


def _signed_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    registry = _registry()
    registry["modules"].append(
        {
            "component_id": "demo",
            "repository": "Paper-Data-Suite/pds-demo-app",
            "distribution": "demo-app",
            "signing_key_ids": ["attacker"],
        }
    )
    signed_registry = _signed(registry, "root-primary")

    def claims(pins: tuple[Any, ...]) -> dict[str, Any]:
        output = _claims(pins)
        output["registry_payload_sha256"] = hashlib.sha256(
            _encode(registry)
        ).hexdigest()
        return output

    with monkeypatch.context() as context:
        context.setattr(pip_fixture, "_registry_bytes", lambda: signed_registry)
        context.setattr(pip_fixture, "_claims", claims)
        wheels, reg, lock, prepared = pip_fixture._signed_wheels(tmp_path)
    stage = tmp_path / "private-staged-venv"
    pip_fixture._run(
        os.sys.executable, "-m", "venv", "--copies", "--without-pip", str(stage)
    )
    pip_fixture._run(
        os.sys.executable,
        "-m",
        "pip",
        "--python",
        str(stage),
        "install",
        "--no-index",
        "--no-deps",
        "--no-compile",
        "--no-cache-dir",
        *(str(wheel) for wheel in sorted(wheels.glob("*.whl"))),
    )
    wheel = wheels / "demo_app-1.0.0-py3-none-any.whl"
    release = _module()
    release.update(
        {
            "component_id": "demo",
            "repository": "Paper-Data-Suite/pds-demo-app",
            "distribution": "demo-app",
        }
    )
    release["releases"][0].update(
        {
            "version": "1.0.0",
            "tag": "v1.0.0",
            "wheel": wheel.name,
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "requires_python": ">=3.11",
            "requires_dist": ["demo-core>=2,<3"],
            "console_script": "demo",
            "console_target": "demo_app.cli:main",
        }
    )
    return stage, wheels, reg, lock, prepared, _signed(release, "attacker")


@pytest.fixture(scope="module")
def signed_real_pip(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("publisher-pip")
    monkeypatch = pytest.MonkeyPatch()
    try:
        return _signed_stage(root, monkeypatch)
    finally:
        monkeypatch.undo()


def _inputs(stage: Path, base: tuple[Any, ...]) -> dict[str, Any]:
    _, wheels, registry, lock, prepared, release = base
    return {
        "stage_root": stage,
        "wheelhouse": wheels,
        "prepared_record": prepared,
        "registry_envelope": registry,
        "lock_envelope": lock,
        "module_envelopes": {"demo": release},
        "trust": _ring(),
        "now": NOW,
    }


@pytest.fixture
def candidate(
    signed_real_pip: tuple[Any, ...], tmp_path: Path
) -> tuple[Path, dict[str, Any]]:
    stage = tmp_path / "candidate"
    shutil.copytree(signed_real_pip[0], stage)
    return stage, _inputs(stage, signed_real_pip)


def _site(stage: Path) -> Path:
    return pip_fixture._site(stage)


def _launcher(stage: Path) -> Path:
    return stage / ("Scripts/demo.exe" if os.name == "nt" else "bin/demo")


def test_real_pip_stage_and_publisher_signatures_join_without_execution(
    candidate: tuple[Path, dict[str, Any]],
) -> None:
    stage, arguments = candidate
    with patch("subprocess.run", side_effect=AssertionError("must not execute")):
        output = audit_publisher_bound_pip_candidate(**arguments)
    assert output.transaction_id == "e" * 32
    assert output.stage_root == stage
    assert output.root_console_targets == (("demo-app", "demo", "demo_app.cli:main"),)
    assert output.external_distributions == ("demo-core",)
    assert output.installed_launcher_paths == (
        ("Scripts/demo.exe" if os.name == "nt" else "bin/demo"),
    )
    assert len(output.publisher_digests) == 1
    assert len(output.pip_inventory_sha256) == 64
    assert not hasattr(output, "can_launch")
    assert not hasattr(output, "active_receipt")


def test_missing_publisher_cannot_be_replaced_by_signed_lock(
    candidate: tuple[Path, dict[str, Any]],
) -> None:
    _, arguments = candidate
    arguments["module_envelopes"] = {}
    with pytest.raises(PublisherPipPreflightError, match="preflight inputs"):
        audit_publisher_bound_pip_candidate(**arguments)


def test_foreign_publisher_key_cannot_authorize_pip_install(
    candidate: tuple[Path, dict[str, Any]],
) -> None:
    _, arguments = candidate
    original = arguments["module_envelopes"]["demo"]
    content = json.loads(base64.b64decode(json.loads(original)["payload_b64"]))
    arguments["module_envelopes"] = {"demo": _signed(content, "portia-primary")}
    with pytest.raises(PublisherPipPreflightError, match="publisher evidence"):
        audit_publisher_bound_pip_candidate(**arguments)


@pytest.mark.parametrize("tamper", ["source", "launcher", "origin", "extra"])
def test_tampering_installed_file_or_generated_origin_refused(
    candidate: tuple[Path, dict[str, Any]], tamper: str
) -> None:
    stage, arguments = candidate
    if tamper == "source":
        path = _site(stage) / "demo_app/__init__.py"
        path.write_bytes(path.read_bytes() + b"tamper")
    elif tamper == "launcher":
        path = _launcher(stage)
        path.write_bytes(path.read_bytes() + b"tamper")
    elif tamper == "origin":
        path = _site(stage) / "demo_app-1.0.0.dist-info/direct_url.json"
        contents = json.loads(path.read_bytes())
        contents["url"] = "https://attacker.invalid/demo.whl"
        path.write_text(json.dumps(contents), encoding="utf-8")
    else:
        (_site(stage) / "usercustomize.py").write_text("print('hi')")
    with pytest.raises(PublisherPipPreflightError, match="pip installation"):
        audit_publisher_bound_pip_candidate(**arguments)


def test_signed_console_target_substitution_is_refused(
    candidate: tuple[Path, dict[str, Any]],
) -> None:
    _, arguments = candidate
    original = arguments["module_envelopes"]["demo"]
    content = json.loads(base64.b64decode(json.loads(original)["payload_b64"]))
    content["releases"][0]["console_target"] = "demo_app.cli:wrong"
    arguments["module_envelopes"] = {"demo": _signed(content, "attacker")}
    with pytest.raises(PublisherPipPreflightError, match="publisher evidence"):
        audit_publisher_bound_pip_candidate(**arguments)


def test_unauthorized_additional_envelope_rejected(
    candidate: tuple[Path, dict[str, Any]],
) -> None:
    _, arguments = candidate
    arguments["module_envelopes"]["unregistered"] = b"extra"
    with pytest.raises(PublisherPipPreflightError, match="publisher evidence"):
        audit_publisher_bound_pip_candidate(**arguments)


def test_changed_publisher_evidence_during_audit_refused(
    candidate: tuple[Path, dict[str, Any]],
) -> None:
    _, arguments = candidate
    from paper_data_suite.evergreen_publisher_pip_preflight import (
        verify_publisher_bound_composition,
    )

    count = 0

    def changed(*args: Any, **kwargs: Any):
        nonlocal count
        count += 1
        value = verify_publisher_bound_composition(*args, **kwargs)
        return replace(value, lock_payload_sha256="f" * 64) if count == 2 else value

    with patch(
        "paper_data_suite.evergreen_publisher_pip_preflight."
        "verify_publisher_bound_composition",
        side_effect=changed,
    ):
        with pytest.raises(PublisherPipPreflightError, match="changed during"):
            audit_publisher_bound_pip_candidate(**arguments)
    assert count == 2


def test_invalid_input_does_not_touch_stage(
    candidate: tuple[Path, dict[str, Any]],
) -> None:
    stage, arguments = candidate
    before = _launcher(stage).read_bytes()
    arguments["module_envelopes"] = {"demo": "not-bytes"}
    with pytest.raises(PublisherPipPreflightError, match="preflight inputs"):
        audit_publisher_bound_pip_candidate(**arguments)
    assert _launcher(stage).read_bytes() == before
