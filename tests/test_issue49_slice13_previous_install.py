"""Issue #49 Slice 13: prior-slot bytes are reverified, never activated."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from test_issue49_slice11_update_journal import Scene

from paper_data_suite.evergreen_activation_slots import (
    UntrustedSlotSelection,
    _selection_bytes,
)
from paper_data_suite.evergreen_previous_install import (
    PreviousInstallationError,
    capture_previous_slot_record,
    observe_previous_slot,
    parse_untrusted_previous_slot_record,
    verify_previous_slot_record,
)


def _scene(tmp_path: Path) -> Scene:
    scene = Scene(tmp_path)
    selection = UntrustedSlotSelection(
        scene.tx,
        scene.stage.relative_to(scene.manager).as_posix(),
        hashlib.sha256(scene.prepared).hexdigest(),
        hashlib.sha256(scene.evidence).hexdigest(),
        2,
    )
    (scene.manager / "candidate-selection.json").write_bytes(
        _selection_bytes(selection)
    )
    return scene


def _kwargs(scene: Scene) -> dict[str, Any]:
    return dict(
        classroom_workspace=scene.workspace,
        wheelhouse=scene.wheels,
        prepared_record=scene.prepared,
        registry_envelope=scene.registry,
        lock_envelope=scene.lock,
        evidence_envelope=scene.evidence,
        trust=scene.inputs()["trust"],
        now=scene.inputs()["now"],
        layout=scene.layout,
    )


def test_previous_stage_signed_bytes_can_be_observed_without_activation(
    tmp_path: Path,
) -> None:
    scene = _scene(tmp_path)
    result = observe_previous_slot(scene.manager, **_kwargs(scene))
    assert result.transaction_id == scene.tx
    assert result.stage_relative_path == scene.stage.name
    assert result.wheelhouse_relative_path == scene.wheels.name
    assert result.selection_generation == 2
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "trusted_installation")


def test_canonical_record_reverifies_sufficient_signed_evidence(
    tmp_path: Path,
) -> None:
    scene = _scene(tmp_path)
    receipt = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    evidence = verify_previous_slot_record(
        receipt,
        scene.manager,
        expected_record_sha256=hashlib.sha256(receipt).hexdigest(),
        **_kwargs(scene),
    )
    assert evidence.record_sha256 == hashlib.sha256(receipt).hexdigest()
    assert evidence.observation == parse_untrusted_previous_slot_record(receipt)
    assert not hasattr(evidence, "can_launch")
    assert not hasattr(evidence, "activated")


def test_no_pointer_means_no_prior_software(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene.manager / "candidate-selection.json").unlink()
    with pytest.raises(PreviousInstallationError, match="no previous"):
        capture_previous_slot_record(scene.manager, **_kwargs(scene))


def test_unauthenticated_prepared_hash_cannot_be_rewritten(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    input_data = _kwargs(scene)
    input_data["prepared_record"] = scene.prepared + b" "
    with pytest.raises(PreviousInstallationError, match="evidence changed"):
        observe_previous_slot(scene.manager, **input_data)


def test_changed_native_binary_prevents_prior_observation(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    previous = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    interpreter = scene.stage / "Scripts/python.exe"
    interpreter.write_bytes(b"X" * interpreter.stat().st_size)
    with pytest.raises(PreviousInstallationError, match="reauthentication"):
        verify_previous_slot_record(previous, scene.manager, **_kwargs(scene))


def test_untrusted_signature_cannot_validate_previous_install(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    blob = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    input_data = _kwargs(scene)
    input_data["evidence_envelope"] = b"{}"
    with pytest.raises(PreviousInstallationError, match="evidence changed"):
        verify_previous_slot_record(blob, scene.manager, **input_data)


def test_changed_previous_selection_generation_fails_receipt(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    record = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    observed = parse_untrusted_previous_slot_record(record)
    pointer = UntrustedSlotSelection(
        observed.transaction_id,
        observed.stage_relative_path,
        observed.prepared_sha256,
        observed.native_envelope_sha256,
        observed.selection_generation + 1,
    )
    (scene.manager / "candidate-selection.json").write_bytes(_selection_bytes(pointer))
    with pytest.raises(PreviousInstallationError, match="record differs"):
        verify_previous_slot_record(record, scene.manager, **_kwargs(scene))


def test_record_hash_from_journal_must_match_exact_bytes(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    record = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    with pytest.raises(PreviousInstallationError, match="expected receipt hash"):
        verify_previous_slot_record(
            record,
            scene.manager,
            expected_record_sha256="0" * 64,
            **_kwargs(scene),
        )


def test_expired_evidence_not_promoted_to_offline_receipt(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    record = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    data = _kwargs(scene)
    data["now"] = data["now"] + timedelta(days=50)
    with pytest.raises(PreviousInstallationError, match="reauthentication"):
        verify_previous_slot_record(record, scene.manager, **data)


def test_pending_switch_marker_blocks_previous_validation(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene.manager / "pending-slot-recovery.json").write_bytes(b"unresolved")
    with pytest.raises(PreviousInstallationError, match="reauthentication"):
        observe_previous_slot(scene.manager, **_kwargs(scene))


def test_previous_wheelhouse_path_change_requires_new_receipt(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    record = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    other = scene.manager / "other"
    other.mkdir()
    for wheel in scene.wheels.iterdir():
        (other / wheel.name).write_bytes(wheel.read_bytes())
    data = _kwargs(scene)
    data["wheelhouse"] = other
    with pytest.raises(PreviousInstallationError, match="record differs"):
        verify_previous_slot_record(record, scene.manager, **data)


def test_no_classroom_workspace_access_or_writes(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    classroom_file = scene.workspace / "private.txt"
    classroom_file.write_bytes(b"never read classroom")
    before = {
        path.relative_to(scene.manager): path.read_bytes()
        for path in scene.manager.rglob("*")
        if path.is_file()
    }
    record = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    verify_previous_slot_record(record, scene.manager, **_kwargs(scene))
    after = {
        path.relative_to(scene.manager): path.read_bytes()
        for path in scene.manager.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert classroom_file.read_bytes() == b"never read classroom"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda doc: doc.update({"phase": "active"}),
        lambda doc: doc.update({"can_launch": True}),
        lambda doc: doc.update({"schema_version": True}),
        lambda doc: doc.update({"native_revision": 0}),
        lambda doc: doc.update({"wheelhouse_relative_path": "../outside"}),
        lambda doc: doc.update({"selection_generation": False}),
        lambda doc: doc.update({"registry_envelope_sha256": "A" * 64}),
    ],
)
def test_local_receipt_mutations_fail_closed(
    tmp_path: Path,
    mutation: Any,
) -> None:
    scene = _scene(tmp_path)
    data = json.loads(capture_previous_slot_record(scene.manager, **_kwargs(scene)))
    mutation(data)
    with pytest.raises(PreviousInstallationError):
        parse_untrusted_previous_slot_record(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        )


def test_duplicate_members_and_noncanonical_json_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    original = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    duplicated = original.replace(
        b'"schema_version":1', b'"schema_version":1,"schema_version":1'
    )
    with pytest.raises(PreviousInstallationError, match="duplicate"):
        parse_untrusted_previous_slot_record(duplicated)
    with pytest.raises(PreviousInstallationError, match="noncanonical"):
        parse_untrusted_previous_slot_record(original + b"\n")


def test_reject_oversized_receipt_without_verification(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    with pytest.raises(PreviousInstallationError, match="length"):
        verify_previous_slot_record(b"x" * 8193, scene.manager, **_kwargs(scene))


def test_previous_root_must_not_overlap_classroom(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    data = _kwargs(scene)
    data["classroom_workspace"] = scene.manager / "transactions"
    with pytest.raises(PreviousInstallationError, match="reauthentication"):
        observe_previous_slot(scene.manager, **data)


def test_outside_wheelhouse_must_not_be_considered_part_of_managed_state(
    tmp_path: Path,
) -> None:
    scene = _scene(tmp_path)
    data = _kwargs(scene)
    data["wheelhouse"] = scene.workspace
    with pytest.raises(PreviousInstallationError, match="reauthentication"):
        observe_previous_slot(scene.manager, **data)


def test_selection_is_untrusted_even_when_signed_bytes_validate(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    original = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    item = json.loads(original)
    assert item["phase"] == "reverified_bytes_not_active_receipt"
    assert "active_at" not in item
    assert "approved_update" not in item
    assert "is_installed" not in item


def test_previous_selection_cannot_be_retargeted_to_other_transaction(
    tmp_path: Path,
) -> None:
    scene = _scene(tmp_path)
    wrong = UntrustedSlotSelection(
        "a" * 32,
        scene.stage.name,
        hashlib.sha256(scene.prepared).hexdigest(),
        hashlib.sha256(scene.evidence).hexdigest(),
        2,
    )
    (scene.manager / "candidate-selection.json").write_bytes(_selection_bytes(wrong))
    with pytest.raises(PreviousInstallationError, match="transaction differs"):
        observe_previous_slot(scene.manager, **_kwargs(scene))


def test_replaced_prior_dependency_wheel_fails_closed(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    record = capture_previous_slot_record(scene.manager, **_kwargs(scene))
    wheel = next(iter(scene.wheels.glob("*.whl")))
    wheel.write_bytes(wheel.read_bytes() + b"modified")
    with pytest.raises(PreviousInstallationError, match="reauthentication"):
        verify_previous_slot_record(record, scene.manager, **_kwargs(scene))


def test_symlinked_previous_stage_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    replacement = scene.manager / "linked-stage"
    try:
        replacement.symlink_to(scene.stage, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    selected = UntrustedSlotSelection(
        scene.tx,
        replacement.name,
        hashlib.sha256(scene.prepared).hexdigest(),
        hashlib.sha256(scene.evidence).hexdigest(),
        2,
    )
    (scene.manager / "candidate-selection.json").write_bytes(_selection_bytes(selected))
    with pytest.raises(PreviousInstallationError, match="reauthentication"):
        observe_previous_slot(scene.manager, **_kwargs(scene))
