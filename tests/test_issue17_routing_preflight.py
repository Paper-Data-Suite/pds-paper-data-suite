"""Suite #17 Slice 3: metadata versus optional Core registration observations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_data_suite.returned_paper_readonly_decode import (
    DecodedPage,
    observe_selected_sources,
)
from paper_data_suite.returned_paper_routing_preflight import (
    collect_routing_metadata,
    evaluate_routing_profiles,
    make_core_registration_check,
)

QR = "PDS2|m=quillan|c=class_a|w=work_a|r=rt_0123456789abcdef"


@dataclass(frozen=True)
class Metadata:
    entry_point_name: str = "quillan"
    distribution_name: str | None = "quillan"
    provider_kind: str = "routing_module"
    entry_point_group: str = "paper_data_suite.modules"
    entry_point_target: str = "quillan.pds_module:get_module_profile"


@dataclass(frozen=True)
class FakeLocator:
    module_id: str = "quillan"


def _fake_profile(*, qr: str = "PDS2") -> SimpleNamespace:
    return SimpleNamespace(
        module_id="quillan",
        supported_core_routing_contract_versions={"1"},
        supported_qr_schemas={qr},
        supported_route_registration_schema_versions={"1"},
        dispatchable_route_statuses={"active"},
    )


def _diagnostic(
    code: str = "provider.valid", *, profile: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=Metadata(), code=code,
        validated_profile=_fake_profile() if profile is None else profile,
    )


def test_routing_metadata_is_six_approved_rows_and_purely_observational() -> None:
    calls: list[str] = []

    def inspect() -> tuple[Metadata, ...]:
        calls.append("metadata")
        return (Metadata(), Metadata("concord", "pds-concord"))

    inventory = collect_routing_metadata(inspect=inspect)
    assert calls == ["metadata"]
    assert inventory.inspection_available
    assert [row.module_id for row in inventory.applications] == [
        "scoreform", "quillan", "concord", "meridian", "vitrine", "portia",
    ]
    assert inventory.for_component("core") is None
    assert (
        inventory.for_component("quillan").metadata_status
        == "declared_unvalidated"
    )  # type: ignore[union-attr]
    assert (
        inventory.for_component("concord").profile_status
        == "not_evaluated"
    )  # type: ignore[union-attr]
    assert (
        inventory.for_component("portia").metadata_status
        == "not_declared"
    )  # type: ignore[union-attr]


def test_owner_mismatch_ambiguous_and_unknown_do_not_promote() -> None:
    inventory = collect_routing_metadata(inspect=lambda: (
        Metadata("quillan", "bad-owner"),
        Metadata("concord", "pds_concord"),
        Metadata("concord", "pds-concord"),
        Metadata("surprise", "surprise"),
    ))
    assert (
        inventory.for_component("quillan").metadata_status
        == "owner_mismatch"
    )  # type: ignore[union-attr]
    assert (
        inventory.for_component("concord").metadata_status
        == "ambiguous"
    )  # type: ignore[union-attr]
    assert inventory.unapproved_candidates == 1
    assert (
        inventory.for_component("quillan").profile_status
        == "not_evaluated"
    )  # type: ignore[union-attr]


def test_publisher_name_normalization_is_not_authentication() -> None:
    rows = collect_routing_metadata(inspect=lambda: (
        Metadata("concord", "PDS_CONCORD"),
    ))
    assert (
        rows.for_component("concord").metadata_status
        == "declared_unvalidated"
    )  # type: ignore[union-attr]
    assert (
        rows.for_component("concord").profile_status
        == "not_evaluated"
    )  # type: ignore[union-attr]


def test_invalid_malformed_or_failed_metadata_never_masquerades_as_empty() -> None:
    broken = collect_routing_metadata(inspect=lambda: (
        Metadata(provider_kind="module_operations"),
        Metadata("concord", "pds-concord", entry_point_target=""),
    ))
    assert (
        broken.for_component("quillan").metadata_status
        == "invalid_metadata"
    )  # type: ignore[union-attr]
    assert (
        broken.for_component("concord").metadata_status
        == "invalid_metadata"
    )  # type: ignore[union-attr]

    def failed() -> tuple[Metadata, ...]:
        raise RuntimeError("sensitive source path/student details")

    unavailable = collect_routing_metadata(inspect=failed)
    assert not unavailable.inspection_available
    assert all(
        row.metadata_status == "inspection_unavailable"
        for row in unavailable.applications
    )
    assert "sensitive source" not in repr(unavailable)
    excessive = collect_routing_metadata(inspect=lambda: (Metadata(),) * 513)
    assert not excessive.inspection_available


def test_explicit_profile_diagnosis_never_claims_dispatch_authority() -> None:
    declared = collect_routing_metadata(inspect=lambda: (Metadata(),))
    count = 0

    def diagnose() -> tuple[SimpleNamespace, ...]:
        nonlocal count
        count += 1
        return (_diagnostic(),)

    observed = evaluate_routing_profiles(declared, diagnose=diagnose)
    assert count == 1
    row = observed.for_component("quillan")
    assert row is not None
    assert row.profile_status == "profile_valid"
    assert row.metadata_status == "declared_unvalidated"
    assert not hasattr(row, "can_dispatch")
    assert (
        observed.for_component("portia").profile_status
        == "not_evaluated"
    )  # type: ignore[union-attr]


def test_diagnostic_incompatible_missing_and_invalid() -> None:
    declared = collect_routing_metadata(inspect=lambda: (Metadata(),))
    incompatible = evaluate_routing_profiles(
        declared, diagnose=lambda: (_diagnostic(profile=_fake_profile(qr="QR_OTHER")),)
    )
    assert (
        incompatible.for_component("quillan").profile_status
        == "core_incompatible"
    )  # type: ignore[union-attr]
    invalid = evaluate_routing_profiles(declared, diagnose=lambda: (
        _diagnostic("provider.identity_conflict"),
    ))
    assert (
        invalid.for_component("quillan").profile_status
        == "profile_invalid"
    )  # type: ignore[union-attr]
    missing = evaluate_routing_profiles(declared, diagnose=lambda: ())
    assert (
        missing.for_component("quillan").profile_status
        == "profile_unavailable"
    )  # type: ignore[union-attr]


def test_diagnostic_never_upgrades_wrong_owner() -> None:
    declared = collect_routing_metadata(
        inspect=lambda: (Metadata(distribution_name="foreign"),)
    )
    upgraded = evaluate_routing_profiles(declared, diagnose=lambda: (_diagnostic(),))
    assert (
        upgraded.for_component("quillan").profile_status
        == "not_evaluated"
    )  # type: ignore[union-attr]


def test_registration_checker_requires_explicit_workspace_authorization(
    tmp_path: Path,
) -> None:
    core = pytest.importorskip("pds_core.pds2")
    target = core.parse_pds2_payload(QR)
    assert make_core_registration_check(None)(1, 1, target) == "workspace_unavailable"
    assert (
        make_core_registration_check(tmp_path)(1, 1, target)
        == "workspace_unavailable"
    )
    called: list[Path] = []

    def deny(path: Path, _: object) -> bool:
        called.append(path)
        return False

    check = make_core_registration_check(tmp_path, authorize_route=deny)
    assert check(1, 1, target) == "workspace_unavailable"
    assert called == [tmp_path]
    # A forged/non-Core locator is rejected before any authorization callback.
    assert check(1, 2, FakeLocator()) == "registration_invalid"
    assert called == [tmp_path]


def test_registration_checker_fail_closed_on_bad_authorizer(tmp_path: Path) -> None:
    core = pytest.importorskip("pds_core.pds2")
    target = core.parse_pds2_payload(QR)
    called: list[object] = []

    def broken(_: Path, locator: object) -> bool:
        called.append(locator)
        raise RuntimeError("sensitive student/file text")

    check = make_core_registration_check(tmp_path, authorize_route=broken)
    assert check(1, 1, target) == "workspace_unavailable"
    assert check(1, 2, target) == "workspace_unavailable"
    assert called == [target, target]


def test_decoder_uses_transient_locator_only_for_opt_in_checker(
    tmp_path: Path,
) -> None:
    file = tmp_path / "selected.png"
    data = b"\x89PNG\r\n\x1a\n" + b"synthetic"
    file.write_bytes(data)
    before = file.stat().st_mtime_ns
    seen: list[tuple[int, int, object]] = []

    def check(source: int, page: int, locator: object) -> str:
        seen.append((source, page, locator))
        return "registration_not_found"

    def parse(text: str) -> FakeLocator:
        if not text.startswith("PDS2|"):
            raise ValueError("secret QR payload")
        return FakeLocator()

    def decode(*_: object) -> tuple[DecodedPage, ...]:
        return (
            DecodedPage((QR,)), DecodedPage(),
            DecodedPage((QR, "PDS2|m=concord|c=x|w=y|r=z")),
            DecodedPage(("PDS1|bad",)),
        )

    unverified = observe_selected_sources(
        (file,), decoder=decode, parse_payload=parse,
    )
    assert unverified[0].pages[0].registration_status == "not_checked"
    assert seen == []
    rows = observe_selected_sources(
        (file,), decoder=decode, parse_payload=parse, registration_check=check,
    )
    assert [(page.status, page.registration_status) for page in rows[0].pages] == [
        ("candidate_unverified", "registration_not_found"),
        ("missing_qr", "not_checked"),
        ("ambiguous_qr", "not_checked"),
        ("invalid_or_foreign_qr", "not_checked"),
    ]
    assert [(source, page) for source, page, _ in seen] == [(1, 1)]
    assert hashlib.sha256(data).hexdigest() == rows[0].sha256_advisory
    assert "rt_0123456789" not in repr(rows)
    assert QR not in repr(rows)
    assert before == file.stat().st_mtime_ns
    assert file.read_bytes() == data


def test_registration_checker_exception_is_bounded_and_not_a_decode_failure(
    tmp_path: Path,
) -> None:
    file = tmp_path / "selected.png"
    file.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")

    def fail(*_: object) -> str:
        raise RuntimeError("private student / sensitive route")

    rows = observe_selected_sources(
        (file,),
        decoder=lambda *args: (DecodedPage((QR,)),),
        parse_payload=lambda text: FakeLocator(),
        registration_check=fail,
    )
    page = rows[0].pages[0]
    assert page.status == "candidate_unverified"
    assert page.registration_status == "registration_invalid"
    assert "private student" not in repr(rows)


def test_core_public_registration_reader_in_disposable_workspace(
    tmp_path: Path,
) -> None:
    pytest.importorskip("pds_core")
    from pds_core.pds2 import parse_pds2_payload
    from pds_core.route_registrations import write_route_registration
    from pds_core.routing_models import ModuleRecordRef, RouteRegistration

    locator = parse_pds2_payload(QR)
    registration = RouteRegistration(
        schema_version="1",
        locator=locator,
        target=ModuleRecordRef(
            module_id="quillan", record_kind="synthetic", record_id="record_1",
            contract_version="1",
        ),
        created_at="2026-11-09T14:00:00+00:00",
        status="active",
        human_fallback="synthetic nonstudent test route",
        module_details={},
    )
    write_route_registration(tmp_path, registration)
    before = tuple((p, p.read_bytes()) for p in sorted(tmp_path.rglob("*.json")))
    check = make_core_registration_check(
        tmp_path, authorize_route=lambda _root, _locator: True
    )
    assert check(1, 1, locator) == "structurally_consistent"
    after = tuple((p, p.read_bytes()) for p in sorted(tmp_path.rglob("*.json")))
    assert after == before
    other = parse_pds2_payload(QR.replace("rt_0123456789abcdef", "rt_aabbccddeeff0011"))
    assert check(1, 2, other) == "registration_not_found"


def test_injected_core_reader_statuses_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.returned_paper_routing_preflight as preflight

    class Locator:
        pass

    locator = Locator()
    route_file = tmp_path / "routes" / "route.json"
    state = {"record": "active"}
    requested: list[object] = []

    class Missing(Exception):
        pass

    Missing.__module__ = "pds_core.route_registrations"
    Missing.__name__ = "RouteRegistrationNotFoundError"

    def load(_root: Path, given: object) -> object:
        requested.append(given)
        if state["record"] == "missing":
            raise Missing("private sensitive route data")
        if state["record"] == "broken":
            raise RuntimeError("private sensitive route data")
        if state["record"] == "mismatch":
            return SimpleNamespace(locator=Locator(), status="active")
        return SimpleNamespace(locator=locator, status=state["record"])

    def importer(name: str) -> object:
        if name == "pds_core.routing_models":
            return SimpleNamespace(RouteLocator=Locator)
        if name == "pds_core.routes":
            return SimpleNamespace(route_registration_path=lambda root, loc: route_file)
        if name == "pds_core.route_registrations":
            return SimpleNamespace(load_route_registration=load)
        raise AssertionError("Unexpected module import")

    monkeypatch.setattr(preflight, "import_module", importer)
    allowed: list[tuple[Path, object]] = []

    def authorized(root: Path, given: object) -> bool:
        allowed.append((root, given))
        return True

    check = make_core_registration_check(tmp_path, authorize_route=authorized)
    assert check(1, 1, locator) == "structurally_consistent"
    state["record"] = "inactive"
    assert check(1, 1, locator) == "registration_inactive"
    state["record"] = "missing"
    assert check(1, 1, locator) == "registration_not_found"
    state["record"] = "broken"
    assert check(1, 1, locator) == "registration_invalid"
    state["record"] = "mismatch"
    assert check(1, 1, locator) == "registration_invalid"
    assert len(allowed) == 5
    assert all(x is locator for x in requested)


def test_redirected_registration_refused_before_core_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.returned_paper_routing_preflight as preflight

    class Locator:
        pass

    route_parent = tmp_path / "routes"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        route_parent.symlink_to(elsewhere, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privilege unavailable")

    called: list[str] = []

    def importer(name: str) -> object:
        if name == "pds_core.routing_models":
            return SimpleNamespace(RouteLocator=Locator)
        if name == "pds_core.routes":
            return SimpleNamespace(
                route_registration_path=lambda root, loc: route_parent / "route.json"
            )
        if name == "pds_core.route_registrations":
            return SimpleNamespace(
                load_route_registration=lambda *_: called.append("load")
            )
        raise AssertionError("Unexpected module import")

    monkeypatch.setattr(preflight, "import_module", importer)
    check = make_core_registration_check(
        tmp_path, authorize_route=lambda root, loc: True,
    )
    assert check(1, 1, Locator()) == "registration_invalid"
    assert called == []
