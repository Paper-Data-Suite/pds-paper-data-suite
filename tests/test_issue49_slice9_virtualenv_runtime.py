"""Issue #49 Slice 9: read-only isolated venv and wrapper observations."""

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
from paper_data_suite.evergreen_staged_runtime import (
    StagedRuntimeError,
    inspect_staged_virtualenv,
)

WRAPPER = (
    "import re\nimport sys\nfrom demo_app.cli import main\n"
    "if __name__ == '__main__':\n"
    "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
    "    sys.exit(main())\n"
)


def _console_wheel(path: Path) -> None:
    original = io.BytesIO(path.read_bytes())
    target = io.BytesIO()
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(target, "w") as archive:
        for info in source.infolist():
            archive.writestr(info, source.read(info))
        archive.writestr(
            "demo_app-1.0.0.dist-info/entry_points.txt",
            "[console_scripts]\ndemo = demo_app.cli:main\n",
        )
    path.write_bytes(target.getvalue())


def _record_entry(name: str, raw: bytes) -> tuple[str, str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode()
    return (name, "sha256=" + digest.rstrip("="), str(len(raw)))


def _site_from_wheels(site: Path, wheels: Path) -> None:
    site.mkdir(parents=True)
    for wheel in wheels.glob("*.whl"):
        with zipfile.ZipFile(wheel) as archive:
            values = {name: archive.read(name) for name in archive.namelist()}
        record_name = next(name for name in values if name.endswith("/RECORD"))
        rows = []
        for name, raw in sorted(values.items()):
            destination = site / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if name == record_name:
                rows.append((name, "", ""))
            else:
                destination.write_bytes(raw)
                rows.append(_record_entry(name, raw))
        output = io.StringIO(newline="")
        csv.writer(output, lineterminator="\n").writerows(rows)
        (site / record_name).write_text(output.getvalue(), encoding="utf-8")


def _windows_wrapper(script: Path, content: str = WRAPPER) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("__main__.py", content)
    script.write_bytes(
        b"MZ" + b"synthetic-not-authentic-executable" + stream.getvalue()
    )


def _scene(
    tmp_path: Path, *, layout: str = "windows"
) -> tuple[Path, Path, bytes, bytes, bytes, str]:
    wheels = tmp_path / "wheelhouse"
    wheels.mkdir()
    app = _add(wheels, requirements=("demo-core>=2,<3",))
    _console_wheel(wheels / app.filename)
    app_bytes = (wheels / app.filename).read_bytes()
    app = type(app)(app.filename, hashlib.sha256(app_bytes).hexdigest())
    core = _add(
        wheels,
        name="demo-core",
        version="2.4.0",
        requirements=(),
        member="demo_core/__init__.py",
    )
    registry = _registry_bytes()
    lock = _signed_lock(_claims((app, core)), "root-primary")
    prepared = prepare_composition_record(
        wheels,
        lock_envelope=lock,
        registry_envelope=registry,
        trust=_ring(),
        now=NOW,
        transaction_id="f" * 32,
    )
    stage = tmp_path / "private-stage"
    stage.mkdir()
    (stage / "pyvenv.cfg").write_text(
        "home = C:/Installed/Python\ninclude-system-site-packages = false\n",
        encoding="utf-8",
    )
    windows = layout == "windows"
    site = stage / (
        "Lib/site-packages"
        if windows
        else (
            f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
        )
    )
    scripts = stage / ("Scripts" if windows else "bin")
    scripts.mkdir(parents=True)
    (scripts / ("python.exe" if windows else "python")).write_bytes(b"synthetic")
    _site_from_wheels(site, wheels)
    script = scripts / ("demo.exe" if windows else "demo")
    if windows:
        _windows_wrapper(script)
    else:
        script.write_text("#!/staged/python\n" + WRAPPER, encoding="utf-8")
    return stage, wheels, registry, lock, serialize_prepared_record(prepared), layout


def _inspect(scene: tuple[Path, Path, bytes, bytes, bytes, str]):
    stage, wheels, registry, lock, prepared, layout = scene
    return inspect_staged_virtualenv(
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
def test_staged_venv_observes_owned_console_without_claiming_trust(
    tmp_path: Path, layout: str
) -> None:
    scene = _scene(tmp_path, layout=layout)
    before = {
        p.relative_to(scene[0]): p.read_bytes()
        for p in scene[0].rglob("*")
        if p.is_file()
    }
    result = _inspect(scene)
    after = {
        p.relative_to(scene[0]): p.read_bytes()
        for p in scene[0].rglob("*")
        if p.is_file()
    }
    assert result.distributions == ("demo-app", "demo-core")
    assert len(result.console_launchers) == 1
    assert result.console_launchers[0].target == "demo_app.cli:main"
    assert result.console_launchers[0].name == "demo"
    assert result.native_executables_authenticated is False
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "active_install")
    assert before == after


def test_modified_staged_distribution_metadata_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    file = scene[0] / "Lib/site-packages/demo_app-1.0.0.dist-info/METADATA"
    file.write_bytes(file.read_bytes() + b"Name: bad\n")
    with pytest.raises(StagedRuntimeError, match="metadata differs"):
        _inspect(scene)


def test_missing_installed_distribution_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    file = scene[0] / "Lib/site-packages/demo_core-2.4.0.dist-info"
    file.rename(file.with_name("missing"))
    with pytest.raises(StagedRuntimeError, match="inventory"):
        _inspect(scene)


def test_injected_foreign_distribution_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene[0] / "Lib/site-packages/rogue-0.1.0.dist-info").mkdir()
    with pytest.raises(StagedRuntimeError, match="inventory"):
        _inspect(scene)


