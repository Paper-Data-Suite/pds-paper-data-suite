"""Issue #49 Slice 23: genuine offline pip stage and locked PEP 610 provenance."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import subprocess
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
from test_issue49_slice9_virtualenv_runtime import (
    _console_wheel,
    _record_entry,
)

from paper_data_suite.evergreen_install_records import (
    prepare_composition_record,
    serialize_prepared_record,
)
from paper_data_suite.evergreen_pip_direct_url import (
    PipDirectUrlError,
    inspect_locked_pip_direct_url,
)
from paper_data_suite.evergreen_pip_layout_audit import (
    PipLayoutError,
    audit_staged_pip_layout,
)
from paper_data_suite.evergreen_wheelhouse import WheelPin


def _valid_wheel_record(path: Path) -> WheelPin:
    """Build standard wheel RECORD hashes unlike earlier metadata-only fixtures."""
    with zipfile.ZipFile(path) as archive:
        members = {
            item.filename: archive.read(item)
            for item in archive.infolist()
            if not item.is_dir()
        }
    record_paths = [name for name in members if name.endswith(".dist-info/RECORD")]
    assert len(record_paths) == 1
    record = record_paths[0]
    content = io.StringIO(newline="")
    writer = csv.writer(content, lineterminator="\n")
    for name, raw in sorted(members.items()):
        writer.writerow((name, "", "") if name == record else _record_entry(name, raw))
    members[record] = content.getvalue().encode("utf-8")
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    raw_wheel = target.getvalue()
    path.write_bytes(raw_wheel)
    return WheelPin(path.name, hashlib.sha256(raw_wheel).hexdigest())


def _signed_wheels(tmp_path: Path) -> tuple[Path, bytes, bytes, bytes]:
    wheels = tmp_path / "signed-wheelhouse"
    wheels.mkdir()
    app = _add(wheels)
    _console_wheel(wheels / app.filename)
    app = _valid_wheel_record(wheels / app.filename)
    core = _add(
        wheels,
        name="demo-core",
        version="2.4.0",
        requirements=(),
        member="demo_core/__init__.py",
    )
    core = _valid_wheel_record(wheels / core.filename)
    registry = _registry_bytes()
    lock = _signed_lock(_claims((app, core)), "root-primary")
    prepared = prepare_composition_record(
        wheels,
        lock_envelope=lock,
        registry_envelope=registry,
        trust=_ring(),
        now=NOW,
        transaction_id="e" * 32,
    )
    return wheels, registry, lock, serialize_prepared_record(prepared)


def _site(root: Path) -> Path:
    if os.name == "nt":
        return root / "Lib/site-packages"
    return root / (
        f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )


def _audit(root: Path, wheels: Path, registry: bytes, lock: bytes, prepared: bytes):
    return audit_staged_pip_layout(
        root,
        wheels,
        prepared_record=prepared,
        registry_envelope=registry,
        lock_envelope=lock,
        trust=_ring(),
        now=NOW,
        require_launcher_records=True,
    )


def _run(*args: str, timeout: int = 45) -> None:
    result = subprocess.run(
        list(args),
        capture_output=True,
        check=False,
        timeout=timeout,
        env={
            **os.environ,
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        },
    )
    assert result.returncode == 0, (
        "offline real-pip fixture installation failed (redacted): "
        + str(result.returncode)
    )


@pytest.fixture
def real_pip_stage(tmp_path: Path) -> tuple[Path, Path, bytes, bytes, bytes]:
    wheels, registry, lock, prepared = _signed_wheels(tmp_path)
    root = tmp_path / "private-staged-venv"
    _run(sys.executable, "-m", "venv", "--copies", "--without-pip", str(root))
    _run(
        sys.executable,
        "-m",
        "pip",
        "--python",
        str(root),
        "install",
        "--no-index",
        "--no-deps",
        "--no-compile",
        "--no-cache-dir",
        *(str(wheel) for wheel in sorted(wheels.glob("*.whl"))),
    )
    return root, wheels, registry, lock, prepared


def test_genuine_offline_pip_venv_matches_signed_wheels_and_launcher_records(
    real_pip_stage: tuple[Path, Path, bytes, bytes, bytes],
) -> None:
    root, wheels, registry, lock, prepared = real_pip_stage
    inspected = _audit(root, wheels, registry, lock, prepared)
    assert inspected.transaction_id == "e" * 32
    assert inspected.distributions == ("demo-app", "demo-core")
    assert len(inspected.launcher_records) == 1
    assert len(inspected.generated_metadata) >= 2
    assert any(
        name.endswith("/direct_url.json") for name in inspected.generated_metadata
    )
    assert not hasattr(inspected, "can_launch")


def test_real_pip_direct_url_changed_to_remote_is_rejected(
    real_pip_stage: tuple[Path, Path, bytes, bytes, bytes],
) -> None:
    root, wheels, registry, lock, prepared = real_pip_stage
    direct = _site(root) / "demo_app-1.0.0.dist-info/direct_url.json"
    info = json.loads(direct.read_bytes())
    info["url"] = "https://example.invalid/untrusted.whl"
    direct.write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises(PipLayoutError, match="preflight"):
        _audit(root, wheels, registry, lock, prepared)


def test_real_pip_direct_url_changed_to_other_local_wheel_is_rejected(
    real_pip_stage: tuple[Path, Path, bytes, bytes, bytes],
) -> None:
    root, wheels, registry, lock, prepared = real_pip_stage
    direct = _site(root) / "demo_app-1.0.0.dist-info/direct_url.json"
    info = json.loads(direct.read_bytes())
    info["url"] = (wheels / "demo_core-2.4.0-py3-none-any.whl").as_uri()
    direct.write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises(PipLayoutError, match="preflight"):
        _audit(root, wheels, registry, lock, prepared)


def test_real_pip_direct_url_absent_but_record_not_rewritten_fails(
    real_pip_stage: tuple[Path, Path, bytes, bytes, bytes],
) -> None:
    root, wheels, registry, lock, prepared = real_pip_stage
    (_site(root) / "demo_app-1.0.0.dist-info/direct_url.json").unlink()
    with pytest.raises(PipLayoutError, match="RECORD"):
        _audit(root, wheels, registry, lock, prepared)


def test_real_pip_generated_launcher_tamper_fails_strict_audit(
    real_pip_stage: tuple[Path, Path, bytes, bytes, bytes],
) -> None:
    root, wheels, registry, lock, prepared = real_pip_stage
    script = root / ("Scripts/demo.exe" if os.name == "nt" else "bin/demo")
    script.write_bytes(script.read_bytes() + b"tampered")
    with pytest.raises(PipLayoutError):
        _audit(root, wheels, registry, lock, prepared)


def test_real_pip_installed_package_change_fails_audit(
    real_pip_stage: tuple[Path, Path, bytes, bytes, bytes],
) -> None:
    root, wheels, registry, lock, prepared = real_pip_stage
    source = _site(root) / "demo_app/__init__.py"
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(PipLayoutError):
        _audit(root, wheels, registry, lock, prepared)


@pytest.mark.parametrize("field", ["url", "hash", "hashes", "keys", "duplicate"])
def test_direct_url_parser_rejects_invalid_or_unbounded_origin(
    tmp_path: Path, field: str
) -> None:
    wheel = tmp_path / "signed.whl"
    sha = "a" * 64
    info: dict[str, object] = {
        "url": wheel.absolute().as_uri(),
        "archive_info": {"hash": f"sha256={sha}", "hashes": {"sha256": sha}},
    }
    if field == "url":
        info["url"] = "file:///other.wheel"
    elif field == "hash":
        info["archive_info"] = {"hash": "sha256=" + "b" * 64, "hashes": {"sha256": sha}}
    elif field == "hashes":
        info["archive_info"] = {"hash": f"sha256={sha}", "hashes": {"sha256": "b" * 64}}
    elif field == "keys":
        info["editable"] = True
    raw = json.dumps(info).encode("utf-8")
    if field == "duplicate":
        raw = raw.replace(b'"url":', b'"url":"file:///duplicate", "url":')
    with pytest.raises(PipDirectUrlError):
        inspect_locked_pip_direct_url(raw, wheel_path=wheel, wheel_sha256=sha)


def test_local_wheel_direct_url_parser_does_not_access_wheel(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "signed.whl"
    sha = "a" * 64
    raw = json.dumps(
        {
            "url": wheel.absolute().as_uri(),
            "archive_info": {"hash": f"sha256={sha}", "hashes": {"sha256": sha}},
        }
    ).encode("utf-8")
    digest, length = inspect_locked_pip_direct_url(
        raw, wheel_path=wheel, wheel_sha256=sha
    )
    assert digest == hashlib.sha256(raw).hexdigest()
    assert length == len(raw)
    assert not wheel.exists()  # Parsing did not open or retrieve the wheel.
