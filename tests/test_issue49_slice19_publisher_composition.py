"""Issue #49 Slice 19: publisher delegation binds every selected PDS wheel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_issue49_slice3_signature_verification import (
    NOW,
    _encode,
    _module,
    _registry,
    _ring,
    _signed,
)
from test_issue49_slice5_rotation_and_artifacts import _wheel_bytes
from test_issue49_slice6_wheelhouse import _add
from test_issue49_slice7_signed_lock_and_records import _claims, _signed_lock

from paper_data_suite.evergreen_install_records import (
    prepare_composition_record,
    serialize_prepared_record,
)
from paper_data_suite.evergreen_publisher_composition import (
    PublisherCompositionError,
    verify_publisher_bound_composition,
)
from paper_data_suite.evergreen_wheelhouse import WheelPin


class Scene:
    def __init__(self, tmp_path: Path) -> None:
        self.directory = tmp_path
        self.wheel = tmp_path / "quillan-0.10.7-py3-none-any.whl"
        raw = _wheel_bytes()
        self.wheel.write_bytes(raw)
        quillan = WheelPin(self.wheel.name, hashlib.sha256(raw).hexdigest())
        core = _add(tmp_path, name="pds-core", version="0.6.6", requirements=())
        self.registry = _signed(_registry(), "root-primary")
        lock_claims = _claims((quillan, core))
        lock_claims["roots"] = ["quillan"]
        self.lock = _signed_lock(lock_claims, "root-primary")
        release = _module()
        release["releases"][0]["sha256"] = quillan.sha256
        self.release = _signed(release, "quillan-primary")
        record = prepare_composition_record(
            tmp_path,
            lock_envelope=self.lock,
            registry_envelope=self.registry,
            trust=_ring(),
            now=NOW,
            transaction_id="f" * 32,
        )
        self.prepared = serialize_prepared_record(record)

    def verify(self, **changes: Any):
        inputs: dict[str, Any] = {
            "prepared_record": self.prepared,
            "registry_envelope": self.registry,
            "lock_envelope": self.lock,
            "module_envelopes": {"quillan": self.release},
            "trust": _ring(),
            "now": NOW,
        }
        inputs.update(changes)
        return verify_publisher_bound_composition(self.directory, **inputs)


def test_valid_root_and_publisher_signed_composition(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    verified = scene.verify()
    assert verified.transaction_id == "f" * 32
    assert len(verified.authorized_modules) == 1
    module = verified.authorized_modules[0]
    assert module.component_id == "quillan"
    assert module.console_script == "quillan"
    assert module.version == "0.10.7"
    assert verified.external_distributions == ("pds-core",)
    assert not hasattr(verified, "can_launch")
    assert not hasattr(verified, "installed")


def test_absent_publisher_signature_not_substituted_by_root_lock(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    with pytest.raises(PublisherCompositionError, match="missing or unexpected"):
        scene.verify(module_envelopes={})


def test_unexpected_or_misnamed_envelope_fails(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    for value in (
        {"quillan": scene.release, "unexpected": scene.release},
        {"pds-quillan": scene.release},
        {"Quillan": scene.release},
    ):
        with pytest.raises(PublisherCompositionError, match="missing or unexpected"):
            scene.verify(module_envelopes=value)


@pytest.mark.parametrize(
    "bad_value",
    [None, [], {"quillan": "not bytes"}, {42: b"broken"}],
)
def test_reject_untyped_envelope_mapping(tmp_path: Path, bad_value: Any) -> None:
    scene = Scene(tmp_path)
    with pytest.raises(PublisherCompositionError, match="invalid publisher"):
        scene.verify(module_envelopes=bad_value)


def test_wrong_or_undelegated_signer_rejected(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    payload = json.loads(scene.release)
    wrong = _signed(_module(), "root-primary")
    with pytest.raises(PublisherCompositionError, match="delegated"):
        scene.verify(module_envelopes={"quillan": wrong})
    payload["signatures"][0]["key_id"] = "root-primary"
    with pytest.raises(PublisherCompositionError, match="delegated"):
        scene.verify(module_envelopes={"quillan": _encode(payload)})


def test_root_signed_lock_does_not_override_publisher_hash(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    release = _module()
    release["releases"][0]["sha256"] = "a" * 64
    with pytest.raises(PublisherCompositionError, match="delegated"):
        scene.verify(module_envelopes={"quillan": _signed(release, "quillan-primary")})


def test_explicit_revocation_blocks_wheel(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    release = _module()
    release["releases"][0]["sha256"] = hashlib.sha256(
        scene.wheel.read_bytes()
    ).hexdigest()
    release["releases"][0]["revoked"] = True
    with pytest.raises(PublisherCompositionError, match="delegated"):
        scene.verify(module_envelopes={"quillan": _signed(release, "quillan-primary")})


def test_publisher_expiration_fails_closed(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    release = _module()
    release["releases"][0]["sha256"] = hashlib.sha256(
        scene.wheel.read_bytes()
    ).hexdigest()
    release["expires_at"] = "2026-10-17T16:00:01Z"
    with pytest.raises(PublisherCompositionError, match="delegated"):
        scene.verify(module_envelopes={"quillan": _signed(release, "quillan-primary")})


def test_changed_wheel_rejected_even_if_signed_module_metadata_is_valid(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    scene.wheel.write_bytes(scene.wheel.read_bytes() + b"tampered")
    with pytest.raises(PublisherCompositionError, match="dependency lock"):
        scene.verify()


def test_root_registered_component_identity_not_supplied_by_wheel(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    reg = _registry()
    reg["modules"][0]["component_id"] = "renamed"
    scene.registry = _signed(reg, "root-primary")
    with pytest.raises(PublisherCompositionError, match="dependency lock"):
        scene.verify()


def test_unregistered_root_cannot_be_approved_by_signed_lock_only(
    tmp_path: Path,
) -> None:
    # Independent closed composition containing only an unregistered root.
    # A valid root-signed lock alone must not make it a PDS application.
    root = tmp_path / "unregistered"
    root.mkdir()
    core = _add(root, name="pds-core", version="0.6.6", requirements=())
    claims = _claims((core,))
    claims["roots"] = ["pds-core"]
    registry = _signed(_registry(), "root-primary")
    lock = _signed_lock(claims, "root-primary")
    record = serialize_prepared_record(
        prepare_composition_record(
            root,
            lock_envelope=lock,
            registry_envelope=registry,
            trust=_ring(),
            now=NOW,
            transaction_id="f" * 32,
        )
    )
    with pytest.raises(PublisherCompositionError, match="unregistered"):
        verify_publisher_bound_composition(
            root,
            prepared_record=record,
            registry_envelope=registry,
            lock_envelope=lock,
            module_envelopes={},
            trust=_ring(),
            now=NOW,
        )


def test_registered_transitive_pds_module_requires_its_own_delegation(
    tmp_path: Path,
) -> None:
    root = tmp_path
    quillan_bytes = _wheel_bytes(requirement="pds-portia>=0.2,<0.3")
    quillan_name = "quillan-0.10.7-py3-none-any.whl"
    (root / quillan_name).write_bytes(quillan_bytes)
    quillan = WheelPin(quillan_name, hashlib.sha256(quillan_bytes).hexdigest())
    portia_bytes = _wheel_bytes(
        distribution="pds-portia",
        version="0.2.0",
        console="portia = portia.cli:main",
        member="portia/__init__.py",
    )
    portia_name = "pds_portia-0.2.0-py3-none-any.whl"
    (root / portia_name).write_bytes(portia_bytes)
    portia = WheelPin(portia_name, hashlib.sha256(portia_bytes).hexdigest())
    core = _add(root, name="pds-core", version="0.6.6", requirements=())
    registry = _signed(_registry(), "root-primary")
    claims = _claims((quillan, portia, core))
    claims["roots"] = ["quillan"]
    lock = _signed_lock(claims, "root-primary")
    record = serialize_prepared_record(
        prepare_composition_record(
            root,
            lock_envelope=lock,
            registry_envelope=registry,
            trust=_ring(),
            now=NOW,
            transaction_id="f" * 32,
        )
    )
    quillan_release = _module()
    quillan_release["releases"][0]["sha256"] = quillan.sha256
    quillan_release["releases"][0]["requires_dist"] = ["pds-portia>=0.2,<0.3"]
    portia_release = _module()
    portia_release["component_id"] = "portia"
    portia_release["repository"] = "Paper-Data-Suite/pds-portia"
    portia_release["distribution"] = "pds-portia"
    portia_release["releases"][0].update(
        {
            "version": "0.2.0",
            "tag": "v0.2.0",
            "wheel": portia_name,
            "sha256": portia.sha256,
            "console_script": "portia",
            "console_target": "portia.cli:main",
        }
    )
    module_docs = {
        "quillan": _signed(quillan_release, "quillan-primary"),
        "portia": _signed(portia_release, "portia-primary"),
    }
    params = dict(
        prepared_record=record,
        registry_envelope=registry,
        lock_envelope=lock,
        trust=_ring(),
        now=NOW,
    )
    with pytest.raises(PublisherCompositionError, match="missing or unexpected"):
        verify_publisher_bound_composition(
            root, module_envelopes={"quillan": module_docs["quillan"]}, **params
        )
    result = verify_publisher_bound_composition(
        root, module_envelopes=module_docs, **params
    )
    assert {module.component_id for module in result.authorized_modules} == {
        "quillan",
        "portia",
    }
    assert result.external_distributions == ("pds-core",)


def test_no_execution_or_software_file_mutation(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    scene.verify()
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
