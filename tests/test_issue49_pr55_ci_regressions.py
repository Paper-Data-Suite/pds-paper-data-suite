"""PR #55: stable doctor wording and exact pip wrapper allowlist."""

from __future__ import annotations

import pytest

from paper_data_suite.doctor import _CORE_PUBLIC_CONTRACTS, render_doctor_report
from paper_data_suite.evergreen_local_doctor import _core_public_contract_checks
from paper_data_suite.evergreen_staged_runtime import (
    StagedRuntimeError,
    _safe_wrapper,
)


def _modern_wrapper(module: str = "demo_app.cli") -> bytes:
    return (
        "#!/isolated/venv/bin/python\n"
        "import sys\n"
        f"from {module} import main\n"
        "if __name__ == '__main__':\n"
        "    sys.argv[0] = sys.argv[0].removesuffix('.exe')\n"
        "    sys.exit(main())\n"
    ).encode("utf-8")


@pytest.mark.parametrize("windows", (False, True))
def test_modern_pip_wrapper_exact_ast_is_accepted(windows: bool) -> None:
    _safe_wrapper(_modern_wrapper(), "demo_app.cli:main", windows=windows)


@pytest.mark.parametrize("windows", (False, True))
def test_modern_pip_wrapper_wrong_owner_is_refused(windows: bool) -> None:
    with pytest.raises(StagedRuntimeError, match="console wrapper"):
        _safe_wrapper(
            _modern_wrapper("foreign.cli"), "demo_app.cli:main", windows=windows
        )


@pytest.mark.parametrize("windows", (False, True))
def test_modern_pip_wrapper_with_extra_code_is_refused(windows: bool) -> None:
    with pytest.raises(StagedRuntimeError, match="console wrapper"):
        _safe_wrapper(
            _modern_wrapper() + b"print('unowned work')\n",
            "demo_app.cli:main",
            windows=windows,
        )


def test_doctor_core_public_contract_wording_is_stable() -> None:
    class PublicCore:
        def __getattr__(self, name: str) -> object:
            return lambda *args, **kwargs: None

    report = _core_public_contract_checks(module_importer=lambda _: PublicCore())
    assert report.exit_code == 0
    rendered = render_doctor_report(report)
    for _module, _name, purpose in _CORE_PUBLIC_CONTRACTS:
        assert f"Core {purpose} public contract is available." in rendered


def test_doctor_missing_public_contract_still_fails() -> None:
    class EmptyCore:
        pass

    report = _core_public_contract_checks(module_importer=lambda _: EmptyCore())
    assert report.exit_code == 1
    assert all(check.code == "core.contract_missing" for check in report.checks)
