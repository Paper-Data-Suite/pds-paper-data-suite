"""#19G1: Core producer output must not escape into Teacher Home."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import pytest
from pds_core.module_profiles import ModuleRegistry

from paper_data_suite import returned_paper_ordered_dispatch as ordered


def test_core_dispatch_suppresses_producer_stdout_stderr_without_changing_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_root = tmp_path / "PRIVATE_STUDENT_SAMPLE"
    expected = (object(),)
    seen: list[tuple[Path, object, object]] = []
    registry = cast(ModuleRegistry, object())
    requests = ()

    def noisy(root: Path, current: object, pages: object) -> tuple[object, ...]:
        seen.append((root, current, pages))
        print(f"Saved {root}/classes/PRIVATE_STUDENT_SAMPLE/debug.png")
        print("PRIVATE_STUDENT_SAMPLE and PDS2|secret", file=sys.stderr)
        return expected

    monkeypatch.setattr(ordered, "dispatch_routes", noisy)
    result = ordered._core_dispatch(private_root, registry, requests)
    assert result is expected
    assert seen == [(private_root, registry, requests)]
    output = capsys.readouterr()
    assert output.out == "" and output.err == ""
    print("Teacher menu still visible after Core handler")
    assert "Teacher menu still visible" in capsys.readouterr().out


def test_core_dispatch_does_not_swallow_handler_failure_or_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invocations = 0

    def failing(_root: Path, _registry: object, _pages: object) -> object:
        nonlocal invocations
        invocations += 1
        print("C:/PRIVATE_STUDENT_SAMPLE/debug.png")
        print("PDS2|PRIVATE", file=sys.stderr)
        raise RuntimeError("Core handler failure is still propagated")

    monkeypatch.setattr(ordered, "dispatch_routes", failing)
    with pytest.raises(RuntimeError, match="still propagated"):
        ordered._core_dispatch(tmp_path, cast(ModuleRegistry, object()), ())
    assert invocations == 1
    output = capsys.readouterr()
    assert output.out == "" and output.err == ""


def test_core_dispatch_never_invents_success_or_report_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[object] = []

    def producing(_root: Path, _registry: object, _pages: object) -> tuple[()]:
        observed.append(True)
        return ()

    monkeypatch.setattr(ordered, "dispatch_routes", producing)
    assert ordered._core_dispatch(tmp_path, cast(ModuleRegistry, object()), ()) == ()
    assert observed == [True]
