"""Issue #49 Slice 23 Fix 1: real pip Windows distlib wrapper contracts."""

from __future__ import annotations

import io
import warnings
import zipfile
from pathlib import Path

import pytest
from test_issue49_slice9_virtualenv_runtime import (
    _inspect,
    _scene,
    _windows_wrapper,
)

from paper_data_suite.evergreen_staged_runtime import StagedRuntimeError

MODERN_WINDOWS_WRAPPER = (
    "import sys\n"
    "from demo_app.cli import main\n"
    "if __name__ == '__main__':\n"
    "    sys.argv[0] = sys.argv[0].removesuffix('.exe')\n"
    "    sys.exit(main())\n"
)


def test_real_pip_windows_removesuffix_template_accepted(tmp_path: Path) -> None:
    scene = _scene(tmp_path, layout="windows")
    _windows_wrapper(scene[0] / "Scripts/demo.exe", MODERN_WINDOWS_WRAPPER)
    result = _inspect(scene)
    assert len(result.console_launchers) == 1
    assert result.console_launchers[0].target == "demo_app.cli:main"
    assert result.native_executables_authenticated is False


@pytest.mark.parametrize(
    "changed",
    [
        MODERN_WINDOWS_WRAPPER.replace("demo_app.cli", "evil.cli"),
        MODERN_WINDOWS_WRAPPER.replace("removesuffix('.exe')", "removesuffix('.py')"),
        MODERN_WINDOWS_WRAPPER.replace("sys.exit(main())", "sys.exit(evil())"),
        MODERN_WINDOWS_WRAPPER + "print('injected')\n",
        MODERN_WINDOWS_WRAPPER.replace("removesuffix('.exe')", "replace('.exe', '')"),
    ],
)
def test_modified_windows_pip_wrapper_is_rejected(tmp_path: Path, changed: str) -> None:
    scene = _scene(tmp_path, layout="windows")
    _windows_wrapper(scene[0] / "Scripts/demo.exe", changed)
    with pytest.raises(StagedRuntimeError, match="console wrapper"):
        _inspect(scene)


def test_windows_template_not_allowed_on_posix(tmp_path: Path) -> None:
    scene = _scene(tmp_path, layout="posix")
    (scene[0] / "bin/demo").write_text(
        "#!/private/python\n" + MODERN_WINDOWS_WRAPPER, encoding="utf-8"
    )
    with pytest.raises(StagedRuntimeError, match="console wrapper"):
        _inspect(scene)


def test_duplicate_windows_zip_main_rejected(tmp_path: Path) -> None:
    scene = _scene(tmp_path, layout="windows")
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name: '__main__.py'")
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("__main__.py", MODERN_WINDOWS_WRAPPER)
            archive.writestr("__main__.py", MODERN_WINDOWS_WRAPPER)
    (scene[0] / "Scripts/demo.exe").write_bytes(b"MZ" + stream.getvalue())
    with pytest.raises(StagedRuntimeError, match="embedded launcher"):
        _inspect(scene)
