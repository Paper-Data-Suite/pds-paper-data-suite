"""Issue #49 Slice 21: exact pip-style wheel relocation and RECORD audit."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from test_issue49_slice3_signature_verification import NOW, _ring
from test_issue49_slice7_signed_lock_and_records import (
    _claims,
    _signed_lock,
)
from test_issue49_slice9_virtualenv_runtime import (
    _record_entry,
    _scene,
)

from paper_data_suite.evergreen_install_records import (
    prepare_composition_record,
    serialize_prepared_record,
)
from paper_data_suite.evergreen_pip_layout_audit import (
    PipLayoutError,
    audit_staged_pip_layout,
)
from paper_data_suite.evergreen_wheelhouse import WheelPin


def _site(scene: tuple[Path, Path, bytes, bytes, bytes, str]) -> Path:
    root, _, _, _, _, layout = scene
    if layout == "windows":
        return root / "Lib/site-packages"
    import sys

    return root / (
        f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )


def _rewrite_records(site: Path) -> None:
    import csv

    for folder in sorted(site.glob("*.dist-info")):
        record = folder / "RECORD"
        all_paths = sorted(
            (p for p in site.rglob("*") if p.is_file() and p != record),
            key=lambda p: p.as_posix(),
        )
        own_names = {p.relative_to(site).as_posix() for p in all_paths}
        # Test fixture has two distributions: partition each file by the
        # installed RECORD's original ownership, rather than all file names.
        initial = {row.split(",", 1)[0] for row in record.read_text().splitlines()}
        owned = (
            initial
            | {
                f"{folder.name}/INSTALLER",
                f"{folder.name}/REQUESTED",
            }
        ) & own_names
        import io as _io

        content = _io.StringIO(newline="")
        writer = csv.writer(content, lineterminator="\n")
        for name in sorted(owned | {f"{folder.name}/RECORD"}):
            if name == f"{folder.name}/RECORD":
                writer.writerow((name, "", ""))
            else:
                writer.writerow(_record_entry(name, (site / name).read_bytes()))
        record.write_text(content.getvalue(), encoding="utf-8")


def _pip_scene(
    tmp_path: Path,
    *,
    layout: str = "windows",
    scheme: str | None = None,
) -> tuple[Path, Path, bytes, bytes, bytes, str]:
    scene = _scene(tmp_path, layout=layout)
    stage, wheels, registry, lock, prepared, _ = scene
    site = _site(scene)
    if scheme is not None:
        first = next(wheels.glob("demo_app-*.whl"))
        original = io.BytesIO(first.read_bytes())
        rewritten = io.BytesIO()
        with (
            zipfile.ZipFile(original) as archive,
            zipfile.ZipFile(rewritten, "w", zipfile.ZIP_DEFLATED) as output,
        ):
            for info in archive.infolist():
                output.writestr(info, archive.read(info))
            output.writestr(
                f"demo_app-1.0.0.data/{scheme}/demo_app/extra.py",
                b"verified relocated source\n",
            )
        first.write_bytes(rewritten.getvalue())
        pins = tuple(
            WheelPin(p.name, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(wheels.glob("*.whl"))
        )
        lock = _signed_lock(_claims(pins), "root-primary")
        prepared = serialize_prepared_record(
            prepare_composition_record(
                wheels,
                lock_envelope=lock,
                registry_envelope=registry,
                trust=_ring(),
                now=NOW,
                transaction_id="f" * 32,
            )
        )
        if scheme in {"purelib", "platlib"}:
            (site / "demo_app/extra.py").write_bytes(b"verified relocated source\n")
    for folder in site.glob("*.dist-info"):
        (folder / "INSTALLER").write_bytes(b"pip\n")
        (folder / "REQUESTED").write_bytes(b"")
    _rewrite_records(site)
    return stage, wheels, registry, lock, prepared, layout


def _audit(scene: tuple[Path, Path, bytes, bytes, bytes, str]):
    stage, wheels, registry, lock, prepared, layout = scene
    return audit_staged_pip_layout(
        stage,
        wheels,
        prepared_record=prepared,
        registry_envelope=registry,
        lock_envelope=lock,
        trust=_ring(),
        now=NOW,
        layout=layout,
    )


@pytest.mark.parametrize("layout", ["windows", "posix"])
def test_pip_generated_installer_metadata_with_rewritten_record(
    tmp_path: Path, layout: str
) -> None:
    scene = _pip_scene(tmp_path, layout=layout)
    output = _audit(scene)
    assert output.transaction_id == "f" * 32
    assert len(output.inventory_sha256) == 64
    assert len(output.generated_metadata) == 4
    assert not output.relocated_files
    assert not hasattr(output, "can_launch")
    assert not hasattr(output, "activate")


@pytest.mark.parametrize("scheme", ["purelib", "platlib"])
def test_signed_data_relocations_are_supported(tmp_path: Path, scheme: str) -> None:
    scene = _pip_scene(tmp_path, scheme=scheme)
    # Reconstruct the pip rewritten RECORD for the one relocated file.
    site = _site(scene)
    record = site / "demo_app-1.0.0.dist-info/RECORD"
    record.write_text(
        record.read_text()
        + ",".join(
            _record_entry(
                "demo_app/extra.py", (site / "demo_app/extra.py").read_bytes()
            )
        )
        + "\n",
        encoding="utf-8",
    )
    output = _audit(scene)
    assert output.relocated_files == ("demo_app/extra.py",)


@pytest.mark.parametrize("scheme", ["scripts", "data", "headers", "nonsense"])
def test_unsupported_data_schemes_fail_closed(tmp_path: Path, scheme: str) -> None:
    scene = _pip_scene(tmp_path, scheme=scheme)
    with pytest.raises(PipLayoutError, match="unsupported wheel .data"):
        _audit(scene)


def test_installed_python_source_change_fails_even_if_record_updated(
    tmp_path: Path,
) -> None:
    scene = _pip_scene(tmp_path)
    site = _site(scene)
    source = site / "demo_app/__init__.py"
    source.write_bytes(b"malicious changed code\n")
    _rewrite_records(site)
    with pytest.raises(PipLayoutError, match="installed file differs"):
        _audit(scene)


@pytest.mark.parametrize(
    "filename", ["unknown.py", "startup.pth", "__pycache__/bad.pyc"]
)
def test_unowned_installed_files_fail_closed(tmp_path: Path, filename: str) -> None:
    scene = _pip_scene(tmp_path)
    destination = _site(scene) / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"unexpected")
    with pytest.raises(PipLayoutError, match="unexpected|preflight"):
        _audit(scene)


def test_bad_installer_fails_even_if_record_updated(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    site = _site(scene)
    (site / "demo_app-1.0.0.dist-info/INSTALLER").write_bytes(b"unknown\n")
    _rewrite_records(site)
    with pytest.raises(PipLayoutError, match="installed file differs"):
        _audit(scene)


def test_bad_requested_fails_even_if_record_updated(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    site = _site(scene)
    (site / "demo_core-2.4.0.dist-info/REQUESTED").write_bytes(b"x")
    _rewrite_records(site)
    with pytest.raises(PipLayoutError, match="installed file differs"):
        _audit(scene)


def test_record_omitting_generated_file_fails(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    site = _site(scene)
    record = site / "demo_app-1.0.0.dist-info/RECORD"
    record.write_text(
        "\n".join(
            row for row in record.read_text().splitlines() if "INSTALLER" not in row
        )
        + "\n"
    )
    with pytest.raises(PipLayoutError, match="RECORD"):
        _audit(scene)


def test_extra_foreign_record_entry_fails(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    site = _site(scene)
    record = site / "demo_app-1.0.0.dist-info/RECORD"
    record.write_bytes(record.read_bytes() + b"foreign.py,,\n")
    with pytest.raises(PipLayoutError, match="RECORD|preflight"):
        _audit(scene)


def test_missing_installed_wheel_file_fails(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    (_site(scene) / "demo_app/__init__.py").unlink()
    with pytest.raises(PipLayoutError, match="incomplete"):
        _audit(scene)


def test_changed_source_wheel_fails(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    wheel = next(scene[1].glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"tamper")
    with pytest.raises(PipLayoutError, match="preflight|wheel"):
        _audit(scene)


def test_unsafe_site_symlink_fails_where_supported(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    site = _site(scene)
    original = site / "demo_app/__init__.py"
    moved = site / "demo_app/ordinary.py"
    original.rename(moved)
    try:
        original.symlink_to(moved)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(PipLayoutError, match="preflight"):
        _audit(scene)


def test_absent_optional_installer_metadata_is_allowed(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    site = _site(scene)
    # Regenerate the fixture RECORD, omitting optional pip files entirely.
    for folder in site.glob("*.dist-info"):
        (folder / "INSTALLER").unlink()
        (folder / "REQUESTED").unlink()
    _rewrite_records(site)
    result = _audit(scene)
    assert result.generated_metadata == ()


def test_does_not_modify_installed_files(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    before = {
        p.relative_to(scene[0]): p.read_bytes()
        for p in scene[0].rglob("*")
        if p.is_file()
    }
    _audit(scene)
    after = {
        p.relative_to(scene[0]): p.read_bytes()
        for p in scene[0].rglob("*")
        if p.is_file()
    }
    assert before == after
