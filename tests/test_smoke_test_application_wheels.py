from __future__ import annotations

from pathlib import Path

import pytest

from scripts import smoke_test_application_wheels


def _applications() -> tuple[
    smoke_test_application_wheels.ApplicationExpectation,
    ...,
]:
    expectation = smoke_test_application_wheels.ApplicationExpectation
    return (
        expectation(
            "concord",
            "Concord",
            "0.2.0",
            "concord.whl",
            "concord",
        ),
        expectation(
            "quillan",
            "Quillan",
            "0.9.0",
            "quillan.whl",
            "quillan",
        ),
    )


def test_inventory_output_accepts_all_available_composition() -> None:
    output = """Paper Data Suite applications

Concord
  Purpose: Collaborative classroom evidence.
  Status: available
  Component ID: concord
  Suite-qualified version: 0.2.0
  Installed version: 0.2.0
  Launch: pds launch concord

Quillan
  Purpose: Writing evidence.
  Status: available
  Component ID: quillan
  Suite-qualified version: 0.9.0
  Installed version: 0.9.0
  Launch: pds launch quillan
"""
    smoke_test_application_wheels._assert_inventory_output(
        output,
        _applications(),
    )


def test_inventory_output_rejects_partial_composition() -> None:
    output = """Paper Data Suite applications

Concord
  Status: available
  Component ID: concord
  Suite-qualified version: 0.2.0
  Installed version: 0.2.0
  Launch: pds launch concord

Quillan
  Status: not installed
  Component ID: quillan
  Suite-qualified version: 0.9.0
  Installed version: not installed
"""
    with pytest.raises(
        smoke_test_application_wheels.ApplicationWheelSmokeError,
    ):
        smoke_test_application_wheels._assert_inventory_output(
            output,
            _applications(),
        )


def test_inventory_output_rejects_non_application_row() -> None:
    output = """Paper Data Suite applications

Concord
  Status: available
  Component ID: concord
  Suite-qualified version: 0.2.0
  Installed version: 0.2.0
  Launch: pds launch concord

Quillan
  Status: available
  Component ID: quillan
  Suite-qualified version: 0.9.0
  Installed version: 0.9.0
  Launch: pds launch quillan

PDS Core
"""
    with pytest.raises(
        smoke_test_application_wheels.ApplicationWheelSmokeError,
        match="invalid row",
    ):
        smoke_test_application_wheels._assert_inventory_output(
            output,
            _applications(),
        )


def test_main_invokes_smoke_test_with_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    artifacts = tmp_path / "artifacts"
    observed: list[tuple[Path, Path]] = []

    def fake_smoke_test(suite_wheel: Path, artifact_dir: Path) -> None:
        observed.append((suite_wheel, artifact_dir))

    monkeypatch.setattr(
        smoke_test_application_wheels,
        "smoke_test",
        fake_smoke_test,
    )

    assert (
        smoke_test_application_wheels.main(
            (str(suite), "--artifact-dir", str(artifacts))
        )
        == 0
    )
    assert observed == [(suite, artifacts)]
    assert (
        capsys.readouterr().out.strip()
        == "Application wheel smoke test passed."
    )


def test_main_returns_failure_when_smoke_test_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    artifacts = tmp_path / "artifacts"

    def fail_smoke_test(suite_wheel: Path, artifact_dir: Path) -> None:
        del suite_wheel, artifact_dir
        raise smoke_test_application_wheels.ApplicationWheelSmokeError(
            "synthetic failure"
        )

    monkeypatch.setattr(
        smoke_test_application_wheels,
        "smoke_test",
        fail_smoke_test,
    )

    assert (
        smoke_test_application_wheels.main(
            (str(suite), "--artifact-dir", str(artifacts))
        )
        == 1
    )
    assert "synthetic failure" in capsys.readouterr().err
