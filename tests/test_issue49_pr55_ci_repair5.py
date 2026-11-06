"""Issue #49 PR #55 CI repair 5: installed-wheel dependency boundary."""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from scripts import smoke_test_wheel, smoke_test_workspace_restore_wheel


@pytest.mark.parametrize(
    "module",
    [smoke_test_wheel, smoke_test_workspace_restore_wheel],
)
def test_third_party_runtime_dependencies_are_downloaded_then_installed_offline(
    module: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def capture(
        command: list[str], *, cwd: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == tmp_path
        observed.append((tuple(command), dict(env)))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(module, "_run", capture)
    wheelhouse = tmp_path / "third_party_wheelhouse"
    local_env = {"PIP_NO_INDEX": "1", "KEEP": "value"}
    module._install_runtime_dependencies(  # type: ignore[attr-defined]
        tmp_path / "python",
        wheelhouse=wheelhouse,
        cwd=tmp_path,
        env=local_env,
    )

    assert wheelhouse.is_dir()
    assert len(observed) == 2
    download, online_env = observed[0]
    install, offline_env = observed[1]
    assert download[1:4] == ("-m", "pip", "download")
    assert "--only-binary=:all:" in download
    assert "PIP_NO_INDEX" not in online_env
    assert online_env["KEEP"] == "value"
    assert install[1:4] == ("-m", "pip", "install")
    assert "--no-index" in install
    assert "--find-links" in install
    assert "--only-binary=:all:" in install
    assert offline_env == local_env
    for specifier in ("packaging>=24,<27", "cryptography>=45,<47"):
        assert specifier in download
        assert specifier in install
    assert "pds-core" not in " ".join(download + install)
    assert "paper-data-suite" not in " ".join(download + install)
    assert local_env["PIP_NO_INDEX"] == "1"


@pytest.mark.parametrize(
    "module,function_name",
    [
        (smoke_test_wheel, "smoke_test"),
        (smoke_test_workspace_restore_wheel, "smoke_test_workspace_restore_wheel"),
    ],
)
def test_runtime_dependencies_are_installed_before_pip_check(
    module: object, function_name: str
) -> None:
    source = inspect.getsource(getattr(module, function_name))
    assert source.index("_install_runtime_dependencies(") < source.index(
        '"check"'
    )
    assert source.index("_install_runtime_dependencies(") < source.index(
        "str(core_wheel)"
    )
