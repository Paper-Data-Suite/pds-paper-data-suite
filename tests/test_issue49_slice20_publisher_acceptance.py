"""Issue #49 Slice 20: delegated publisher evidence must precede candidate import."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice9_virtualenv_runtime as venv_fixture
from test_issue49_slice3_signature_verification import (
    _encode,
    _module,
    _registry,
    _signed,
)
from test_issue49_slice7_signed_lock_and_records import _claims
from test_issue49_slice11_update_journal import Scene

from paper_data_suite.evergreen_publisher_acceptance import (
    PublisherAcceptanceError,
    accept_publisher_bound_candidate_public_contracts,
)


def _scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Scene, bytes]:
    """Real synthetic signed registered demo-app + closed staged wheelhouse."""
    registry = _registry()
    registry["modules"].append(
        {
            "component_id": "demo",
            "repository": "Paper-Data-Suite/pds-demo-app",
            "distribution": "demo-app",
            # An otherwise unused synthetic key; no private runtime keys.
            "signing_key_ids": ["attacker"],
        }
    )
    signed_registry = _signed(registry, "root-primary")
    original_claims = _claims

    def claims(pins: tuple[Any, ...]) -> dict[str, Any]:
        output = original_claims(pins)
        output["registry_payload_sha256"] = hashlib.sha256(
            _encode(registry)
        ).hexdigest()
        return output

    monkeypatch.setattr(venv_fixture, "_registry_bytes", lambda: signed_registry)
    monkeypatch.setattr(venv_fixture, "_claims", claims)
    scene = Scene(tmp_path, layout="windows" if os.name == "nt" else "posix")
    scene.begin()
    wheel = scene.wheels / "demo_app-1.0.0-py3-none-any.whl"
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
    return scene, _signed(release, "attacker")


def _inputs(scene: Scene, release: bytes) -> dict[str, Any]:
    return {
        "software_root": scene.manager,
        "transaction_id": scene.tx,
        "expected_revision": 1,
        "module_envelopes": {"demo": release},
        **scene.inputs(),
    }


def _success(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
    assert "-I" in args and "-B" in args
    assert kwargs["check"] is False
    return subprocess.CompletedProcess(args, 0)


def test_publisher_authorizes_public_import_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    with patch(
        "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
        side_effect=_success,
    ) as process:
        output = accept_publisher_bound_candidate_public_contracts(
            **_inputs(scene, release)
        )
    assert process.call_count == 1
    assert output.transaction_id == scene.tx
    payload = base64.b64decode(json.loads(release)["payload_b64"])
    assert output.publisher_digests == (("demo", hashlib.sha256(payload).hexdigest()),)
    assert output.root_console_targets == (("demo-app", "demo", "demo_app.cli:main"),)
    assert output.external_distributions == ("demo-core",)
    assert not hasattr(output, "can_launch")
    assert not hasattr(output, "active_receipt")
    assert scene.load().revision == 1


def test_no_delegated_envelope_never_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    inputs = _inputs(scene, release)
    inputs["module_envelopes"] = {}
    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run") as run:
        with pytest.raises(PublisherAcceptanceError, match="invalid publisher"):
            accept_publisher_bound_candidate_public_contracts(**inputs)
    run.assert_not_called()


def test_wrong_signer_never_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    content = json.loads(base64.b64decode(json.loads(release)["payload_b64"]))
    inputs = _inputs(scene, _signed(content, "portia-primary"))
    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run") as run:
        with pytest.raises(PublisherAcceptanceError, match="delegated publisher"):
            accept_publisher_bound_candidate_public_contracts(**inputs)
    run.assert_not_called()


def test_publisher_hash_changed_never_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    content = json.loads(base64.b64decode(json.loads(release)["payload_b64"]))
    content["releases"][0]["sha256"] = "a" * 64
    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run") as run:
        with pytest.raises(PublisherAcceptanceError, match="delegated publisher"):
            accept_publisher_bound_candidate_public_contracts(
                **_inputs(scene, _signed(content, "attacker"))
            )
    run.assert_not_called()


def test_changed_wheel_never_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    wheel = scene.wheels / "demo_app-1.0.0-py3-none-any.whl"
    wheel.write_bytes(wheel.read_bytes() + b"tamper")
    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run") as run:
        with pytest.raises(PublisherAcceptanceError, match="delegated publisher"):
            accept_publisher_bound_candidate_public_contracts(**_inputs(scene, release))
    run.assert_not_called()


def test_wrong_journal_revision_blocks_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    scene.arm()
    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run") as run:
        with pytest.raises(PublisherAcceptanceError, match="exact candidate"):
            accept_publisher_bound_candidate_public_contracts(**_inputs(scene, release))
    run.assert_not_called()


def test_candidate_source_change_blocks_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    version = os.sys.version_info
    site = scene.stage / (
        "Lib/site-packages"
        if os.name == "nt"
        else f"lib/python{version.major}.{version.minor}/site-packages"
    )
    path = site / "demo_app/__init__.py"
    path.write_bytes(path.read_bytes() + b"modified")
    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run") as run:
        with pytest.raises(PublisherAcceptanceError, match="public import"):
            accept_publisher_bound_candidate_public_contracts(**_inputs(scene, release))
    run.assert_not_called()


def test_publisher_rechecked_after_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    from paper_data_suite.evergreen_publisher_acceptance import (
        verify_publisher_bound_composition,
    )

    original = verify_publisher_bound_composition
    seen = 0

    def observe(*args: Any, **kwargs: Any):
        nonlocal seen
        seen += 1
        output = original(*args, **kwargs)
        if seen == 2:
            return replace(output, lock_payload_sha256="a" * 64)
        return output

    with (
        patch(
            "paper_data_suite.evergreen_candidate_acceptance.subprocess.run",
            side_effect=_success,
        ),
        patch(
            "paper_data_suite.evergreen_publisher_acceptance."
            "verify_publisher_bound_composition",
            side_effect=observe,
        ),
    ):
        with pytest.raises(PublisherAcceptanceError, match="changed during imports"):
            accept_publisher_bound_candidate_public_contracts(**_inputs(scene, release))
    assert seen == 2


def test_refuse_different_publisher_console_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    from paper_data_suite.evergreen_publisher_acceptance import _root_consistency
    from paper_data_suite.evergreen_publisher_composition import (
        verify_publisher_bound_composition,
    )

    observed = verify_publisher_bound_composition(
        scene.wheels,
        prepared_record=scene.prepared,
        registry_envelope=scene.registry,
        lock_envelope=scene.lock,
        module_envelopes={"demo": release},
        trust=scene.inputs()["trust"],
        now=scene.inputs()["now"],
    )
    with pytest.raises(PublisherAcceptanceError, match="consoles differ"):
        _root_consistency(
            observed,
            prepared_record=scene.prepared,
            observed=(("demo-app", "forged", "demo_app.cli:main"),),
        )


@pytest.mark.parametrize("invalid", [None, [], {"demo": "bad"}, {"demo": b""}])
def test_invalid_publisher_arguments_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: Any
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    inputs = _inputs(scene, release)
    inputs["module_envelopes"] = invalid
    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run") as run:
        with pytest.raises(PublisherAcceptanceError, match="invalid publisher"):
            accept_publisher_bound_candidate_public_contracts(**inputs)
    run.assert_not_called()


def test_wrong_lock_and_registry_refs_block_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene, release = _scene(tmp_path, monkeypatch)
    params = _inputs(scene, release)
    params["lock_envelope"] += b" "
    with patch("paper_data_suite.evergreen_candidate_acceptance.subprocess.run") as run:
        with pytest.raises(
            PublisherAcceptanceError, match="journal candidate evidence"
        ):
            accept_publisher_bound_candidate_public_contracts(**params)
    run.assert_not_called()
