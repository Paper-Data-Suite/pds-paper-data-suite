"""#19E1: explicit staged runtime preflight remains default-deny."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
    ApplicationObservation,
)
from paper_data_suite.returned_paper_action_time_readiness import (
    ActionTimeReadinessError,
    PaperActionTimeReadinessV1,
    PaperProducerReadinessV1,
    _pip_check_current_interpreter,
    inspect_paper_action_time_readiness,
    render_paper_action_time_readiness,
)
from paper_data_suite.returned_paper_admission import (
    PaperAdmissionV1,
    ProducerAdmissionV1,
)
from paper_data_suite.returned_paper_runtime_probe import (
    InstalledPaperRuntimeProbeV1,
)


def _candidate(*, core: str = "exact_release_candidate",
               score: str = "exact_release_candidate") -> PaperAdmissionV1:
    return PaperAdmissionV1(
        core_installed_version="0.6.6", core_state=core,
        producers=(
            ProducerAdmissionV1("scoreform", "0.13.0", score, "0.13.0"),
            ProducerAdmissionV1(
                "quillan", "0.10.6", "exact_release_candidate", "0.10.6"
            ),
        ),
        runtime_platform="win32", runtime_python=(3, 11),
    )


def _inventory(*, broken: str = "") -> ApplicationInventory:
    rows: list[ApplicationObservation] = []
    for module in ("scoreform", "quillan"):
        unavailable = module == broken
        rows.append(ApplicationObservation(
            component_id=module, display_name=module,
            purpose="synthetic only", distribution=module,
            qualified_version="historical only", installed_version="0.1",
            console_script_name=module, console_script_target="fake:main",
            status=(
                ApplicationLaunchStatus.UNAVAILABLE if unavailable
                else ApplicationLaunchStatus.AVAILABLE
            ),
            reason="synthetic only", launcher_path=(
                None if unavailable else Path("/synthetic/venv/Scripts/") / module
            ),
        ))
    return ApplicationInventory(tuple(rows))


def _probe(stage: str = "diagnostic_match") -> InstalledPaperRuntimeProbeV1:
    if stage == "diagnostic_match":
        return InstalledPaperRuntimeProbeV1(
            "diagnostic_match", True, True, True,
            (("pypdfium2", "5.15.2"), ("zxing-cpp", "2.3.0"),
             ("Pillow", "12.0.0")),
        )
    if stage == "native_unverified":
        return InstalledPaperRuntimeProbeV1(
            "native_unverified", True, False, False,
        )
    if stage == "payload_unverified":
        return InstalledPaperRuntimeProbeV1(
            "payload_unverified", False, False, False,
        )
    return InstalledPaperRuntimeProbeV1(
        "runtime_unqualified", False, False, False,
    )


def _check(
    tmp_path: Path, *, candidate: Callable[[], PaperAdmissionV1] = _candidate,
    launcher: Callable[[], ApplicationInventory] = _inventory,
    pip: Callable[[], bool] = lambda: True,
    native: Callable[[Path], InstalledPaperRuntimeProbeV1] = lambda _: _probe(),
) -> PaperActionTimeReadinessV1:
    return inspect_paper_action_time_readiness(
        tmp_path, candidate_reader=candidate, launcher_reader=launcher,
        pip_check=pip, native_reader=native,
    )


def _forbidden(*_: object) -> object:
    pytest.fail("later check executed after earlier refusal")


def test_full_diagnostic_match_is_still_not_admission(tmp_path: Path) -> None:
    report = _check(tmp_path)
    assert report.status == "diagnostic_match_not_admitted"
    assert report.pip_ok and report.launchers_checked
    assert report.native_probe_status == "diagnostic_match"
    assert report.qualified_modules == frozenset()
    assert report.producer_dispatch_authorized is False
    assert report.processing_status == "preview_only"
    assert all(not p.dispatch_eligible for p in report.producers)
    assert tuple(p.module_id for p in report.producers) == (
        "scoreform", "quillan"
    )


def test_diagnostic_cannot_be_promoted_by_dataclass_mutation(
    tmp_path: Path,
) -> None:
    report = _check(tmp_path)
    with pytest.raises(ActionTimeReadinessError):
        replace(report, qualified_modules=frozenset({"scoreform"}))
    with pytest.raises(ActionTimeReadinessError):
        replace(report, producer_dispatch_authorized=True)  # type: ignore[arg-type]
    with pytest.raises(ActionTimeReadinessError):
        replace(report, processing_status="enabled")  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        report.status = "candidate_unqualified"  # type: ignore[misc]
    with pytest.raises(ActionTimeReadinessError):
        replace(report.producers[0], dispatch_eligible=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("case", [
    "core", "scoreform", "missing", "exception", "untyped",
])
def test_unqualified_candidate_never_runs_launcher_pip_or_native(
    tmp_path: Path, case: str,
) -> None:
    def candidate() -> PaperAdmissionV1:
        if case == "core":
            return _candidate(core="not_installed")
        if case == "scoreform":
            return _candidate(score="not_installed")
        if case == "exception":
            raise RuntimeError("PRIVATE STUDENT PATH")
        if case == "untyped":
            return object()  # type: ignore[return-value]
        return _candidate(core="runtime_unqualified")

    result = inspect_paper_action_time_readiness(
        tmp_path, candidate_reader=candidate,
        launcher_reader=_forbidden,  # type: ignore[arg-type]
        pip_check=_forbidden,  # type: ignore[arg-type]
        native_reader=_forbidden,  # type: ignore[arg-type]
    )
    assert result.status == "candidate_unqualified"
    assert not result.pip_checked and not result.launchers_checked
    assert not result.qualified_modules
    if case == "scoreform":
        assert result.producers[0].state == "not_installed"


@pytest.mark.parametrize("case", [
    "missing", "unavailable", "duplicate", "exception", "invalid",
])
def test_launcher_refusal_never_runs_pip_or_native(
    tmp_path: Path, case: str,
) -> None:
    def launcher() -> ApplicationInventory:
        inventory = _inventory(broken="quillan" if case == "unavailable" else "")
        if case == "missing":
            return ApplicationInventory(inventory.applications[:1])
        if case == "duplicate":
            return ApplicationInventory(inventory.applications + (
                inventory.applications[0],
            ))
        if case == "exception":
            raise RuntimeError("PRIVATE PATH")
        if case == "invalid":
            return object()  # type: ignore[return-value]
        return inventory

    report = inspect_paper_action_time_readiness(
        tmp_path, candidate_reader=_candidate, launcher_reader=launcher,
        pip_check=_forbidden,  # type: ignore[arg-type]
        native_reader=_forbidden,  # type: ignore[arg-type]
    )
    assert report.status == "launcher_unqualified"
    assert report.launchers_checked and not report.pip_checked
    assert not report.qualified_modules


@pytest.mark.parametrize("case", ["false", "exception", "nonbool"])
def test_dependency_refusal_never_probes_native(
    tmp_path: Path, case: str,
) -> None:
    def pip() -> bool:
        if case == "exception":
            raise RuntimeError("PRIVATE PIP OUTPUT")
        if case == "nonbool":
            return 1  # type: ignore[return-value]
        return False

    report = inspect_paper_action_time_readiness(
        tmp_path, candidate_reader=_candidate, launcher_reader=_inventory,
        pip_check=pip, native_reader=_forbidden,  # type: ignore[arg-type]
    )
    assert report.status == "dependencies_unqualified"
    assert report.pip_checked and not report.pip_ok
    assert report.native_probe_status is None


@pytest.mark.parametrize("case", [
    "native_unverified", "payload_unverified", "runtime_unqualified",
    "exception", "untyped",
])
def test_runtime_refusal_does_not_claim_admission(
    tmp_path: Path, case: str,
) -> None:
    def probe(_: Path) -> InstalledPaperRuntimeProbeV1:
        if case == "exception":
            raise OSError("PRIVATE decoder")
        if case == "untyped":
            # A fabricated duck-typed observation must never qualify.
            return SimpleNamespace(  # type: ignore[return-value]
                status="diagnostic_match"
            )
        return _probe(case)

    report = _check(tmp_path, native=probe)
    assert report.status == "runtime_unqualified"
    assert report.native_probe_status != "diagnostic_match"
    assert report.qualified_modules == frozenset()


@pytest.mark.parametrize("input_path", [Path("relative"), "bad", 5])
def test_wheelhouse_must_be_explicit_absolute_path(input_path: object) -> None:
    with pytest.raises(ActionTimeReadinessError):
        inspect_paper_action_time_readiness(input_path)  # type: ignore[arg-type]


def test_no_exceptions_or_private_paths_in_display(tmp_path: Path) -> None:
    result = _check(tmp_path)
    display = render_paper_action_time_readiness(result)
    assert "diagnostic_match_not_admitted" in display
    assert "scoreform: diagnostic_match_not_admitted" in display
    assert "quillan: diagnostic_match_not_admitted" in display
    assert "NOT admitted" in display
    assert str(tmp_path) not in display
    assert "PRIVATE" not in display
    assert "student" not in display.lower()
    assert "no producer handlers ran" in display


def test_invalid_diagnostic_object_is_refused() -> None:
    with pytest.raises(ActionTimeReadinessError):
        PaperProducerReadinessV1("portia", "metadata_unqualified")
    with pytest.raises(ActionTimeReadinessError):
        PaperActionTimeReadinessV1(
            "diagnostic_match_not_admitted", (
                PaperProducerReadinessV1("scoreform", "metadata_unqualified"),
                PaperProducerReadinessV1("quillan", "metadata_unqualified"),
            ), False, False, False, None,
        )
    with pytest.raises(ActionTimeReadinessError):
        render_paper_action_time_readiness(object())  # type: ignore[arg-type]


def test_offline_pip_check_has_no_installer_or_network_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_action_time_readiness as gate

    received: list[object] = []

    def run(command: object, **kwargs: object) -> object:
        received.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert _pip_check_current_interpreter()
    assert len(received) == 1
    command, kwargs = received[0]  # type: ignore[misc]
    assert command == (gate.sys.executable, "-m", "pip", "check")
    assert kwargs["timeout"] == 30
    assert kwargs["check"] is False
    assert "shell" not in kwargs
    assert kwargs["stdout"] == gate.subprocess.DEVNULL
    assert kwargs["stderr"] == gate.subprocess.DEVNULL


def test_pip_check_runtime_failure_denies_without_leaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_action_time_readiness as gate

    def denied(*_: object, **__: object) -> object:
        raise OSError("SECRET PATH")

    monkeypatch.setattr(gate.subprocess, "run", denied)
    assert not _pip_check_current_interpreter()


def test_readiness_does_not_import_dispatch_or_create_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    original = builtins.__import__
    forbidden = (
        "paper_data_suite.returned_paper_ordered_dispatch",
        "pds_core.module_dispatch", "scoreform", "quillan",
    )

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name in forbidden:
            pytest.fail("ready-only preflight imported a handler")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    before = tuple(tmp_path.rglob("*"))
    report = _check(tmp_path)
    assert report.qualified_modules == frozenset()
    assert tuple(tmp_path.rglob("*")) == before
