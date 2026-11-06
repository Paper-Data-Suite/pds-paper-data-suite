"""Issue #49 Slice 8: verify staged bytes; never authorize active launching."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest
from test_issue49_slice3_signature_verification import NOW, _ring
from test_issue49_slice6_wheelhouse import _add
from test_issue49_slice7_signed_lock_and_records import (
    _claims,
    _registry_bytes,
    _signed_lock,
)

from paper_data_suite.evergreen_install_records import (
    prepare_composition_record,
    serialize_prepared_record,
)
from paper_data_suite.evergreen_staged_install import (
    StageAuditError,
    audit_staged_site_packages,
)

_TX = "e" * 32


def _make_site(stage: Path, wheelhouse: Path) -> Path:
    site = stage / "site-packages"
    site.mkdir(parents=True)
    for wheel in sorted(wheelhouse.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            contents: dict[str, bytes] = {
                name: archive.read(name)
                for name in archive.namelist()
                if not name.endswith("/")
            }
        record_name = next(
            name for name in contents if name.endswith(".dist-info/RECORD")
        )
        rows: list[tuple[str, str, str]] = []
        for name, data in sorted(contents.items()):
            dest = site.joinpath(*name.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            if name == record_name:
                rows.append((name, "", ""))
                continue
            dest.write_bytes(data)
            digest = hashlib.sha256(data).digest()
            encoded = base64.urlsafe_b64encode(digest).decode().rstrip("=")
            rows.append((name, "sha256=" + encoded, str(len(data))))
        out = io.StringIO(newline="")
        writer = csv.writer(out, lineterminator="\n")
        writer.writerows(rows)
        (site / record_name).write_bytes(out.getvalue().encode("utf-8"))
    return site


def _scene(tmp_path: Path) -> tuple[Path, Path, bytes, bytes, bytes]:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    app = _add(wheelhouse)
    core = _add(
        wheelhouse,
        name="demo-core",
        version="2.4.0",
        requirements=(),
        member="demo_core/__init__.py",
    )
    registry = _registry_bytes()
    lock = _signed_lock(_claims((app, core)), "root-primary")
    stage = tmp_path / "private-stage"
    _make_site(stage, wheelhouse)
    record = prepare_composition_record(
        wheelhouse,
        registry_envelope=registry,
        lock_envelope=lock,
        trust=_ring(),
        now=NOW,
        transaction_id=_TX,
    )
    return stage, wheelhouse, registry, lock, serialize_prepared_record(record)


def _audit(scene: tuple[Path, Path, bytes, bytes, bytes]):
    stage, wheels, registry, lock, record = scene
    return audit_staged_site_packages(
        stage,
        wheels,
        prepared_record=record,
        registry_envelope=registry,
        lock_envelope=lock,
        trust=_ring(),
        now=NOW,
    )


def _installed_record(scene: tuple[Path, Path, bytes, bytes, bytes]) -> Path:
    stage = scene[0] / "site-packages"
    return stage / "demo_app-1.0.0.dist-info" / "RECORD"


def test_exact_installed_files_match_signed_lock_and_prepared_record(
    tmp_path: Path,
) -> None:
    scene = _scene(tmp_path)
    before = {
        item.relative_to(scene[0]): item.read_bytes()
        for item in scene[0].rglob("*")
        if item.is_file()
    }
    result = _audit(scene)
    assert result.transaction_id == _TX
    assert result.distributions == ("demo-app", "demo-core")
    assert result.stage_site == scene[0] / "site-packages"
    assert len(result.files) == 8
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "active")
    after = {
        item.relative_to(scene[0]): item.read_bytes()
        for item in scene[0].rglob("*")
        if item.is_file()
    }
    assert before == after


@pytest.mark.parametrize(
    "path",
    [
        "demo_app/__init__.py",
        "demo_core/__init__.py",
        "demo_app-1.0.0.dist-info/METADATA",
    ],
)
def test_any_changed_installed_payload_fails(tmp_path: Path, path: str) -> None:
    scene = _scene(tmp_path)
    file = scene[0] / "site-packages" / path
    file.write_bytes(file.read_bytes() + b"evil")
    with pytest.raises(StageAuditError, match="staged file bytes"):
        _audit(scene)


def test_missing_installed_file_fails(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene[0] / "site-packages/demo_app/__init__.py").unlink()
    with pytest.raises(StageAuditError, match="file set"):
        _audit(scene)


def test_extra_installed_python_fails(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene[0] / "site-packages/injected.py").write_text("evil")
    with pytest.raises(StageAuditError, match="file set"):
        _audit(scene)


@pytest.mark.parametrize(
    "contents",
    [
        "bad,row\n",
        "../escape.py,sha256=abc,1\n",
        "demo_app/__init__.py,,\n",
        "demo_app/__init__.py,sha1=abc,1\n",
        "demo_app/__init__.py,sha256=abc,1\n",
        "demo_app/__init__.py,sha256=abc,-1\n",
    ],
)
def test_malformed_installed_record_fails(tmp_path: Path, contents: str) -> None:
    scene = _scene(tmp_path)
    _installed_record(scene).write_text(contents)
    with pytest.raises(StageAuditError):
        _audit(scene)


def test_record_hash_mismatch_detected_even_when_installed_bytes_match(
    tmp_path: Path,
) -> None:
    scene = _scene(tmp_path)
    record = _installed_record(scene)
    contents = record.read_text()
    record.write_text(contents.replace("sha256=", "sha256=A", 1))
    with pytest.raises(StageAuditError, match="RECORD"):
        _audit(scene)


def test_record_omitting_package_payload_is_rejected(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    record = _installed_record(scene)
    lines = record.read_text().splitlines(keepends=True)
    record.write_text("".join(x for x in lines if "demo_app/__init__.py" not in x))
    with pytest.raises(StageAuditError, match="RECORD has missing"):
        _audit(scene)


def test_installed_record_cannot_claim_another_distribution_file(
    tmp_path: Path,
) -> None:
    scene = _scene(tmp_path)
    record = _installed_record(scene)
    other_record = next(
        p
        for p in (scene[0] / "site-packages").glob("*.dist-info/RECORD")
        if p != record
    )
    record.write_text(
        record.read_text() + other_record.read_text().splitlines()[0] + "\n"
    )
    with pytest.raises(StageAuditError, match="RECORD"):
        _audit(scene)


def test_mutated_prepared_record_fails_without_stage_changes(tmp_path: Path) -> None:
    stage, wheels, registry, lock, record = _scene(tmp_path)
    forged = record.replace(b"e" * 32, b"f" * 32, 1)
    forged = forged.replace(b'"lock_revision":1', b'"lock_revision":2')
    with pytest.raises(StageAuditError, match="prepared record"):
        _audit((stage, wheels, registry, lock, forged))


def test_modified_signed_wheel_fails_even_with_unchanged_stage(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    artifact = next(scene[1].glob("*.whl"))
    artifact.write_bytes(artifact.read_bytes() + b"corruption")
    with pytest.raises(StageAuditError, match="prepared record"):
        _audit(scene)


def test_unknown_stage_files_do_not_get_trusted_from_a_matching_record(
    tmp_path: Path,
) -> None:
    scene = _scene(tmp_path)
    path = scene[0] / "site-packages/injected.dist-info"
    path.mkdir()
    (path / "METADATA").write_text("Name: evil")
    with pytest.raises(StageAuditError, match="file set"):
        _audit(scene)


def test_broken_isolation_fails_on_stage_symlink(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    site = scene[0] / "site-packages"
    real_file = site / "demo_app/__init__.py"
    link = site / "symlink.py"
    try:
        link.symlink_to(real_file)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(StageAuditError, match="reparse"):
        _audit(scene)


def test_refuse_audit_of_active_python_prefix(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    with pytest.raises(StageAuditError, match="active interpreter"):
        audit_staged_site_packages(
            Path(sys.prefix),
            scene[1],
            prepared_record=scene[4],
            registry_envelope=scene[2],
            lock_envelope=scene[3],
            trust=_ring(),
            now=NOW,
        )


def test_no_stage_site_packages_fails(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene[0] / "site-packages").rename(scene[0] / "removed")
    with pytest.raises(StageAuditError, match="site-packages"):
        _audit(scene)
