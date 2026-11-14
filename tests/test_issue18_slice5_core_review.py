"""#18 Slice 5: real Core v2 occurrence/review and no replay evidence."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from pds_core.module_dispatch import (
    ModuleRouteHandlingError,
    RouteDispatchFailure,
)
from pds_core.module_profiles import UnsupportedModuleError
from pds_core.route_registrations import RouteRegistrationNotFoundError
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    load_routing_failure_metadata,
    routing_failure_metadata_path,
    write_routing_failure_metadata,
)
from pds_core.scan_resolution_metadata import load_scan_resolution_metadata

from paper_data_suite.returned_paper_core_review import (
    CoreReviewResultV1,
    DeferDecisionV1,
    ReviewPageV1,
    append_deferred_core_resolution,
    execute_with_core_review,
)
from paper_data_suite.returned_paper_readonly_decode import DecodedPage

# Reuse qualified Slice 4 synthetic setup without duplicating Core registrations.
_slice4 = import_module("test_issue18_slice4_ordered_dispatch")
_approve = _slice4._approve
_batch = _slice4._batch
_case = _slice4._case
_code = _slice4._code
_dispatch_success = _slice4._dispatch_success
_registry = _slice4._registry
_success = _slice4._success


def _failure_dispatch(error: Exception):
    def dispatch(root, registry, requests):
        assert len(requests) == 1
        return (RouteDispatchFailure(requests[0], error),)

    return dispatch


def _run(tmp_path: Path, *, dispatcher=None):
    batch, decode = _batch(tmp_path)
    return execute_with_core_review(
        batch,
        approve=_approve,
        decode=decode,
        registry_factory=_registry,
        dispatcher=dispatcher or _dispatch_success,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )


def _stored(result: CoreReviewResultV1) -> RoutingFailureMetadata:
    page = result.pages[0]
    assert page.review_state == "recorded" and page.failure_id is not None
    return load_routing_failure_metadata(
        result.execution.report.plan.workspace_root,
        page.failure_id,
    )


def test_success_has_no_core_failure_record(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.execution.status == "completed"
    assert result.pages[0].review_state == "not_required"
    assert result.pages[0].automatic_retry_allowed is False
    assert result.pages[1].review_state == "not_required"
    assert not (result.execution.report.plan.workspace_root / "scans/review").exists()


def test_actual_core_missing_registration_failure_persisted(tmp_path: Path) -> None:
    error = RouteRegistrationNotFoundError("private class/identity leak")
    result = _run(tmp_path, dispatcher=_failure_dispatch(error))
    stored = _stored(result)
    assert stored.schema_version == "2"
    assert stored.failure_category == "route_unknown"
    assert stored.stage == "route_resolution"
    assert stored.route_locator is not None
    assert stored.route_locator.module_id == "scoreform"
    assert stored.source_page_number == 1
    assert "private" not in stored.failure_message
    assert stored.detected_payload is None and stored.target is None
    assert stored.source_sha256 == (
        result.execution.report.sources[0].retained_source.source_sha256
    )
    assert result.execution.report.sources[0].pages[0].status == "dispatch_failed"


def test_actual_handler_failure_marks_uncertain_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    error = ModuleRouteHandlingError("secret grade body")
    result = _run(tmp_path, dispatcher=_failure_dispatch(error))
    stored = _stored(result)
    assert result.execution.status == "uncertain"
    assert result.pages[0].dispatch_status == "uncertain"
    assert stored.failure_category == "processing_error"
    assert stored.stage == "module_handling"
    assert "secret grade" not in stored.failure_message
    assert stored.route_locator is not None


def test_actual_unsupported_profile_after_attempt_records_core_mapping(
    tmp_path: Path,
) -> None:
    error = UnsupportedModuleError("private named route")
    result = _run(tmp_path, dispatcher=_failure_dispatch(error))
    stored = _stored(result)
    assert stored.failure_category == "module_unsupported"
    assert result.pages[0].dispatch_status == "module_unqualified"
    assert result.pages[0].review_state == "recorded"


def test_no_admission_does_not_invoke_handler_or_write(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    calls = []

    def dispatch(*args):
        calls.append(args)
        raise RuntimeError("handler must not run")

    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=dispatch,
    )
    assert calls == []
    assert result.pages[0].review_state == "manual_review"
    assert result.pages[1].review_state == "manual_review"
    assert not (batch.report.plan.workspace_root / "scans/review").exists()


def test_cancel_never_writes_review_records(tmp_path: Path) -> None:
    from paper_data_suite.returned_paper_ordered_dispatch import (
        DispatchDecisionV1,
    )

    batch, decode = _batch(tmp_path)

    def cancel(review):
        return DispatchDecisionV1("cancel", review.plan_digest, review.challenge)

    result = execute_with_core_review(
        batch, approve=cancel, decode=decode,
        registry_factory=_registry, dispatcher=_dispatch_success,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert not result.execution.approved
    assert all(row.review_state == "not_required" for row in result.pages)
    assert not (batch.report.plan.workspace_root / "scans/review").exists()


def test_expected_success_failure_success_keeps_all_pages(tmp_path: Path) -> None:
    batch, decode = _batch(
        tmp_path, ("scoreform", "quillan", "scoreform")
    )
    calls = []

    def dispatch(root, registry, requests):
        req = requests[0]
        calls.append(req.source_page_number)
        if req.source_page_number == 2:
            return (RouteDispatchFailure(
                req, RouteRegistrationNotFoundError("missing"),
            ),)
        return (_success(req, registry, root),)

    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=dispatch,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert calls == [1, 2, 3]
    assert [page.review_state for page in result.pages] == [
        "not_required", "recorded", "not_required",
    ]
    assert result.execution.attempted_pages == 3
    assert result.execution.status == "partial"
    assert result.pages[1].failure_id is not None


def test_writer_failure_keeps_original_dispatch_outcome(tmp_path: Path) -> None:
    calls = []

    def failing_writer(root, metadata):
        calls.append(metadata.failure_id)
        raise OSError("cannot write review file")

    batch, decode = _batch(tmp_path)
    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        dispatcher=_failure_dispatch(ModuleRouteHandlingError("unknown")),
        qualified_modules=frozenset({"scoreform", "quillan"}),
        write_failure=failing_writer,
    )
    assert len(calls) == 2
    assert len(set(calls)) == 2
    assert all(page.review_state == "write_uncertain" for page in result.pages)
    assert all(page.failure_id is None for page in result.pages)
    assert all(
        page.status == "uncertain"
        for page in result.execution.report.sources[0].pages
    )


def test_writer_raises_after_durable_write_no_automatic_rewrite(
    tmp_path: Path,
) -> None:
    calls = []

    def post_write_failure(root, metadata):
        calls.append(metadata.failure_id)
        write_routing_failure_metadata(root, metadata)
        raise RuntimeError("simulated crash after commit")

    batch, decode = _batch(tmp_path)
    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
        qualified_modules=frozenset({"scoreform", "quillan"}),
        write_failure=post_write_failure,
    )
    assert len(calls) == 2
    assert len(set(calls)) == 2
    assert all(page.review_state == "write_uncertain" for page in result.pages)
    assert all(page.failure_id is None for page in result.pages)
    # Each page's single write may be durable despite raising; never retry.
    assert all(
        routing_failure_metadata_path(
            batch.report.plan.workspace_root, failure_id
        ).is_file()
        for failure_id in calls
    )


def test_bad_writer_receipt_refused(tmp_path: Path) -> None:
    def incorrect_path(root, metadata):
        write_routing_failure_metadata(root, metadata)
        return root / "wrong.json"

    batch, decode = _batch(tmp_path)
    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
        qualified_modules=frozenset({"scoreform", "quillan"}),
        write_failure=incorrect_path,
    )
    assert result.pages[0].review_state == "write_uncertain"
    assert result.pages[0].failure_id is None


def test_mismatched_loaded_receipt_refused(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)

    def corrupt_loader(root, failure_id):
        raise ValueError("corrupt record")

    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
        qualified_modules=frozenset({"scoreform", "quillan"}),
        load_failure=corrupt_loader,
    )
    assert result.pages[0].review_state == "write_uncertain"


def test_collision_does_not_overwrite_first_occurrence(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    failure_id = "failure_fixed_test"
    original = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
        qualified_modules=frozenset({"scoreform", "quillan"}),
        new_failure_id=lambda: failure_id,
    )
    assert original.pages[0].review_state == "recorded"
    old_bytes = routing_failure_metadata_path(
        batch.report.plan.workspace_root, failure_id
    ).read_bytes()
    # This is an artificial second call; it must not overwrite the first event.
    repeated = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
        qualified_modules=frozenset({"scoreform", "quillan"}),
        new_failure_id=lambda: failure_id,
    )
    assert repeated.pages[0].review_state == "write_uncertain"
    assert routing_failure_metadata_path(
        batch.report.plan.workspace_root, failure_id
    ).read_bytes() == old_bytes


def test_linked_core_review_tree_is_refused(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    root = batch.report.plan.workspace_root
    redirected = tmp_path / "redirected-review"
    redirected.mkdir()
    try:
        (root / "scans" / "review").symlink_to(
            redirected, target_is_directory=True,
        )
    except (OSError, NotImplementedError):
        pytest.skip("symlink privilege unavailable")

    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.pages[0].review_state == "write_uncertain"
    assert list(redirected.iterdir()) == []


def test_bad_failure_id_reports_uncertain_write(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
        qualified_modules=frozenset({"scoreform", "quillan"}),
        new_failure_id=lambda: "unsafe/path",
    )
    assert result.pages[0].review_state == "write_uncertain"


def test_unexpected_handler_exception_is_generic_and_uncertain(
    tmp_path: Path,
) -> None:
    batch, decode = _batch(tmp_path)

    def unexpected(root, registry, requests):
        raise RuntimeError("student private result must not be persisted")

    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=unexpected,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    stored = _stored(result)
    assert result.execution.status == "uncertain"
    assert stored.failure_category == "processing_error"
    assert "student private" not in stored.failure_message


def test_unresolved_page_writes_no_locator_when_another_page_approved(
    tmp_path: Path,
) -> None:
    page_sets = ((
        DecodedPage((_code("scoreform"),)), DecodedPage(),
    ),)
    retention, decode, _ = _case(tmp_path, page_sets)
    from paper_data_suite.returned_paper_retained_requests import (
        prepare_retained_pds2_requests,
    )

    batch = prepare_retained_pds2_requests(retention, decode=decode)
    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=_dispatch_success,
        qualified_modules=frozenset({"scoreform"}),
    )
    assert [page.review_state for page in result.pages] == [
        "not_required", "recorded",
    ]
    stored = load_routing_failure_metadata(
        batch.report.plan.workspace_root, result.pages[1].failure_id
    )
    assert stored.route_locator is None
    assert stored.target is None and stored.detected_payload is None
    assert stored.failure_category == "payload_missing"
    assert stored.source_page_number == 2


def test_no_requests_has_no_review_write_without_fresh_consent(
    tmp_path: Path,
) -> None:
    from paper_data_suite.returned_paper_retained_requests import (
        prepare_retained_pds2_requests,
    )

    retention, decode, _ = _case(
        tmp_path, ((DecodedPage(),),), ((1, 1),)
    )
    batch = prepare_retained_pds2_requests(retention, decode=decode)
    assert batch.status == "no_dispatchable_pages"
    result = execute_with_core_review(batch, approve=_approve, decode=decode)
    assert result.execution.status == "no_requests"
    assert result.pages[0].review_state == "not_required"
    assert not (batch.report.plan.workspace_root / "scans/review").exists()


def test_unselected_physical_page_never_gets_review_entry(
    tmp_path: Path,
) -> None:
    from paper_data_suite.returned_paper_retained_requests import (
        prepare_retained_pds2_requests,
    )

    # _batch selects every page by default. Select only the first page so
    # the second, unresolved physical page cannot acquire a review record.
    retention, decode, _ = _case(tmp_path, selected=((1, 1),))
    batch = prepare_retained_pds2_requests(retention, decode=decode)
    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=_dispatch_success,
        qualified_modules=frozenset({"scoreform"}),
    )
    assert result.pages[0].dispatch_status == "handler_returned"
    assert result.pages[1].dispatch_status == "not_selected"
    assert result.pages[1].review_state == "not_required"
    assert not (batch.report.plan.workspace_root / "scans/review").exists()


def test_stale_retained_source_blocks_review_persistence(tmp_path: Path) -> None:
    batch, decode = _batch(tmp_path)
    receipt = batch.report.sources[0].retained_source
    assert receipt is not None
    receipt.retained_source_path.write_bytes(b"changed")
    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=_dispatch_success,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    assert result.execution.status == "blocked"
    assert not (batch.report.plan.workspace_root / "scans/review").exists()


def test_post_dispatch_custody_change_never_creates_failure_record(
    tmp_path: Path,
) -> None:
    batch, decode = _batch(tmp_path, ("scoreform",))

    def alter_retained(root, registry, requests):
        req = requests[0]
        req.retained_source.retained_source_path.write_bytes(b"tampered")
        return (RouteDispatchFailure(
            req, RouteRegistrationNotFoundError("missing"),
        ),)

    result = execute_with_core_review(
        batch, approve=_approve, decode=decode,
        registry_factory=_registry, dispatcher=alter_retained,
        qualified_modules=frozenset({"scoreform"}),
    )
    assert result.execution.report.sources[0].pages[0].status == "dispatch_failed"
    assert result.pages[0].review_state == "manual_review"
    assert not (batch.report.plan.workspace_root / "scans/review").exists()


def test_review_result_must_match_all_physical_pages(tmp_path: Path) -> None:
    result = _run(tmp_path)
    with pytest.raises(ValueError):
        CoreReviewResultV1(result.execution, result.pages[:1])
    with pytest.raises(ValueError):
        ReviewPageV1(1, 1, "dispatch_failed", "recorded")


def test_deferred_review_append_only_and_links_original_failure(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
    )
    failure = _stored(result)
    workspace = result.execution.report.plan.workspace_root

    def defer(review):
        assert review.failure_id == failure.failure_id
        assert review.automatic_retry_allowed is False
        return DeferDecisionV1("defer", review.failure_id, review.challenge)

    resolved = append_deferred_core_resolution(
        workspace, failure.failure_id, approve=defer,
    )
    assert resolved.state == "appended"
    stored = load_scan_resolution_metadata(workspace, resolved.resolution_id)
    assert stored.failure_id == failure.failure_id
    assert stored.resolution_status == "deferred"
    assert stored.resolution_action == "deferred"
    assert stored.route_locator is None and stored.target is None
    assert stored.resolution_evidence_path is None
    assert load_routing_failure_metadata(workspace, failure.failure_id) == failure


def test_cancel_deferred_review_is_read_only(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
    )
    failure = _stored(result)
    workspace = result.execution.report.plan.workspace_root

    def cancel(review):
        return DeferDecisionV1("cancel", review.failure_id, review.challenge)

    resolved = append_deferred_core_resolution(
        workspace, failure.failure_id, approve=cancel,
    )
    assert resolved.state == "cancelled" and resolved.resolution_id is None
    assert not (workspace / "scans/review/resolutions").exists()


def test_bad_defer_challenge_cannot_write(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
    )
    failure = _stored(result)
    workspace = result.execution.report.plan.workspace_root
    resolved = append_deferred_core_resolution(
        workspace, failure.failure_id,
        approve=lambda review: DeferDecisionV1(
            "defer", review.failure_id, "wrong-challenge",
        ),
    )
    assert resolved.state == "cancelled"
    assert not (workspace / "scans/review/resolutions").exists()


def test_deferred_write_failure_cannot_claim_success(tmp_path: Path, monkeypatch):
    result = _run(
        tmp_path,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
    )
    failure = _stored(result)
    workspace = result.execution.report.plan.workspace_root

    def fail(*args, **kwargs):
        raise OSError("disk is full")

    monkeypatch.setattr(
        "paper_data_suite.returned_paper_core_review.write_scan_resolution_metadata",
        fail,
    )

    def defer(review):
        return DeferDecisionV1("defer", review.failure_id, review.challenge)

    resolved = append_deferred_core_resolution(
        workspace, failure.failure_id, approve=defer,
    )
    assert resolved.state == "write_uncertain"
    assert resolved.resolution_id is None


def test_missing_failure_refuses_defer(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(Exception):
        append_deferred_core_resolution(
            workspace, "failure_missing",
            approve=lambda review: DeferDecisionV1(
                "defer", review.failure_id, review.challenge,
            ),
        )
