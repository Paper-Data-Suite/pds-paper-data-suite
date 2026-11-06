"""Issue #49 Slice 6: bounded, closed wheelhouse inspection (non-authorizing)."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from paper_data_suite.evergreen_wheelhouse import (
    WheelhouseError,
    WheelPin,
    inspect_closed_wheelhouse,
)


def _wheel(
    *,
    name: str = "demo-app",
    version: str = "1.0.0",
    requirements: tuple[str, ...] = ("demo-core>=2,<3",),
    python: str = ">=3.11",
    extras: tuple[str, ...] = (),
    member: str = "demo_app/__init__.py",
    tags: str = "py3-none-any",
    meta_name: str | None = None,
    meta_version: str | None = None,
    metadata_override: bytes | None = None,
) -> bytes:
    prefix = f"{name.replace('-', '_')}-{version}.dist-info"
    fields = [
        "Metadata-Version: 2.3",
        f"Name: {meta_name or name}",
        f"Version: {meta_version or version}",
        f"Requires-Python: {python}",
    ]
    fields.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
    fields.extend(f"Provides-Extra: {extra}" for extra in extras)
    meta = "\n".join(fields).encode("utf-8") + b"\n\n"
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{prefix}/METADATA", metadata_override or meta)
        archive.writestr(f"{prefix}/WHEEL", f"Wheel-Version: 1.0\nTag: {tags}\n")
        archive.writestr(f"{prefix}/RECORD", "")
        archive.writestr(member.replace("\\", "/"), "synthetic wheel\n")
    wheel_bytes = target.getvalue()
    if "\\" in member:
        # zipfile normalizes backslashes on Windows before writing. Replace the
        # same-length names in both ZIP headers to retain the malicious bytes.
        safe_name = member.replace("\\", "/").encode("ascii")
        unsafe_name = member.encode("ascii")
        if wheel_bytes.count(safe_name) != 2:
            raise AssertionError("unexpected ZIP fixture header layout")
        wheel_bytes = wheel_bytes.replace(safe_name, unsafe_name)
    return wheel_bytes


def _add(
    folder: Path,
    name: str = "demo-app",
    version: str = "1.0.0",
    **kwargs: Any,
) -> WheelPin:
    filename = f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
    data = _wheel(name=name, version=version, **kwargs)
    (folder / filename).write_bytes(data)
    return WheelPin(filename, hashlib.sha256(data).hexdigest())


def _closed(directory: Path, *pins: WheelPin, roots: tuple[str, ...] = ("demo-app",)):
    return inspect_closed_wheelhouse(directory, pins=tuple(pins), roots=roots)


def test_closed_wheelhouse_has_exact_dependency_graph(tmp_path: Path) -> None:
    app = _add(tmp_path)
    core = _add(tmp_path, name="demo-core", version="2.4.0", requirements=())
    result = _closed(tmp_path, app, core)
    assert result.roots == ("demo-app",)
    assert tuple(wheel.distribution for wheel in result.wheels) == (
        "demo-app",
        "demo-core",
    )
    assert result.dependency_edges == (("demo-app", "demo-core"),)
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "authenticated")


def test_unrelated_unpinned_file_fails(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=())
    (tmp_path / "untrusted.whl").write_bytes(b"garbage")
    with pytest.raises(WheelhouseError, match="unpinned"):
        _closed(tmp_path, app)


def test_pin_mismatch_detects_modified_wheel(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=())
    (tmp_path / app.filename).write_bytes(b"malicious")
    with pytest.raises(WheelhouseError, match="SHA-256"):
        _closed(tmp_path, app)


def test_missing_transitive_dependency_fails(tmp_path: Path) -> None:
    app = _add(tmp_path)
    with pytest.raises(WheelhouseError, match="unlocked dependency"):
        _closed(tmp_path, app)


def test_pinned_incompatible_dependency_version_fails(tmp_path: Path) -> None:
    app = _add(tmp_path)
    core = _add(tmp_path, name="demo-core", version="3.0.0", requirements=())
    with pytest.raises(WheelhouseError, match="violates requirement"):
        _closed(tmp_path, app, core)


def test_extra_wheel_is_rejected_even_if_exact_hash_pinned(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=())
    core = _add(tmp_path, name="demo-core", version="2.0.0", requirements=())
    with pytest.raises(WheelhouseError, match="unrelated"):
        _closed(tmp_path, app, core)


def test_environment_marker_excludes_unneeded_dependency(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=("demo-core; python_version < '2'",))
    result = _closed(tmp_path, app)
    assert result.dependency_edges == ()


def test_declared_extra_traverses_all_activated_dependencies(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=("demo-core[special]>=2,<3",))
    core = _add(
        tmp_path,
        name="demo-core",
        version="2.0.0",
        requirements=("demo-extra>=1; extra == 'special'",),
        extras=("special",),
    )
    extra = _add(tmp_path, name="demo-extra", version="1.1.0", requirements=())
    result = _closed(tmp_path, app, core, extra)
    assert result.dependency_edges == (
        ("demo-app", "demo-core"),
        ("demo-core", "demo-extra"),
    )


def test_undeclared_dependency_extra_fails(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=("demo-core[admin]>=2",))
    core = _add(tmp_path, name="demo-core", version="2.0.0", requirements=())
    with pytest.raises(WheelhouseError, match="undeclared extra"):
        _closed(tmp_path, app, core)


def test_duplicate_normalized_distribution_fails(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=())
    duplicate = _add(tmp_path, name="demo_app", version="1.1.0", requirements=())
    with pytest.raises(WheelhouseError, match="duplicate normalized"):
        _closed(tmp_path, app, duplicate)


def test_mutually_dependent_wheels_terminate_safely(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=("demo-core>=2",))
    core = _add(
        tmp_path, name="demo-core", version="2.0.0", requirements=("demo-app>=1",)
    )
    result = _closed(tmp_path, app, core)
    assert len(result.dependency_edges) == 2


@pytest.mark.parametrize(
    ("requirements", "expected"),
    [
        (("demo-core @ https://example.invalid/core.whl",), "direct-URL"),
        (("invalid bad requirement",), "Requires-Dist"),
    ],
)
def test_dependency_syntax_and_direct_url_fails(
    tmp_path: Path, requirements: tuple[str, ...], expected: str
) -> None:
    app = _add(tmp_path, requirements=requirements)
    with pytest.raises(WheelhouseError, match=expected):
        _closed(tmp_path, app)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"meta_name": "different"}, "distribution mismatch"),
        ({"meta_version": "1.2.0"}, "version mismatch"),
        ({"python": ">=99"}, "does not support"),
        ({"member": "../outside.py"}, "unsafe"),
        ({"member": "x\\outside.py"}, "unsafe"),
        ({"tags": "cp312-cp312-win_amd64"}, "WHEEL tags disagree"),
    ],
)
def test_hash_matching_invalid_wheels_still_fail(
    tmp_path: Path, changes: dict[str, str], expected: str
) -> None:
    app = _add(tmp_path, requirements=(), **changes)
    with pytest.raises(WheelhouseError, match=expected):
        _closed(tmp_path, app)


def test_backslash_fixture_preserves_unmodified_zip_member_name() -> None:
    data = _wheel(requirements=(), member="x\\outside.py")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        originals = [item.orig_filename for item in archive.infolist()]
    assert "x\\outside.py" in originals


def test_symlink_wheel_refused_without_modifying_target(tmp_path: Path) -> None:
    other = tmp_path / "outside"
    other.mkdir()
    wheel = _add(other, requirements=())
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    link = wheelhouse / wheel.filename
    try:
        link.symlink_to(other / wheel.filename)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(WheelhouseError, match="not a link"):
        _closed(wheelhouse, wheel)
    assert (other / wheel.filename).is_file()


def test_symlink_wheelhouse_directory_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    wheel = _add(real, requirements=())
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(WheelhouseError, match="reparse"):
        _closed(link, wheel)


@pytest.mark.parametrize(
    "invalid_filename",
    ["../other.whl", "a\\b.whl", "foo.whl", "../evil-1-py3-none-any.whl"],
)
def test_pin_rejects_invalid_filenames(invalid_filename: str) -> None:
    with pytest.raises(WheelhouseError, match="filename"):
        WheelPin(invalid_filename, "a" * 64)


def test_pin_requires_exact_lowercase_hash() -> None:
    with pytest.raises(WheelhouseError, match="SHA-256"):
        WheelPin("demo_app-1.0.0-py3-none-any.whl", "A" * 64)


def test_missing_pinned_wheel_fails(tmp_path: Path) -> None:
    with pytest.raises(WheelhouseError, match="missing"):
        _closed(
            tmp_path,
            WheelPin("demo_app-1.0.0-py3-none-any.whl", "a" * 64),
        )


def test_duplicate_root_spelling_is_rejected(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=())
    with pytest.raises(WheelhouseError, match="duplicate root"):
        _closed(tmp_path, app, roots=("demo-app", "demo_app"))


def test_no_wheelhouse_side_effects(tmp_path: Path) -> None:
    app = _add(tmp_path, requirements=())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    _closed(tmp_path, app)
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert before == after
