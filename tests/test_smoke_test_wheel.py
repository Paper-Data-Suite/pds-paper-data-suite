from __future__ import annotations

from pathlib import Path

import pytest

from scripts import smoke_test_wheel


def test_main_invokes_smoke_test_with_cli_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"
    observed: list[tuple[Path, Path]] = []

    def fake_smoke_test(suite_wheel: Path, core_wheel: Path) -> None:
        observed.append((suite_wheel, core_wheel))

    monkeypatch.setattr(smoke_test_wheel, "smoke_test", fake_smoke_test)

    assert smoke_test_wheel.main((str(suite), str(core))) == 0
    assert observed == [(suite, core)]
    assert capsys.readouterr().out.strip() == "Smoke test passed."


def test_main_returns_failure_when_smoke_test_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"

    def fail_smoke_test(suite_wheel: Path, core_wheel: Path) -> None:
        del suite_wheel, core_wheel
        raise smoke_test_wheel.SmokeTestError("synthetic failure")

    monkeypatch.setattr(smoke_test_wheel, "smoke_test", fail_smoke_test)

    assert smoke_test_wheel.main((str(suite), str(core))) == 1
    assert "synthetic failure" in capsys.readouterr().err


def test_doctor_output_assertion_requires_reduced_fidelity_sections() -> None:
    output = "\n".join(
        (
            "Paper Data Suite doctor",
            "Runtime",
            "Suite",
            "Packages",
            "Dependencies",
            "Entry points",
            "Core",
            "Workspace",
            "Core registry",
            "Providers",
            "Modules",
            "Overall",
            "No accessible workspace currently exists at the resolved path.",
            (
                "Routing/publication provider compatibility has reduced "
                "diagnostic fidelity."
            ),
            "Shared module-reported readiness is not available.",
        )
    )

    smoke_test_wheel._assert_doctor_output(output)


def test_doctor_output_assertion_rejects_incomplete_report() -> None:
    with pytest.raises(smoke_test_wheel.SmokeTestError):
        smoke_test_wheel._assert_doctor_output("Paper Data Suite doctor\nOverall\n")
