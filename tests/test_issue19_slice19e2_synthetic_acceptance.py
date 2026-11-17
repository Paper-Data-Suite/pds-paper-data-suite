"""#19E2: immutable synthetic PDF witness is not producer permission."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_data_suite.returned_paper_readonly_decode import (
    DecodedPage,
    DecoderBackendUnavailable,
)
from paper_data_suite.returned_paper_synthetic_acceptance import (
    FIXTURE_NAME,
    FIXTURE_SHA256,
    SyntheticAcceptanceError,
    SyntheticNativeWitnessV1,
    inspect_two_page_synthetic_fixture,
    render_synthetic_fixture_witness,
)

_FIXTURE = Path(__file__).parent / "fixtures" / FIXTURE_NAME
_PAYLOADS = (
    "PDS2|m=scoreform|c=english12_p4|w=essay|r=route_001",
    "PDS2|m=quillan|c=english12_p4|w=essay|r=route_002",
)


def _decoder(_data: bytes, _fmt: str, _limits: object):
    return tuple(DecodedPage((code,)) for code in _PAYLOADS)


def _parser(code: str):
    return SimpleNamespace(module_id=code.split("|", 2)[1][2:])


def _inspect(path: Path = _FIXTURE, **kwargs: object):
    return inspect_two_page_synthetic_fixture(
        path, decoder=kwargs.get("decoder", _decoder),  # type: ignore[arg-type]
        parse=kwargs.get("parse", _parser),  # type: ignore[arg-type]
    )


def test_fixture_bytes_and_no_personal_data() -> None:
    content = _FIXTURE.read_bytes()
    assert content.startswith(b"%PDF-")
    assert 1024 < len(content) < 1_048_576
    assert hashlib.sha256(content).hexdigest() == FIXTURE_SHA256
    assert b"PRIVATE" not in content and b"student_id" not in content


def test_good_two_physical_pages_never_admit_dispatch() -> None:
    before = _FIXTURE.read_bytes()
    witness = _inspect()
    assert witness.status == "native_verified"
    assert witness.verified_pages == 2
    assert witness.verified_owners == ("scoreform", "quillan")
    assert witness.qualified_modules == frozenset()
    assert witness.producer_dispatch_authorized is False
    assert witness.processing_status == "preview_only"
    assert _FIXTURE.read_bytes() == before


def test_renderer_reports_page_order_without_raw_qr_or_paths() -> None:
    output = render_synthetic_fixture_witness(_inspect())
    assert "Physical page owners: 1 scoreform; 2 quillan" in output
    assert "NEVER" in output and "No Core retention" in output
    assert "PDS2|" not in output and str(_FIXTURE) not in output


@pytest.mark.parametrize("failure", [
    "empty", "one", "three", "wrong_owner", "reversed", "duplicate",
    "extra_payload", "missing_qr", "truncated", "failed", "wrong_type",
    "list_type", "decoder_raise", "invalid_format",
])
def test_malformed_native_observations_fail_closed(failure: str) -> None:
    def invalid(data: bytes, fmt: str, limits: object):
        if failure == "decoder_raise":
            raise RuntimeError("PRIVATE classroom")
        if failure == "empty":
            return ()
        if failure == "one":
            return (DecodedPage((_PAYLOADS[0],)),)
        if failure == "three":
            return _decoder(data, fmt, limits) + (DecodedPage(),)
        if failure == "wrong_owner":
            return (DecodedPage((_PAYLOADS[0].replace("scoreform", "portia"),)),
                    DecodedPage((_PAYLOADS[1],)))
        if failure == "reversed":
            return tuple(reversed(_decoder(data, fmt, limits)))
        if failure == "duplicate":
            return (DecodedPage((_PAYLOADS[0],)), DecodedPage((_PAYLOADS[0],)))
        if failure == "extra_payload":
            return (DecodedPage((_PAYLOADS[0], "ANOTHER")),
                    DecodedPage((_PAYLOADS[1],)))
        if failure == "missing_qr":
            return (DecodedPage(), DecodedPage((_PAYLOADS[1],)))
        if failure == "truncated":
            return (DecodedPage((_PAYLOADS[0],), truncated=True),
                    DecodedPage((_PAYLOADS[1],)))
        if failure == "failed":
            return (DecodedPage(failed=True), DecodedPage((_PAYLOADS[1],)))
        if failure == "wrong_type":
            return (object(), DecodedPage((_PAYLOADS[1],)))
        if failure == "list_type":
            return list(_decoder(data, fmt, limits))
        if failure == "invalid_format":
            assert fmt == "pdf"
            return "bad"
        raise AssertionError("unrecognized fixture failure")

    witness = _inspect(decoder=invalid)
    assert witness.status == "decode_mismatch"
    assert witness.verified_pages == 0 and not witness.verified_owners
    assert witness.qualified_modules == frozenset()


def test_missing_native_backend_is_a_refusal_not_silent_skip() -> None:
    def unavailable(*_: object):
        raise DecoderBackendUnavailable("SECRET native detail")

    witness = _inspect(decoder=unavailable)
    assert witness.status == "backend_unavailable"
    assert "SECRET" not in render_synthetic_fixture_witness(witness)


@pytest.mark.parametrize("path", [
    Path("relative/issue19_two_page_synthetic_pds2.pdf"),
    Path("/not-the-fixture.pdf"),
    Path("/missing/issue19_two_page_synthetic_pds2.pdf"),
])
def test_invalid_explicit_fixture_paths_refuse_without_decoder(path: Path) -> None:
    def forbidden(*_: object):
        pytest.fail("decoder called for invalid fixture")

    outcome = _inspect(path, decoder=forbidden)
    assert outcome.status == "fixture_invalid"


def test_mutated_fixture_bytes_refuse_without_native_call(tmp_path: Path) -> None:
    copied = tmp_path / FIXTURE_NAME
    copied.write_bytes(_FIXTURE.read_bytes() + b"corrupt")

    def forbidden(*_: object):
        pytest.fail("decoder called for digest mismatch")

    outcome = _inspect(copied, decoder=forbidden)
    assert outcome.status == "fixture_invalid"


def test_wrong_parser_owner_or_parser_error_refuses() -> None:
    assert _inspect(parse=lambda _: object()).status == "decode_mismatch"

    def broken(_: str):
        raise RuntimeError("PRIVATE student ID")

    result = _inspect(parse=broken)
    assert result.status == "decode_mismatch"
    assert "PRIVATE" not in render_synthetic_fixture_witness(result)


def test_fake_authorization_cannot_be_constructed() -> None:
    observed = _inspect()
    with pytest.raises(SyntheticAcceptanceError):
        replace(observed, qualified_modules=frozenset({"scoreform"}))
    with pytest.raises(SyntheticAcceptanceError):
        replace(observed, producer_dispatch_authorized=True)  # type: ignore[arg-type]
    with pytest.raises(SyntheticAcceptanceError):
        replace(observed, processing_status="active")  # type: ignore[arg-type]
    with pytest.raises(SyntheticAcceptanceError):
        SyntheticNativeWitnessV1("native_verified", 1, ("scoreform",))
    with pytest.raises(SyntheticAcceptanceError):
        SyntheticNativeWitnessV1("decode_mismatch", 2, ("scoreform", "quillan"))
    with pytest.raises(FrozenInstanceError):
        observed.status = "fixture_invalid"  # type: ignore[misc]


def test_no_handler_modules_imported_during_synthetic_fixture_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def guarded(name: str, *args: object, **kwargs: object):
        if name in {
            "scoreform", "quillan", "pds_core.module_dispatch",
            "paper_data_suite.returned_paper_ordered_dispatch",
        }:
            pytest.fail("synthetic witness imported a producer/dispatch module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert _inspect().status == "native_verified"


def test_renderer_rejects_untyped_results() -> None:
    with pytest.raises(SyntheticAcceptanceError):
        render_synthetic_fixture_witness(object())  # type: ignore[arg-type]


def test_synthetic_pdf_is_two_pages_when_pdfium_is_available() -> None:
    pdfium = pytest.importorskip("pypdfium2")
    document = pdfium.PdfDocument(_FIXTURE.read_bytes())
    try:
        assert len(document) == 2
    finally:
        document.close()


@pytest.mark.parametrize("ready,native,exit_code", [
    (True, True, 0), (True, False, 1), (False, True, 1), (False, False, 1),
])
def test_explicit_cli_requires_both_non_authorizing_checks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    ready: bool, native: bool, exit_code: int,
) -> None:
    import sys
    from types import ModuleType

    from paper_data_suite import returned_paper_synthetic_acceptance as accept

    mock = ModuleType("paper_data_suite.returned_paper_action_time_readiness")
    setattr(
        mock, "inspect_paper_action_time_readiness",
        lambda _: SimpleNamespace(
            status=(
                "diagnostic_match_not_admitted" if ready
                else "candidate_unqualified"
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules, "paper_data_suite.returned_paper_action_time_readiness", mock,
    )
    monkeypatch.setattr(
        accept, "inspect_two_page_synthetic_fixture",
        lambda _: (
            SyntheticNativeWitnessV1("native_verified", 2, ("scoreform", "quillan"))
            if native else SyntheticNativeWitnessV1("backend_unavailable")
        ),
    )
    assert accept.main([
        "--fixture", str(_FIXTURE), "--wheelhouse", str(tmp_path)
    ]) == exit_code
    text = capsys.readouterr().out
    assert "No teacher dispatch is enabled" in text
    assert "Exact installed-runtime diagnostic match: " in text
    assert str(tmp_path) not in text
    assert "PDS2|" not in text
