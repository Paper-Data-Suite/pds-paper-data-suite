"""Suite #21 B0: explicit selected-context guards; never load producer code.

Fixtures write synthetic Core workspace state BEFORE the read-only preflight.
They do not create attention facts or qualify installed official wheels.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pds_core.classes import ensure_class_folder
from pds_core.school_years import open_school_year
from pds_core.workspace import ensure_workspace_root

from paper_data_suite import module_attention_selection as selection

YEAR = "2026-2027"
OWNER_SET = ("scoreform", "quillan", "concord")


def _workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    root = tmp_path / "synthetic_core_attention"
    ensure_workspace_root(root)
    open_school_year(
        root, YEAR, opened_at=datetime(2026, 9, 8, tzinfo=timezone.utc)
    )
    ensure_class_folder(root, "class_a")
    monkeypatch.setattr(selection, "resolve_workspace_root", lambda: root)
    return root


def _scope(
    root: Path | None, *,
    year: str | None = YEAR,
    class_id: str | None = "class_a",
    owners: tuple[str, ...] = OWNER_SET,
) -> selection.AttentionScopePreflight:
    return selection.prepare_selected_attention_scope(
        workspace_root=root, active_school_year=year,
        class_id=class_id, requested_owners=owners,
    )


def _snapshot(root: Path) -> tuple[tuple[str, str], ...]:
    files: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            files.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
        elif path.is_dir():
            files.append((relative + "/", "directory"))
    return tuple(sorted(files))


def test_explicit_current_selection_has_core_typed_readonly_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    before = _snapshot(root)
    result = _scope(root)
    assert result.scope_validated
    assert result.code == "scope_validated"
    assert result.request is not None
    assert result.request.workspace_root == root
    assert result.request.active_school_year == YEAR
    assert result.request.class_id == "class_a"
    assert result.requested_owners == OWNER_SET
    assert before == _snapshot(root)
    assert not hasattr(result, "profile")
    assert not hasattr(result, "invocation_result")


def test_only_named_owners_in_fixed_suite_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    selected = _scope(root, owners=("concord", "scoreform"))
    assert selected.scope_validated
    assert selected.requested_owners == ("scoreform", "concord")
    assert "quillan" not in selected.requested_owners


@pytest.mark.parametrize(
    "owners",
    [
        (),
        ("scoreform", "scoreform"),
        ("portia",),
        ("scoreform", "unknown_private_owner"),
        ("scoreform", "quillan", "concord", "portia"),
        ("ScoreForm",),
        ("scoreform", 42),
        ["scoreform"],
    ],
)
def test_invalid_requested_owners_are_refused_without_factory_calls(
    owners: object,
) -> None:
    result = selection.prepare_selected_attention_scope(
        workspace_root=None,
        active_school_year=YEAR,
        class_id=None,
        requested_owners=owners,  # type: ignore[arg-type]
    )
    assert result.code == "invalid_selection"
    assert result.request is None
    assert result.requested_owners == ()
    assert not result.scope_validated
    assert "unknown_private_owner" not in repr(result)


def test_missing_root_must_not_fall_back_to_saved_core_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    assert _scope(None).code == "invalid_selection"
    assert _scope(None).request is None
    assert root.is_dir()


def test_string_and_relative_roots_are_not_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    text = selection.prepare_selected_attention_scope(
        workspace_root=str(root),  # type: ignore[arg-type]
        active_school_year=YEAR, class_id=None,
        requested_owners=("scoreform",),
    )
    assert text.code == "invalid_selection"
    relative = _scope(Path("synthetic_core_attention"))
    assert relative.code == "invalid_selection"


def test_filesystem_root_is_refused_before_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    anchor = Path(root.anchor)
    result = _scope(anchor)
    assert result.code == "invalid_selection"
    assert result.request is None


def test_missing_or_unusable_selected_workspace_stays_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    missing = _scope(tmp_path / "missing_private_workspace")
    assert missing.code == "workspace_unavailable"
    assert missing.request is None
    private_file = tmp_path / "private_workspace_file"
    private_file.write_text("synthetic", encoding="utf-8")
    assert _scope(private_file).code == "workspace_unavailable"
    assert root.is_dir()


def test_core_selection_changed_since_explicit_choice_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(
        selection, "resolve_workspace_root",
        lambda: tmp_path / "private_different_user",
    )
    result = _scope(root)
    assert result.code == "workspace_mismatch"
    assert result.request is None
    assert "private_different_user" not in repr(result)


def test_core_selection_inspection_exception_is_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)

    def broken() -> Path:
        raise RuntimeError("private_student_traceback_path")

    monkeypatch.setattr(selection, "resolve_workspace_root", broken)
    result = _scope(root)
    assert result.code == "workspace_unavailable"
    assert "private_student_traceback_path" not in repr(result)


@pytest.mark.parametrize("year", [None, "", "2026-2030", "SECRET", "2027-2028"])
def test_wrong_or_missing_school_year_never_opens_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, year: str | None
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    result = _scope(root, year=year)
    assert result.code in {"invalid_selection", "school_year_mismatch"}
    assert result.request is None
    assert not result.scope_validated


def test_closed_or_unavailable_active_school_year_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(selection, "get_active_school_year", lambda _: None)
    assert _scope(root).code == "school_year_mismatch"


def test_missing_selected_class_cannot_be_implicitly_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    before = _snapshot(root)
    result = _scope(root, class_id="class_missing")
    assert result.code == "class_unavailable"
    assert result.request is None
    assert before == _snapshot(root)


@pytest.mark.parametrize("class_id", ["", "../other", "not valid class", "a/b"])
def test_unsafe_class_selection_is_refused_without_private_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, class_id: str
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    result = _scope(root, class_id=class_id)
    assert result.code in {"invalid_selection", "class_unavailable"}
    assert result.request is None
    assert class_id not in repr(result)


def test_explicit_whole_workspace_selection_keeps_class_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    result = _scope(root, class_id=None, owners=("scoreform",))
    assert result.scope_validated
    assert result.request is not None
    assert result.request.class_id is None
    assert result.requested_owners == ("scoreform",)


def test_private_root_and_class_not_exposed_in_repr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    result = _scope(root)
    assert str(root) not in repr(result)
    assert "class_a" not in repr(result)
    assert "scope_validated" in repr(result)


def test_scope_preflight_never_imports_producers_or_loads_entry_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    prefixes = ("scoreform", "quillan", "concord")
    loaded_before = {
        name for name in sys.modules
        if name.split(".", maxsplit=1)[0] in prefixes
    }
    assert _scope(root).scope_validated
    loaded_after = {
        name for name in sys.modules
        if name.split(".", maxsplit=1)[0] in prefixes
    }
    assert loaded_after == loaded_before


def test_wrong_class_symlink_redirect_refused_when_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    class_a = root / "classes" / "class_a"
    class_a.rmdir()
    outside = tmp_path / "private_other_user_class"
    outside.mkdir()
    try:
        class_a.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This host does not allow directory symlink fixtures")
    result = _scope(root)
    assert result.code == "class_unavailable"
    assert result.request is None
    assert not (outside / "new_state").exists()

def test_year_state_symlink_redirect_refused_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    year_file = root / "settings" / "school_year.json"
    outside = tmp_path / "private_foreign_year_state.json"
    outside.write_bytes(year_file.read_bytes())
    year_file.unlink()
    try:
        year_file.symlink_to(outside)
    except OSError:
        pytest.skip("This host does not allow file symlink fixtures")
    result = _scope(root)
    assert result.code == "workspace_unavailable"
    assert result.request is None


def test_classes_collection_redirect_refused_before_class_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    collection = root / "classes"
    outside = tmp_path / "private_foreign_classes"
    collection.rename(outside)
    try:
        collection.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This host does not allow directory symlink fixtures")
    result = _scope(root, class_id=None)
    assert result.code == "workspace_unavailable"
    assert result.request is None
