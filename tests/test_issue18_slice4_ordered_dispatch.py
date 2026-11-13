"""#18 Slice 4: real Core outcome types, isolated producer boundaries."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

import pytest
from pds_core.module_dispatch import (
    ModuleRouteHandlingError,
    RouteDispatchFailure,
    RouteDispatchRequest,
    RouteDispatchSuccess,
)
from pds_core.module_profiles import (
    ModuleProfile,
    ModuleRegistry,
    UnsupportedModuleError,
)
from pds_core.routing_models import (
    ModuleRecordRef,
    RouteRegistration,
    RouteResolution,
)

from paper_data_suite.returned_paper_authorized_retention import (
    AuthorizedRetentionResultV1,
    RetentionDecisionV1,
    authorize_and_retain_sources,
)
from paper_data_suite.returned_paper_ordered_dispatch import (
    DispatchDecisionV1,
    OrderedDispatchError,
    count_ordered_dispatch_groups,
    execute_prepared_paper_batch,
)
from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    PagePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_processing_contract import (
    PaperProcessingPlanV1,
    build_processing_plan,
    count_processing_outcomes,
)
from paper_data_suite.returned_paper_readonly_decode import (
    DecodedPage,
    DecodeLimits,
)
from paper_data_suite.returned_paper_retained_requests import (
    PreparedDispatchBatchV1,
    prepare_retained_pds2_requests,
)


def _code(module: str, route: str = "route_001") -> str:
    return f"PDS2|m={module}|c=english12_p4|w=essay|r={route}"


def _preview(pages: tuple[DecodedPage, ...]) -> tuple[PagePreview, ...]:
    results: list[PagePreview] = []
    for number, page in enumerate(pages, 1):
        values = tuple(dict.fromkeys(page.payloads))
        if page.failed:
            results.append(PagePreview(number, "page_decode_failed"))
        elif page.truncated or len(values) > 1:
            results.append(PagePreview(number, "ambiguous_qr"))
        elif not values:
            results.append(PagePreview(number, "missing_qr"))
        elif values[0].startswith("PDS2|m=") and len(values[0]) < 256:
            module = values[0].split("|", 2)[1][2:]
            results.append(PagePreview(number, "candidate_unverified", module))
        else:
            results.append(PagePreview(number, "invalid_or_foreign_qr"))
    return tuple(results)


def _case(
    tmp_path: Path,
    page_sets: tuple[tuple[DecodedPage, ...], ...] | None = None,
    selected: tuple[tuple[int, int], ...] | None = None,
) -> tuple[
    AuthorizedRetentionResultV1,
    Callable[[bytes, str, DecodeLimits], tuple[DecodedPage, ...]],
    tuple[Path, ...],
]:
    if page_sets is None:
        page_sets = ((
            DecodedPage((_code("scoreform"),)), DecodedPage(),
        ),)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    originals = tmp_path / "originals"
    originals.mkdir()
    paths: list[Path] = []
    snapshots: list[SourcePreview] = []
    content_to_pages: dict[bytes, tuple[DecodedPage, ...]] = {}
    for number, pages in enumerate(page_sets, 1):
        path = originals / f"source_{number}.pdf"
        data = f"%PDF-1.4\n% synthetic source {number}\n".encode("ascii")
        path.write_bytes(data)
        paths.append(path)
        content_to_pages[data] = pages
        snapshots.append(SourcePreview(
            number, "observed", _preview(pages), hashlib.sha256(data).hexdigest(),
        ))
    if selected is None:
        selected = tuple(
            (i, n) for i, pages in enumerate(page_sets, 1)
            for n in range(1, len(pages) + 1)
        )
    plan: PaperProcessingPlanV1 = build_processing_plan(
        workspace, tuple(paths), IntakePreview(tuple(snapshots), ()), selected,
    )

    def observe(chosen: tuple[Path, ...]) -> tuple[SourcePreview, ...]:
        return tuple(
            SourcePreview(
                n, "observed", snapshots[paths.index(path)].pages,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for n, path in enumerate(chosen, 1)
        )

    def approve(review):
        return RetentionDecisionV1("approve", review.plan_digest, review.challenge)

    retained = authorize_and_retain_sources(plan, approve=approve, observe=observe)
    assert retained.status == "retained"

    def decode(data: bytes, _format: str, _limits: DecodeLimits):
        return content_to_pages[data]

    return retained, decode, tuple(paths)


def _batch(
    root: Path,
    modules: tuple[str, ...] = ("scoreform", "quillan"),
) -> tuple[
    PreparedDispatchBatchV1,
    Callable[[bytes, str, DecodeLimits], tuple[DecodedPage, ...]],
]:
    retention, decode, _ = _case(root, ((tuple(
        DecodedPage((_code(module, f"route_{i}"),))
        for i, module in enumerate(modules, 1)
    )),))
    batch = prepare_retained_pds2_requests(retention, decode=decode)
    assert batch.status == "ready"
    return batch, decode


def _approve(review):
    assert review.producer_handlers_may_write is True
    assert review.retained_sources_are_immutable is True
    assert review.selected_pages
    return DispatchDecisionV1("approve", review.plan_digest, review.challenge)


def _profile(module: str) -> ModuleProfile:
    return ModuleProfile(
        module_id=module,
        display_name=module.title(),
        supported_core_routing_contract_versions=frozenset({"1"}),
        supported_qr_schemas=frozenset({"PDS2"}),
        supported_route_registration_schema_versions=frozenset({"1"}),
        dispatchable_route_statuses=frozenset({"active"}),
        route_handler=lambda *_args: None,
    )


def _registry() -> ModuleRegistry:
    return ModuleRegistry((_profile("scoreform"), _profile("quillan")))


def _success(
    req: RouteDispatchRequest,
    registry: ModuleRegistry,
    root: Path,
    *,
    secret: object = None,
) -> RouteDispatchSuccess:
    locator = req.locator
    reg = RouteRegistration(
        schema_version="1",
        locator=locator,
        target=ModuleRecordRef(locator.module_id, "answer_sheet_page", "record_1", "1"),
        created_at="2026-11-11T12:00:00+00:00",
        status="active",
        human_fallback="synthetic test page",
        module_details={},
    )
    class_root = root / "classes" / locator.class_id
    module_root = class_root / "modules" / locator.module_id
    work_root = module_root / "work" / locator.work_id
    resolution = RouteResolution(
        locator, reg, class_root, module_root, work_root
    )
    return RouteDispatchSuccess(
        req, registry.require(locator.module_id), resolution, secret,
    )


def _dispatch_success(root: Path, registry: ModuleRegistry, reqs):
    assert len(reqs) == 1
    return (_success(reqs[0], registry, root),)


def test_approved_batch_runs_one_real_core_typed_request_per_page(
    tmp_path: Path,
) -> None:
    batch, decode = _batch(tmp_path)
    calls: list[str] = []

    def dispatch(root, registry, reqs):
        calls.append(reqs[0].locator.module_id)
        return _dispatch_success(root, registry, reqs)

    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=dispatch,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "completed" and result.approved
    assert result.attempted_pages == 2
    assert calls == ["scoreform", "quillan"]
    assert count_processing_outcomes(result.report) == (("handler_returned", 2),)
    groups = count_ordered_dispatch_groups(result)
    assert sum(group.count for group in groups) == 2
    assert {group.module_id for group in groups} == {"scoreform", "quillan"}
    assert all(group.class_id == "english12_p4" for group in groups)


def test_expected_failure_isolated_success_failure_success(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path, ("scoreform", "portia", "quillan"))
    called: list[str] = []

    def dispatch(root, registry, requests):
        request = requests[0]
        module = request.locator.module_id
        called.append(module)
        if module == "portia":
            return (RouteDispatchFailure(
                request, UnsupportedModuleError("no published profile"),
            ),)
        return (_success(request, registry, root),)

    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=dispatch,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "partial" and result.attempted_pages == 2
    assert called == ["scoreform", "quillan"]
    assert [p.status for p in result.report.sources[0].pages] == [
        "handler_returned", "module_unqualified", "handler_returned",
    ]
    assert result.report.sources[0].pages[1].failure_category is None


def test_handler_failure_is_uncertain_but_other_pages_continue(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    called: list[int] = []

    def dispatch(root, registry, reqs):
        req = reqs[0]
        called.append(req.source_page_number)
        if req.source_page_number == 1:
            return (RouteDispatchFailure(req, ModuleRouteHandlingError("internal")),)
        return (_success(req, registry, root),)

    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=dispatch,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "uncertain"
    assert called == [1, 2]
    assert [p.status for p in result.report.sources[0].pages] == [
        "uncertain", "handler_returned",
    ]
    assert result.report.sources[0].pages[0].failure_category == "processing_error"


def test_unexpected_handler_escape_stops_with_unattempted_pages(
    tmp_path: Path,
) -> None:
    batch, decode = _batch(tmp_path, ("scoreform", "quillan", "scoreform"))
    called: list[int] = []

    def dispatch(root, registry, requests):
        req = requests[0]
        called.append(req.source_page_number)
        if req.source_page_number == 2:
            raise RuntimeError("secret student payload")
        return (_success(req, registry, root),)

    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=dispatch,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "uncertain" and result.attempted_pages == 2
    assert called == [1, 2]
    assert [p.status for p in result.report.sources[0].pages] == [
        "handler_returned", "uncertain", "not_attempted",
    ]
    assert "secret student payload" not in repr(result)


def test_cancel_requires_no_registry_or_handlers(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    calls: list[str] = []
    result = execute_prepared_paper_batch(
        batch, decode=decode,
        approve=lambda r: DispatchDecisionV1(
            "cancel", r.plan_digest, r.challenge,
        ),
        registry_factory=lambda: calls.append("factory"),  # type: ignore[arg-type]
        dispatcher=lambda *_args: calls.append("dispatch"),  # type: ignore[arg-type]
    )
    assert result.status == "cancelled" and result.attempted_pages == 0
    assert calls == []
    assert [p.status for p in result.report.sources[0].pages] == [
        "not_attempted", "not_attempted",
    ]


@pytest.mark.parametrize("bad", ["digest", "challenge", "type", "raise"])
def test_bad_approval_never_creates_registry(tmp_path: Path, bad: str) -> None:
    batch, decode = _batch(tmp_path)
    calls: list[str] = []

    def approve(review):
        if bad == "type":
            return True
        if bad == "raise":
            raise RuntimeError("private teacher path")
        if bad == "digest":
            return DispatchDecisionV1("approve", "0" * 64, review.challenge)
        return DispatchDecisionV1("approve", review.plan_digest, "wrong")

    result = execute_prepared_paper_batch(
        batch, decode=decode, approve=approve,
        registry_factory=lambda: calls.append("factory"),  # type: ignore[arg-type]
    )
    assert result.status == "cancelled"
    assert calls == []


def test_retained_tampering_before_consent_blocks(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    retained = batch.report.sources[0].retained_source
    assert retained is not None
    retained.retained_source_path.write_bytes(b"%PDF-1.4\n% tampered\n")
    calls: list[str] = []
    result = execute_prepared_paper_batch(
        batch, decode=decode,
        approve=lambda r: calls.append("approved"),  # type: ignore[arg-type]
        registry_factory=_registry,
    )
    assert result.status == "blocked" and result.reason == "retained_changed"
    assert calls == []
    assert all(p.status == "not_attempted" for p in result.report.sources[0].pages)


def test_retained_mutation_during_approval_blocks_before_registry(
    tmp_path: Path,
) -> None:
    batch, decode = _batch(tmp_path)
    retained = batch.report.sources[0].retained_source
    assert retained is not None
    calls: list[str] = []

    def approve(review):
        retained.retained_source_path.write_bytes(b"%PDF-1.4\n% tampered\n")
        return _approve(review)

    result = execute_prepared_paper_batch(
        batch, approve=approve, decode=decode,
        registry_factory=lambda: calls.append("factory"),  # type: ignore[arg-type]
    )
    assert result.status == "blocked"
    assert result.approved
    assert calls == []


def test_bad_registry_refuses_before_any_handler(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    calls: list[str] = []

    def bad_registry():
        calls.append("registry")
        raise RuntimeError("provider bug")

    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=bad_registry,
        dispatcher=lambda *_args: calls.append("dispatch"),  # type: ignore[arg-type]
    )
    assert result.status == "blocked" and result.reason == "registry_unavailable"
    assert calls == ["registry"]


def test_wrong_registry_type_refused(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=lambda: {},  # type: ignore[arg-type]
    )
    assert result.status == "blocked" and result.reason == "registry_unavailable"


def test_wrong_core_outcome_shape_is_uncertain(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        qualified_modules=frozenset({"scoreform", "quillan"}),
        dispatcher=lambda *_args: (),
    )
    assert result.status == "uncertain"
    assert result.attempted_pages == 1
    assert result.report.sources[0].pages[0].status == "uncertain"
    assert result.report.sources[0].pages[1].status == "not_attempted"


def test_wrong_core_request_identity_is_uncertain(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    request = batch.candidates[1].request

    def wrong(_root, _reg, _reqs):
        return (RouteDispatchFailure(
            request, UnsupportedModuleError("other request"),
        ),)

    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=wrong,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "uncertain" and result.attempted_pages == 1


def test_post_handler_retained_tamper_blocks_next_attempt(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    retained = batch.report.sources[0].retained_source
    assert retained is not None
    invoked: list[int] = []

    def dispatch(root, registry, reqs):
        req = reqs[0]
        invoked.append(req.source_page_number)
        retained.retained_source_path.write_bytes(b"%PDF-1.4\n% tampered\n")
        return (_success(req, registry, root),)

    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=dispatch,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "uncertain" and result.attempted_pages == 1
    assert invoked == [1]
    assert [p.status for p in result.report.sources[0].pages] == [
        "handler_returned", "not_attempted",
    ]


def test_unresolved_physical_pages_remain_unrouted(tmp_path: Path) -> None:
    retention, decoder, _ = _case(tmp_path, ((
        DecodedPage((_code("scoreform"),)), DecodedPage(),
    ),))
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decoder,
        registry_factory=_registry, dispatcher=_dispatch_success,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "completed"
    assert [p.status for p in result.report.sources[0].pages] == [
        "handler_returned", "unresolved_qr",
    ]
    groups = count_ordered_dispatch_groups(result)
    assert sum(item.count for item in groups) == 2
    unresolved = next(row for row in groups if row.status == "unresolved_qr")
    assert unresolved.module_id is None


def test_no_routes_requires_no_approval(tmp_path: Path) -> None:
    retention, decoder, _ = _case(tmp_path, ((DecodedPage(),),))
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    assert batch.status == "no_dispatchable_pages"
    result = execute_prepared_paper_batch(
        batch, decode=decoder, approve=lambda r: 1,  # type: ignore[arg-type]
    )
    assert result.status == "no_requests" and not result.approved
    assert result.attempted_pages == 0


def test_reject_unready_and_malformed_arguments(tmp_path: Path) -> None:
    batch, decoder = _batch(tmp_path)
    with pytest.raises(OrderedDispatchError):
        execute_prepared_paper_batch(
            batch, decode=decoder, approve=None,  # type: ignore[arg-type]
        )
    with pytest.raises(OrderedDispatchError):
        execute_prepared_paper_batch(
            batch, decode=decoder, approve=_approve,
            limits=3,  # type: ignore[arg-type]
        )


def test_success_module_result_is_never_serialized(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    secret = {"private_student_id": "hidden-student-42"}

    def dispatch(root, registry, requests):
        return (_success(requests[0], registry, root, secret=secret),)

    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=dispatch,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "completed"
    assert "hidden-student-42" not in repr(result)
    assert "hidden-student-42" not in repr(count_ordered_dispatch_groups(result))


def test_real_core_dispatch_routes_with_synthetic_persisted_registrations(
    tmp_path: Path,
) -> None:
    """Exercise Core's public registry, exclusive routes and dispatch together."""
    from pds_core.route_registrations import write_route_registration

    batch, decode = _batch(tmp_path)
    root = batch.report.plan.workspace_root
    invoked: list[tuple[str, int]] = []

    def make_profile(module: str) -> ModuleProfile:
        def handle(resolution, _receipt, number):
            invoked.append((resolution.locator.module_id, number))
            return {"private_result": "not copied to Suite"}

        return ModuleProfile(
            module_id=module,
            display_name=module.title(),
            supported_core_routing_contract_versions=frozenset({"1"}),
            supported_qr_schemas=frozenset({"PDS2"}),
            supported_route_registration_schema_versions=frozenset({"1"}),
            dispatchable_route_statuses=frozenset({"active"}),
            route_handler=handle,
        )

    profiles = (make_profile("scoreform"), make_profile("quillan"))
    registry = ModuleRegistry(profiles)
    for candidate in batch.candidates:
        locator = candidate.request.locator
        write_route_registration(root, RouteRegistration(
            schema_version="1", locator=locator,
            target=ModuleRecordRef(locator.module_id, "response_page", "page_1", "1"),
            created_at="2026-11-11T12:00:00+00:00",
            status="active", human_fallback="Synthetic returned page",
            module_details={},
        ))

    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=lambda: registry,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "completed"
    assert invoked == [("scoreform", 1), ("quillan", 2)]
    assert "not copied to Suite" not in repr(result)


