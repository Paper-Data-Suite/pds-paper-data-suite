"""#19A3: isolated native/profile preflight is always non-authorizing."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import paper_data_suite.returned_paper_runtime_probe as probe
from paper_data_suite.returned_paper_admission import (
    PaperAdmissionV1,
    ProducerAdmissionV1,
)
from paper_data_suite.returned_paper_payload_audit import (
    InstalledPayloadAuditError,
    InstalledPayloadAuditV1,
    MatchedWheelPayloadV1,
)
from paper_data_suite.returned_paper_runtime_probe import (
    InstalledPaperRuntimeProbeV1,
    RuntimeProbeError,
    inspect_installed_paper_runtime,
)


def _valid_admission() -> PaperAdmissionV1:
    return PaperAdmissionV1(
        core_installed_version="0.6.6", core_state="exact_release_candidate",
        producers=(
            ProducerAdmissionV1(
                "scoreform", "0.13.0", "exact_release_candidate", "0.13.0"
            ),
            ProducerAdmissionV1(
                "quillan", "0.10.6", "exact_release_candidate", "0.10.6"
            ),
        ),
        runtime_platform="win32", runtime_python=(3, 11),
    )


def _valid_payload() -> InstalledPayloadAuditV1:
    return InstalledPayloadAuditV1(tuple(
        MatchedWheelPayloadV1(distribution, version, "a" * 64, 5)
        for distribution, version in (
            ("pds-core", "0.6.6"), ("scoreform", "0.13.0"),
            ("quillan", "0.10.6"),
        )
    ))


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Substitute observations only; they cannot produce dispatch permissions."""
    wheelhouse = tmp_path / "verified_wheels"
    wheelhouse.mkdir()
    monkeypatch.setattr(probe, "_isolated_supported_runtime", lambda: True)
    monkeypatch.setattr(probe, "inspect_paper_admission", _valid_admission)
    monkeypatch.setattr(probe, "audit_installed_paper_payloads", lambda _: (
        _valid_payload()
    ))
    monkeypatch.setattr(
        probe, "_native_versions_and_symbols",
        lambda: (
            ("pypdfium2", "5.15.2"),
            ("zxing-cpp", "2.3.0"),
            ("Pillow", "12.0.0"),
        ),
    )
    monkeypatch.setattr(
        probe, "qualify_installed_profiles",
        lambda: ("quillan", "scoreform"),
    )
    return wheelhouse


def test_exact_diagnostic_match_remains_preview_only(ready: Path) -> None:
    result = inspect_installed_paper_runtime(ready)
    assert result.status == "diagnostic_match"
    assert result.payload_matched
    assert result.native_contract_observed
    assert result.core_profiles_observed
    assert result.native_versions[0] == ("pypdfium2", "5.15.2")
    assert result.qualified_modules == frozenset()
    assert result.producer_dispatch_authorized is False
    assert result.processing_status == "preview_only"


def test_probe_result_cannot_grant_permissions(ready: Path) -> None:
    result = inspect_installed_paper_runtime(ready)
    with pytest.raises(RuntimeProbeError):
        replace(result, qualified_modules=frozenset({"scoreform"}))
    with pytest.raises(RuntimeProbeError):
        replace(result, producer_dispatch_authorized=True)  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        result.status = "payload_unverified"  # type: ignore[misc]


def test_non_isolated_runtime_short_circuits_all_probes(
    ready: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "_isolated_supported_runtime", lambda: False)
    monkeypatch.setattr(probe, "inspect_paper_admission", lambda: pytest.fail(
        "candidate inspection attempted on unsupported host"
    ))
    result = inspect_installed_paper_runtime(ready)
    assert result.status == "runtime_unqualified"
    assert not result.payload_matched


