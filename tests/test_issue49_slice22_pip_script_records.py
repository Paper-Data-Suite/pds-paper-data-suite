"""Issue #49 Slice 22: pip RECORD paths for exact owned console wrappers."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from test_issue49_slice3_signature_verification import NOW, _ring
from test_issue49_slice9_virtualenv_runtime import _record_entry
from test_issue49_slice21_pip_layout import _audit, _pip_scene, _site

from paper_data_suite.evergreen_pip_layout_audit import (
    PipLayoutError,
    audit_staged_pip_layout,
)
from paper_data_suite.evergreen_pip_script_records import (
    PipScriptRecordError,
    split_pip_record,
)


def _script(scene: tuple[Path, Path, bytes, bytes, bytes, str]) -> tuple[str, Path]:
    root, _, _, _, _, layout = scene
    if layout == "windows":
        return "../../Scripts/demo.exe", root / "Scripts/demo.exe"
    return "../../../bin/demo", root / "bin/demo"


def _record(scene: tuple[Path, Path, bytes, bytes, bytes, str]) -> Path:
    return _site(scene) / "demo_app-1.0.0.dist-info/RECORD"


def _rows(record: Path) -> list[list[str]]:
    with record.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.reader(stream))


def _write(record: Path, rows: list[list[str]]) -> None:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    record.write_bytes(buffer.getvalue().encode("utf-8"))


def _add_script_record(
    scene: tuple[Path, Path, bytes, bytes, bytes, str],
) -> None:
    name, path = _script(scene)
    record = _record(scene)
    _write(record, _rows(record) + [list(_record_entry(name, path.read_bytes()))])


def _audit_strict(scene: tuple[Path, Path, bytes, bytes, bytes, str]):
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
        require_launcher_records=True,
    )


@pytest.mark.parametrize("layout", ["windows", "posix"])
def test_pip_launcher_record_is_authenticated_against_inspected_wrapper(
    tmp_path: Path, layout: str
) -> None:
    scene = _pip_scene(tmp_path, layout=layout)
    _add_script_record(scene)
    before = _script(scene)[1].read_bytes()
    output = _audit_strict(scene)
    assert output.transaction_id == "f" * 32
    assert len(output.inventory_sha256) == 64
    assert _script(scene)[1].read_bytes() == before
    assert len(output.launcher_records) == 1
    assert output.launcher_records[0].relative_path == _script(scene)[0]
    assert not hasattr(output, "can_launch")


@pytest.mark.parametrize("layout", ["windows", "posix"])
def test_strict_pip_qualification_rejects_missing_owned_launcher_record(
    tmp_path: Path, layout: str
) -> None:
    scene = _pip_scene(tmp_path, layout=layout)
    _audit(scene)  # Legacy synthetic fixture accepted by the old observation.
    with pytest.raises(PipLayoutError, match="required launcher RECORD"):
        _audit_strict(scene)


def test_launcher_record_hash_mismatch_rejected_even_if_site_record_valid(
    tmp_path: Path,
) -> None:
    scene = _pip_scene(tmp_path)
    _add_script_record(scene)
    record = _record(scene)
    rows = _rows(record)
    rows[-1][1] = "sha256=" + "A" * 43
    _write(record, rows)
    with pytest.raises(PipLayoutError, match="console RECORD digest"):
        _audit_strict(scene)


def test_launcher_record_size_mismatch_rejected(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    _add_script_record(scene)
    record = _record(scene)
    rows = _rows(record)
    rows[-1][2] = str(int(rows[-1][2]) + 1)
    _write(record, rows)
    with pytest.raises(PipLayoutError, match="console RECORD digest"):
        _audit_strict(scene)


def test_wrong_owner_claiming_another_wheels_launcher_fails(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    name, path = _script(scene)
    other = _site(scene) / "demo_core-2.4.0.dist-info/RECORD"
    _write(other, _rows(other) + [list(_record_entry(name, path.read_bytes()))])
    with pytest.raises(PipLayoutError, match="launcher RECORD"):
        _audit_strict(scene)


@pytest.mark.parametrize(
    "path",
    [
        "../../../Scripts/demo.exe",
        "../../Scripts/other.exe",
        "../../Scripts/demo-script.py",
        "../../Scripts/DEMO.exe",
        "../../Scripts/../Secrets.txt",
        "../Scripts/demo.exe",
        "C:/Python/Scripts/demo.exe",
        "..\\..\\Scripts\\demo.exe",
        "../../Scripts/demo.exe/../../evil",
    ],
)
def test_unapproved_script_paths_never_escape_site_inventory(
    tmp_path: Path, path: str
) -> None:
    scene = _pip_scene(tmp_path)
    _, script = _script(scene)
    record = _record(scene)
    _write(record, _rows(record) + [list(_record_entry(path, script.read_bytes()))])
    with pytest.raises(PipLayoutError, match="launcher RECORD"):
        _audit_strict(scene)


def test_duplicate_script_rows_rejected(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    _add_script_record(scene)
    record = _record(scene)
    rows = _rows(record)
    _write(record, rows + [rows[-1]])
    with pytest.raises(PipLayoutError, match="launcher RECORD"):
        _audit_strict(scene)


def test_unsigned_script_row_rejected(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    _add_script_record(scene)
    record = _record(scene)
    rows = _rows(record)
    rows[-1][1:] = ["", ""]
    _write(record, rows)
    with pytest.raises(PipLayoutError, match="launcher RECORD"):
        _audit_strict(scene)


def test_partial_script_records_fail_closed(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    _add_script_record(scene)
    # The scene has exactly one public script. Adding a foreign name is rejected.
    record = _record(scene)
    _write(record, _rows(record) + [["../../Scripts/nope.exe", "", ""]])
    with pytest.raises(PipLayoutError, match="launcher RECORD"):
        _audit_strict(scene)


def test_parser_requires_explicit_script_allowlist() -> None:
    row = (
        b"../../Scripts/demo.exe,"
        b"sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,12\n"
    )
    with pytest.raises(PipScriptRecordError):
        split_pip_record(row, allowed_scripts=frozenset())
    parsed, scripts = split_pip_record(
        row, allowed_scripts=frozenset({"../../Scripts/demo.exe"})
    )
    assert parsed == {}
    assert scripts["../../Scripts/demo.exe"][1] == 12


def test_parser_rejects_unknown_duplicate_and_bad_script_fields() -> None:
    name = "../../Scripts/demo.exe"
    good = b"sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,12\n"
    with pytest.raises(PipScriptRecordError, match="duplicate"):
        split_pip_record(
            (name + ",").encode() + good + (name + ",").encode() + good,
            allowed_scripts=frozenset({name}),
        )
    for invalid in (b",12\n", b"sha256=bad,12\n", b"sha256=AAA,-1\n"):
        with pytest.raises(PipScriptRecordError):
            split_pip_record(
                (name + ",").encode() + invalid,
                allowed_scripts=frozenset({name}),
            )


def test_site_record_tampering_still_refused(tmp_path: Path) -> None:
    scene = _pip_scene(tmp_path)
    _add_script_record(scene)
    source = _site(scene) / "demo_app/__init__.py"
    source.write_bytes(b"not the signed source\n")
    with pytest.raises(PipLayoutError, match="installed file differs"):
        _audit_strict(scene)