@pytest.mark.parametrize("filename", ["bad.pth", "sitecustomize.py", "rogue.egg-link"])
def test_staged_startup_injection_refused(tmp_path: Path, filename: str) -> None:
    scene = _scene(tmp_path)
    (scene[0] / "Lib/site-packages" / filename).write_text("import evil")
    with pytest.raises(StagedRuntimeError, match="startup injection"):
        _inspect(scene)


def test_virtualenv_inheriting_system_packages_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene[0] / "pyvenv.cfg").write_text("include-system-site-packages = true")
    with pytest.raises(StagedRuntimeError, match="system packages"):
        _inspect(scene)


def test_duplicate_virtualenv_configuration_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    with (scene[0] / "pyvenv.cfg").open("a") as handle:
        handle.write("include-system-site-packages = false\n")
    with pytest.raises(StagedRuntimeError, match="duplicate"):
        _inspect(scene)


def test_missing_expected_launcher_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene[0] / "Scripts/demo.exe").unlink()
    with pytest.raises(StagedRuntimeError, match="missing staged path"):
        _inspect(scene)


def test_different_imported_launcher_target_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    _windows_wrapper(
        scene[0] / "Scripts/demo.exe", WRAPPER.replace("demo_app.cli", "evil.cli")
    )
    with pytest.raises(StagedRuntimeError, match="console wrapper"):
        _inspect(scene)


def test_extra_python_code_in_wrapper_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    _windows_wrapper(scene[0] / "Scripts/demo.exe", WRAPPER + "print('evil')\n")
    with pytest.raises(StagedRuntimeError, match="console wrapper"):
        _inspect(scene)


def test_unknown_binary_embedded_zip_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene[0] / "Scripts/demo.exe").write_bytes(b"MZbutnotazip")
    with pytest.raises(StagedRuntimeError, match="embedded ZIP"):
        _inspect(scene)


def test_missing_native_exe_header_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    path = scene[0] / "Scripts/demo.exe"
    path.write_bytes(b"notpe" + path.read_bytes()[2:])
    with pytest.raises(StagedRuntimeError, match="MZ header"):
        _inspect(scene)


def test_installed_record_forgery_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    record = scene[0] / "Lib/site-packages/demo_app-1.0.0.dist-info/RECORD"
    record.write_text(record.read_text().replace("sha256=", "sha256=bad", 1))
    with pytest.raises(StagedRuntimeError, match="RECORD differs"):
        _inspect(scene)


def test_replacing_authenticated_wheel_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    wheel = next(scene[1].glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"tamper")
    with pytest.raises(StagedRuntimeError, match="provenance"):
        _inspect(scene)


def test_tampered_prepared_record_refused(tmp_path: Path) -> None:
    stage, wheels, registry, lock, prepared, layout = _scene(tmp_path)
    forged = prepared.replace(b'"lock_revision":1', b'"lock_revision":7')
    with pytest.raises(StagedRuntimeError, match="provenance"):
        _inspect((stage, wheels, registry, lock, forged, layout))


def test_running_interpreter_cannot_be_stage(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    with pytest.raises(StagedRuntimeError, match="running interpreter"):
        inspect_staged_virtualenv(
            Path(sys.prefix),
            scene[1],
            prepared_record=scene[4],
            registry_envelope=scene[2],
            lock_envelope=scene[3],
            trust=_ring(),
            now=NOW,
        )


def test_symbolic_script_refused_where_supported(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    script = scene[0] / "Scripts/demo.exe"
    dest = scene[0] / "actual.exe"
    script.rename(dest)
    try:
        script.symlink_to(dest)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(StagedRuntimeError, match="reparse"):
        _inspect(scene)


def test_unowned_executable_in_scripts_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    (scene[0] / "Scripts/rogue.exe").write_bytes(b"MZ-malicious")
    with pytest.raises(StagedRuntimeError, match="unowned"):
        _inspect(scene)


def test_intermediate_symlinked_site_directory_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    root = scene[0]
    target = root / "real-lib"
    try:
        (root / "Lib").rename(target)
        (root / "Lib").symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(StagedRuntimeError, match="reparse"):
        _inspect(scene)