def test_default_qualification_is_no_producer_execution(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    invoked: list[int] = []
    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        dispatcher=lambda *_args: invoked.append(1),  # type: ignore[arg-type]
    )
    assert result.status == "partial" and result.approved
    assert result.attempted_pages == 0 and not invoked
    assert [p.status for p in result.report.sources[0].pages] == [
        "module_unqualified", "module_unqualified",
    ]


@pytest.mark.parametrize("ids", [
    frozenset({"concord"}), frozenset({"vitrine"}),
    frozenset({"portia"}), frozenset({"meridian"}),
    {"scoreform"}, frozenset({42}),
])
def test_unqualified_or_malformed_module_set_refused_before_consent(
    tmp_path: Path, ids: object,
) -> None:
    batch, decode = _batch(tmp_path)
    invoked: list[str] = []
    with pytest.raises(OrderedDispatchError):
        execute_prepared_paper_batch(
            batch,
            approve=lambda r: invoked.append("approval"),  # type: ignore[arg-type]
            decode=decode, qualified_modules=ids,  # type: ignore[arg-type]
        )
    assert not invoked


def test_actual_core_missing_registration_isolated_from_later_page(
    tmp_path: Path,
) -> None:
    from pds_core.route_registrations import write_route_registration

    batch, decode = _batch(tmp_path)
    root = batch.report.plan.workspace_root
    later = batch.candidates[1].request.locator
    write_route_registration(root, RouteRegistration(
        schema_version="1", locator=later,
        target=ModuleRecordRef("quillan", "response_page", "page_2", "1"),
        created_at="2026-11-11T12:00:00+00:00",
        status="active", human_fallback="Synthetic returned page",
        module_details={},
    ))
    result = execute_prepared_paper_batch(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.status == "partial"
    assert [p.status for p in result.report.sources[0].pages] == [
        "dispatch_failed", "handler_returned",
    ]