@pytest.mark.parametrize("case", [
    "missing_core", "missing_producer", "unexpected_processing_status",
    "fake_qualified_modules", "unavailable_observation", "malformed_observation",
])
def test_unqualified_candidate_refuses_without_wheel_or_native_work(
    ready: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    observed = _valid_admission()
    if case == "missing_core":
        observed = replace(observed, core_state="not_installed")
    elif case == "missing_producer":
        observed = replace(observed, producers=(
            observed.producers[0],
            replace(observed.producers[1], state="not_installed"),
        ))
    if case == "unavailable_observation":
        monkeypatch.setattr(probe, "inspect_paper_admission", lambda: 1 / 0)
    elif case == "malformed_observation":
        monkeypatch.setattr(probe, "inspect_paper_admission", lambda: object())
    elif case == "unexpected_processing_status":
        monkeypatch.setattr(probe, "inspect_paper_admission", lambda: (
            SimpleNamespace(processing_status="enabled")
        ))
    elif case == "fake_qualified_modules":
        monkeypatch.setattr(probe, "inspect_paper_admission", lambda: (
            SimpleNamespace(qualified_modules=frozenset({"scoreform"}))
        ))
    else:
        monkeypatch.setattr(probe, "inspect_paper_admission", lambda: observed)
    monkeypatch.setattr(probe, "audit_installed_paper_payloads", lambda _: (
        pytest.fail("payload audit ran without exact candidates")
    ))
    result = inspect_installed_paper_runtime(ready)
    assert result.status == "candidate_unqualified"
    assert not result.native_contract_observed


@pytest.mark.parametrize("case", [
    "unavailable", "wrong_wheel_set", "pretends_authorized", "malformed",
])
def test_payload_refusal_halts_before_imports(
    ready: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    def audit(_: Path) -> object:
        if case == "unavailable":
            raise InstalledPayloadAuditError("missing wheel")
        if case == "wrong_wheel_set":
            return SimpleNamespace(
                producer_dispatch_authorized=False,
                wheels=(SimpleNamespace(distribution="scoreform"),),
            )
        if case == "pretends_authorized":
            return SimpleNamespace(
                producer_dispatch_authorized=True,
                wheels=tuple(SimpleNamespace(distribution=x) for x in (
                    "pds-core", "scoreform", "quillan"
                )),
            )
        return SimpleNamespace(producer_dispatch_authorized=False, wheels=None)

    monkeypatch.setattr(probe, "audit_installed_paper_payloads", audit)
    monkeypatch.setattr(probe, "_native_versions_and_symbols", lambda: (
        pytest.fail("native import ran after payload refusal")
    ))
    result = inspect_installed_paper_runtime(ready)
    assert result.status == "payload_unverified"
    assert not result.payload_matched


@pytest.mark.parametrize("case", ["missing", "bad_range", "bad_symbol", "error"])
def test_native_refusal_halts_before_core_profile_import(
    ready: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    def native() -> tuple[tuple[str, str], ...]:
        if case == "missing":
            raise ModuleNotFoundError("pypdfium2")
        if case == "bad_range":
            raise RuntimeProbeError("native dependency version unqualified")
        if case == "bad_symbol":
            raise RuntimeProbeError("native dependency API unavailable")
        raise RuntimeError("private native loader exception")

    monkeypatch.setattr(probe, "_native_versions_and_symbols", native)
    monkeypatch.setattr(probe, "qualify_installed_profiles", lambda: (
        pytest.fail("producer import ran after native refusal")
    ))
    result = inspect_installed_paper_runtime(ready)
    assert result.status == "native_unverified"
    assert result.payload_matched
    assert not result.native_contract_observed


@pytest.mark.parametrize("kind", ["wrong_membership", "raised"])
def test_mismatched_core_registry_is_not_reported_as_qualified(
    ready: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    if kind == "wrong_membership":
        monkeypatch.setattr(
            probe, "qualify_installed_profiles", lambda: ("scoreform",)
        )
    else:
        def blocked() -> tuple[str, ...]:
            raise RuntimeError("unsupported Core profile")
        monkeypatch.setattr(probe, "qualify_installed_profiles", blocked)
    result = inspect_installed_paper_runtime(ready)
    assert result.status == "profiles_unverified"
    assert result.native_contract_observed
    assert not result.core_profiles_observed
    assert result.producer_dispatch_authorized is False


def test_native_contract_checks_exact_versions_and_callable_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = {"pypdfium2": "5.15.2", "zxing-cpp": "2.3.0", "Pillow": "12.0.0"}
    monkeypatch.setattr(probe.metadata, "version", good.__getitem__)
    names = {
        "pypdfium2": SimpleNamespace(PdfDocument=lambda _: None),
        "zxingcpp": SimpleNamespace(read_barcodes=lambda _: None),
        "PIL.Image": SimpleNamespace(open=lambda _: None),
    }
    monkeypatch.setattr(probe, "import_module", names.__getitem__)
    assert probe._native_versions_and_symbols() == tuple(good.items())


@pytest.mark.parametrize("bad_key,bad_version", [
    ("pypdfium2", "4.30.0"), ("pypdfium2", "6.0"),
    ("zxing-cpp", "2.2.0"), ("zxing-cpp", "3.0"),
    ("Pillow", "10.4.0"), ("Pillow", "13.0"),
])
def test_native_out_of_range_is_refused(
    monkeypatch: pytest.MonkeyPatch, bad_key: str, bad_version: str,
) -> None:
    versions = {"pypdfium2": "5.15.2", "zxing-cpp": "2.3.0", "Pillow": "12.0"}
    versions[bad_key] = bad_version
    monkeypatch.setattr(probe.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(probe, "import_module", lambda _: SimpleNamespace(
        PdfDocument=lambda: None, read_barcodes=lambda: None, open=lambda: None
    ))
    with pytest.raises(RuntimeProbeError, match="version unqualified"):
        probe._native_versions_and_symbols()


def test_native_import_missing_callable_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = {"pypdfium2": "5.15.2", "zxing-cpp": "2.3.0", "Pillow": "12.0"}
    monkeypatch.setattr(probe.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(probe, "import_module", lambda _: SimpleNamespace())
    with pytest.raises(RuntimeProbeError, match="API unavailable"):
        probe._native_versions_and_symbols()


@pytest.mark.parametrize("invalid", ["str", None, 1, ["/not/a/path"]])
def test_invalid_wheelhouse_is_refused_without_inspecting(
    invalid: object,
) -> None:
    with pytest.raises(RuntimeProbeError):
        inspect_installed_paper_runtime(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("case", ["no_payload", "no_native", "no_profile"])
def test_inconsistent_evidence_flags_are_rejected(case: str) -> None:
    data: dict[str, object] = {
        "status": "diagnostic_match", "payload_matched": True,
        "native_contract_observed": True, "core_profiles_observed": True,
        "native_versions": (
            ("pypdfium2", "5.15.2"), ("zxing-cpp", "2.3.0"),
            ("Pillow", "12.0.0"),
        ),
    }
    if case == "no_payload":
        data["payload_matched"] = False
    elif case == "no_native":
        data["native_contract_observed"] = False
    else:
        data["core_profiles_observed"] = False
    with pytest.raises(RuntimeProbeError):
        InstalledPaperRuntimeProbeV1(**data)  # type: ignore[arg-type]
