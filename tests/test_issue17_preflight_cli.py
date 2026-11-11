"""Suite #17 Slice 4: one compact observation stage, never paper processing."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from paper_data_suite.returned_paper_preflight import (
    build_readonly_preflight,
    render_readonly_preflight,
    run_readonly_papers_preview,
)
from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    ModuleRoutingPreview,
    PagePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_routing_preflight import RoutingInventory

_DEF_ROWS = (
    ModuleRoutingPreview("scoreform", "declared_unvalidated"),
    ModuleRoutingPreview("quillan", "declared_unvalidated"),
    ModuleRoutingPreview("concord", "declared_unvalidated"),
    ModuleRoutingPreview("meridian", "not_declared"),
    ModuleRoutingPreview("vitrine", "declared_unvalidated"),
    ModuleRoutingPreview("portia", "not_declared"),
)


def _routing() -> RoutingInventory:
    return RoutingInventory(_DEF_ROWS, True)


def _sample() -> IntakePreview:
    return IntakePreview(
        (
            SourcePreview(1, "observed", (
                PagePreview(1, "candidate_unverified", "quillan"),
                PagePreview(2, "missing_qr"),
                PagePreview(3, "candidate_unverified", "scoreform"),
                PagePreview(4, "ambiguous_qr"),
            )),
            SourcePreview(2, "backend_unavailable"),
        ),
        _DEF_ROWS,
    )


def test_build_consumes_only_injected_readers_and_never_processes() -> None:
    calls: list[str] = []
    files = (Path("one.pdf"), Path("two.jpg"))

    def observe(paths: tuple[Path, ...]) -> tuple[SourcePreview, ...]:
        assert paths == files
        calls.append("observe")
        return _sample().sources

    def inspect() -> RoutingInventory:
        calls.append("metadata")
        return _routing()

    preview = build_readonly_preflight(files, observe=observe, routing=inspect)
    assert calls == ["observe", "metadata"]
    assert preview.processing_performed is False
    assert len(preview.routing) == 6
    assert not hasattr(preview, "authorized_to_dispatch")


@pytest.mark.parametrize("bad", [(), ("file.pdf",), [Path("file.pdf")]])
def test_explicit_path_tuple_required(bad: object) -> None:
    with pytest.raises(ValueError):
        build_readonly_preflight(bad)  # type: ignore[arg-type]


def test_compact_output_is_path_free_and_unambiguous() -> None:
    report = render_readonly_preflight(_sample())
    assert "Sources: 2 selected, 1 observed, 1 unavailable/unsupported" in report
    assert (
        "Physical pages observed: 4; candidate pages: 2; "
        "other pages needing attention: 2"
    ) in report
    assert "Source 2: scanner dependency unavailable" in report
    assert "Physical page 1: candidate quillan — registration not checked" in report
    assert "Physical page 4: multiple/conflicting QR observations" in report
    assert "quillan: 1" in report
    assert "meridian: no routing declaration" in report
    assert "routing declared, unvalidated" in report
    assert "STOP — no scans retained" in report
    assert "no routing or scoring occurred" in report
    for secret in (
        "C:\\Private\\Student", "pds-core", "PDS2|", "class_a", "rt_",
        "Source 2: C:",
    ):
        assert secret not in report


def test_output_is_deterministic() -> None:
    assert render_readonly_preflight(_sample()) == render_readonly_preflight(_sample())


def test_issue_first_page_selection_keeps_physical_order_and_bounds() -> None:
    pages = tuple(
        PagePreview(i, "missing_qr" if i >= 50 else "candidate_unverified",
                    None if i >= 50 else "concord")
        for i in range(1, 65)
    )
    preview = IntakePreview(
        (SourcePreview(1, "observed", pages),), _DEF_ROWS
    )
    text = render_readonly_preflight(preview)
    assert "Physical pages observed: 64; candidate pages: 49; " in text
    assert "Physical page 50: no QR decoded" in text
    assert "Physical page 61: no QR decoded" in text
    assert "Physical page 49:" not in text
    assert "additional page(s) omitted" in text
    lines = [line for line in text.splitlines() if "Physical page " in line]
    numbers = [int(line.split("Physical page ")[1].split(":")[0]) for line in lines]
    assert numbers == sorted(numbers)
    assert len(lines) <= 16


def test_registration_observation_remains_non_authorizing() -> None:
    preview = IntakePreview((SourcePreview(1, "observed", (
        PagePreview(1, "candidate_unverified", "quillan", "structurally_consistent"),
    )),), _DEF_ROWS)
    text = render_readonly_preflight(preview)
    assert "structural registration check only" in text
    assert "Actual processing requires a separate" in text
    assert "STOP — no scans retained" in text


def test_no_candidates_is_normal_observation_not_processing() -> None:
    preview = IntakePreview(
        (SourcePreview(1, "observed", (PagePreview(1, "missing_qr"),)),),
        _DEF_ROWS,
    )
    assert "Candidate module counts (not accepted/processed):\n  None" in (
        render_readonly_preflight(preview)
    )


def test_runner_returns_nonzero_on_missing_backend_but_provides_report() -> None:
    output = StringIO()
    errors = StringIO()
    outcome = run_readonly_papers_preview(
        (Path("selected.pdf"),),
        observe=lambda _: (SourcePreview(1, "backend_unavailable"),),
        routing=_routing,
        output=output,
        errors=errors,
    )
    assert outcome == 1
    assert "Source 1: scanner dependency unavailable" in output.getvalue()
    assert "no scans retained" in output.getvalue()
    assert not errors.getvalue()


def test_runner_returns_zero_for_valid_preview_with_attention() -> None:
    output = StringIO()
    result = run_readonly_papers_preview(
        (Path("selected.png"),),
        observe=lambda _: (SourcePreview(
            1, "observed", (PagePreview(1, "missing_qr"),)
        ),),
        routing=_routing,
        output=output,
    )
    assert result == 0
    assert "other pages needing attention: 1" in output.getvalue()


def test_failed_routing_inventory_is_not_silent_success() -> None:
    output = StringIO()
    result = run_readonly_papers_preview(
        (Path("selected.png"),),
        observe=lambda _: (SourcePreview(
            1, "observed", (PagePreview(1, "missing_qr"),)
        ),),
        routing=lambda: RoutingInventory(
            tuple(
                replace(row, metadata_status="inspection_unavailable")
                for row in _DEF_ROWS
            ),
            False,
        ),
        output=output,
    )
    assert result == 1
    assert "routing metadata unavailable" in output.getvalue()


def test_provider_and_parser_failures_do_not_leak_sensitive_exceptions() -> None:
    out = StringIO()
    err = StringIO()

    def broken(_: tuple[Path, ...]) -> tuple[SourcePreview, ...]:
        raise RuntimeError("C:/private/student/someone.pdf raw: PDS2|m=quillan")

    code = run_readonly_papers_preview(
        (Path("c:/private/student/someone.pdf"),),
        observe=broken,
        routing=_routing,
        output=out,
        errors=err,
    )
    assert code == 1
    assert "preflight unavailable; no processing was performed" in err.getvalue()
    assert "someone" not in err.getvalue()
    assert "PDS2|" not in err.getvalue()
    assert not out.getvalue()


def test_preflight_never_calls_profile_diagnostics_or_registration() -> None:
    touched: list[str] = []

    def observe(_: tuple[Path, ...]) -> tuple[SourcePreview, ...]:
        return (
            SourcePreview(
                1,
                "observed",
                (PagePreview(1, "candidate_unverified", "portia"),),
            ),
        )

    def inspect() -> RoutingInventory:
        return _routing()

    preview = build_readonly_preflight(
        (Path("something.pdf"),), observe=observe, routing=inspect,
    )
    assert not touched
    assert preview.sources[0].pages[0].candidate_module_id == "portia"
    assert "portia: no routing declaration" in render_readonly_preflight(preview)


def test_source_observer_sees_exact_explicit_paths_only() -> None:
    seen: list[tuple[Path, ...]] = []
    inputs = (Path("selected.pdf"),)

    def observe(paths: tuple[Path, ...]) -> tuple[SourcePreview, ...]:
        seen.append(paths)
        return (SourcePreview(1, "unsupported_format"),)

    build_readonly_preflight(inputs, observe=observe, routing=_routing)
    assert seen == [inputs]


def test_cli_has_explicit_nested_preview_and_does_not_change_home() -> None:
    from paper_data_suite import cli

    parser = cli.build_parser()
    args = parser.parse_args(("papers", "preview", "--source", "one.pdf"))
    assert args.command == "papers"
    assert args.papers_command == "preview"
    assert args.source == [Path("one.pdf")]
    no_arg = parser.parse_args(())
    assert no_arg.command is None
    with pytest.raises(SystemExit) as problem:
        parser.parse_args(("papers", "preview"))
    assert problem.value.code == 2


def test_cli_deliberate_preview_delegates_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import cli
    from paper_data_suite import returned_paper_preflight as module

    seen: list[tuple[Path, ...]] = []

    def synthetic(paths: tuple[Path, ...]) -> int:
        seen.append(paths)
        return 0

    monkeypatch.setattr(module, "run_readonly_papers_preview", synthetic)
    assert cli.main((
        "papers", "preview", "--source", "one.pdf", "--source", "two.jpg"
    )) == 0
    assert seen == [(Path("one.pdf"), Path("two.jpg"))]


def test_cli_parent_help_does_not_execute_preflight(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from paper_data_suite import cli
    from paper_data_suite import returned_paper_preflight as module

    def prohibited(_: tuple[Path, ...]) -> int:
        raise AssertionError("preview executed without explicit selected source")

    monkeypatch.setattr(module, "run_readonly_papers_preview", prohibited)
    assert cli.main(("papers",)) == 0
    captured = capsys.readouterr()
    assert "preview" in captured.out
