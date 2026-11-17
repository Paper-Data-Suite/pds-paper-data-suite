"""#19E3B1: exact installed Windows composition, default-deny otherwise."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from paper_data_suite import returned_paper_live_admission as policy
from paper_data_suite.returned_paper_action_time_readiness import (
    PaperActionTimeReadinessV1,
    PaperProducerReadinessV1,
)
from paper_data_suite.returned_paper_live_admission import (
    LivePaperAdmissionError,
    LivePaperAdmissionV1,
    _wheelhouse_safe,
    inspect_live_paper_admission,
    render_live_paper_admission,
)


def _matching() -> PaperActionTimeReadinessV1:
    return PaperActionTimeReadinessV1(
        "diagnostic_match_not_admitted",
        (
            PaperProducerReadinessV1(
                "scoreform", "diagnostic_match_not_admitted"
            ),
            PaperProducerReadinessV1(
                "quillan", "diagnostic_match_not_admitted"
            ),
        ),
        True, True, True, "diagnostic_match",
    )


def _audit(monkeypatch: pytest.MonkeyPatch, response: object) -> list[Path]:
    calls: list[Path] = []

    def inspect(path: Path) -> PaperActionTimeReadinessV1:
        calls.append(path)
        return response  # type: ignore[return-value]

    monkeypatch.setattr(policy, "_action_host_supported", lambda: True)
    monkeypatch.setattr(policy, "inspect_paper_action_time_readiness", inspect)
    return calls


def test_full_current_match_is_exact_temporarily_eligible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    calls = _audit(monkeypatch, _matching())
    status = inspect_live_paper_admission(tmp_path)
    assert calls == [tmp_path]
    assert status.status == "admitted"
    assert status.qualified_modules == frozenset({"scoreform", "quillan"})
    assert status.action_time_only and status.can_skip_second_consent is False
    assert status.source_retention_authorized is False
    assert "eligible for this action only" in render_live_paper_admission(status)


@pytest.mark.parametrize("status", [
    "candidate_unqualified", "launcher_unqualified",
    "dependencies_unqualified", "runtime_unqualified",
])
def test_any_lower_diagnostic_stage_refuses_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str,
) -> None:
    rows = tuple(
        PaperProducerReadinessV1(name, "metadata_unqualified")
        for name in ("scoreform", "quillan")
    )
    flags = {
        "candidate_unqualified": (False, False, False, None),
        "launcher_unqualified": (True, False, False, None),
        "dependencies_unqualified": (True, True, False, None),
        "runtime_unqualified": (True, True, True, "native_unverified"),
    }
    diagnostic = PaperActionTimeReadinessV1(
        status, rows, *flags[status],  # type: ignore[arg-type]
    )
    calls = _audit(monkeypatch, diagnostic)
    decision = inspect_live_paper_admission(tmp_path)
    assert decision.status == "audit_refused" and not decision.qualified_modules
    assert calls == [tmp_path]


@pytest.mark.parametrize("outcome", ["bad", "error", "keyboard"])
def test_untyped_or_failed_audit_cannot_become_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    monkeypatch.setattr(policy, "_action_host_supported", lambda: True)

    def read(_: Path) -> object:
        if outcome == "error":
            raise RuntimeError("SECRET STUDENT PATH")
        if outcome == "keyboard":
            raise KeyboardInterrupt
        return object()

    monkeypatch.setattr(policy, "inspect_paper_action_time_readiness", read)
    result = inspect_live_paper_admission(tmp_path)
    assert result.status == "audit_refused"
    assert "SECRET" not in render_live_paper_admission(result)
    assert not result.qualified_modules


def test_unsupported_host_stops_before_disk_or_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy, "_action_host_supported", lambda: False)
    monkeypatch.setattr(
        policy, "inspect_paper_action_time_readiness",
        lambda _: pytest.fail("audit run on unsupported host"),
    )
    decision = inspect_live_paper_admission(tmp_path)
    assert decision.status == "unsupported_runtime"
    assert decision.qualified_modules == frozenset()


@pytest.mark.parametrize("bad", [Path("relative"), Path("..")])
def test_wheelhouse_must_be_explicit_absolute(bad: Path) -> None:
    assert not _wheelhouse_safe(bad)


def test_missing_wheelhouse_is_not_admitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _audit(monkeypatch, _matching())
    decision = inspect_live_paper_admission(tmp_path / "absent")
    assert decision.status == "wheelhouse_unavailable"


def test_symlinked_wheelhouse_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privilege unavailable")
    _audit(monkeypatch, _matching())
    assert inspect_live_paper_admission(alias).status == "wheelhouse_unavailable"


@pytest.mark.parametrize("change", [
    {"status": "admitted", "qualified_modules": frozenset()},
    {"status": "audit_refused", "qualified_modules": frozenset({"scoreform"})},
    {"status": "admitted", "qualified_modules": frozenset({"scoreform"})},
    {"status": "admitted", "can_skip_second_consent": True},
    {"status": "admitted", "source_retention_authorized": True},
])
def test_fabricated_or_partial_admission_result_fails_closed(
    change: dict[str, object],
) -> None:
    with pytest.raises(LivePaperAdmissionError):
        LivePaperAdmissionV1(**change)  # type: ignore[arg-type]


def test_result_is_immutable_and_review_does_not_cache() -> None:
    state = LivePaperAdmissionV1(
        "admitted", frozenset({"scoreform", "quillan"})
    )
    with pytest.raises(FrozenInstanceError):
        state.status = "audit_refused"  # type: ignore[misc]
    with pytest.raises(LivePaperAdmissionError):
        replace(state, qualified_modules=frozenset())
    assert "cached credential" in render_live_paper_admission(state)


def test_no_untrusted_object_injection_seam() -> None:
    import inspect

    sig = inspect.signature(inspect_live_paper_admission)
    assert tuple(sig.parameters) == ("wheelhouse",)
    source = Path(policy.__file__).read_text(encoding="utf-8")
    assert "execute_with_core_review(" not in source
    assert "dispatch_routes(" not in source
    assert "qualified_modules: frozenset[str] = frozenset()" in source
    assert "sys.platform == \"win32\"" in source
    assert "platform.machine().casefold()" in source


def test_renderer_rejects_nontyped_result() -> None:
    with pytest.raises(LivePaperAdmissionError):
        render_live_paper_admission(object())  # type: ignore[arg-type]
