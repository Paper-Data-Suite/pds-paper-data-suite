"""Issue #49 Slice 32: externally pinned receipt continuity is not local authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    ExternallyPinnedReceiptHead,
    compare_receipt_to_observed_candidate,
    make_untrusted_active_receipt,
    parse_untrusted_active_receipt,
    verify_externally_pinned_receipt,
)
from paper_data_suite.evergreen_journal_pip_preflight import (
    ObservedJournalPipCandidate,
)

NOW = datetime(2026, 10, 18, 20, tzinfo=UTC)
EVIDENCE = {
    "prepared_record": b"authenticated prepared transaction",
    "registry_envelope": b"root signed registry",
    "lock_envelope": b"root signed dependency lock",
    "native_envelope": b"root signed interpreter",
}


def _candidate() -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        transaction_id="a" * 32,
        journal_revision=1,
        stage_relative_path="candidates/stage-1",
        wheelhouse_relative_path="wheelhouse/approved-1",
        native_payload_sha256="b" * 64,
        pip_inventory_sha256="c" * 64,
        publisher_digests=(("quillan", "d" * 64), ("scoreform", "e" * 64)),
        root_console_targets=(
            ("quillan", "quillan", "quillan.cli:main"),
            ("scoreform", "scoreform", "scoreform.cli:main"),
        ),
        external_distributions=("pds-core",),
    )


def _draft(
    *, previous: ExternallyPinnedReceiptHead | None = None, generation: int = 1
) -> bytes:
    return make_untrusted_active_receipt(
        _candidate(),
        **EVIDENCE,
        generation=generation,
        recorded_at=NOW,
        previous=previous,
    )


def _head(raw: bytes, generation: int = 1) -> ExternallyPinnedReceiptHead:
    # A test-provided fixture only. Production must obtain head OUTSIDE the
    # locally editable software tree; this helper does not establish trust.
    return ExternallyPinnedReceiptHead(generation, hashlib.sha256(raw).hexdigest())


def _mutate(raw: bytes, **changes: Any) -> bytes:
    data = json.loads(raw)
    data.update(changes)
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("ascii")


def test_canonical_draft_round_trip_and_pinned_external_head() -> None:
    raw = _draft()
    receipt = parse_untrusted_active_receipt(raw)
    assert receipt.transaction_id == "a" * 32
    assert receipt.generation == 1
    assert receipt.previous_receipt_sha256 is None
    result = verify_externally_pinned_receipt(raw, head=_head(raw), predecessor=None)
    assert result.receipt == receipt
    compare_receipt_to_observed_candidate(result, _candidate(), **EVIDENCE)
    assert "can_launch" not in vars(result.__class__)
    assert "activate" not in vars(result.__class__)


def test_second_generation_requires_independently_pinned_predecessor() -> None:
    first = _draft()
    old_head = _head(first)
    second = _draft(previous=old_head, generation=2)
    result = verify_externally_pinned_receipt(
        second, head=_head(second, 2), predecessor=old_head
    )
    assert result.receipt.previous_receipt_sha256 == old_head.receipt_sha256
    assert result.receipt.generation == 2


def test_chain_refuses_missing_or_mismatched_prior_checkpoint() -> None:
    first = _head(_draft())
    second = _draft(previous=first, generation=2)
    with pytest.raises(ActiveReceiptError, match="predecessor"):
        verify_externally_pinned_receipt(
            second, head=_head(second, 2), predecessor=None
        )
    wrong = ExternallyPinnedReceiptHead(1, "f" * 64)
    with pytest.raises(ActiveReceiptError, match="predecessor"):
        verify_externally_pinned_receipt(
            second, head=_head(second, 2), predecessor=wrong
        )


def test_copied_old_receipt_fails_new_independent_head() -> None:
    first = _draft()
    prior = _head(first)
    second = _draft(previous=prior, generation=2)
    with pytest.raises(ActiveReceiptError, match="head"):
        verify_externally_pinned_receipt(
            first, head=_head(second, 2), predecessor=prior
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("prepared_sha256", "0" * 64),
        ("registry_sha256", "0" * 64),
        ("lock_sha256", "0" * 64),
        ("native_envelope_sha256", "0" * 64),
        ("native_payload_sha256", "0" * 64),
        ("pip_inventory_sha256", "0" * 64),
        ("transaction_id", "b" * 32),
        ("stage_relative_path", "candidates/other"),
        ("wheelhouse_relative_path", "wheelhouse/other"),
    ],
)
def test_exact_field_substitution_fails_original_external_head(
    field: str, value: str
) -> None:
    raw = _draft()
    substituted = _mutate(raw, **{field: value})
    with pytest.raises(ActiveReceiptError, match="head"):
        verify_externally_pinned_receipt(substituted, head=_head(raw), predecessor=None)


@pytest.mark.parametrize(
    "field,value",
    [
        ("stage_relative_path", "../escape"),
        ("stage_relative_path", "C:/outside"),
        ("wheelhouse_relative_path", "safe/../escape"),
        ("publisher_digests", [["quillan", "d" * 64]] * 2),
        ("publisher_digests", [["quillan", "d" * 64], ["quillan", "e" * 64]]),
        (
            "root_console_targets",
            [
                ["quillan", "app", "quillan.cli:main"],
                ["scoreform", "app", "scoreform.cli:main"],
            ],
        ),
        ("root_console_targets", [["quillan", "danger", "os.system"]]),
        ("external_distributions", ["pds-core", "pds-core"]),
        ("generation", True),
        ("generation", 0),
        ("recorded_at", "2026-99-01T10:00:00Z"),
    ],
)
def test_invalid_shape_rejected_before_trust(field: str, value: object) -> None:
    with pytest.raises(ActiveReceiptError):
        parse_untrusted_active_receipt(_mutate(_draft(), **{field: value}))


def test_unknown_member_and_duplicate_keys_rejected() -> None:
    raw = _draft()
    with pytest.raises(ActiveReceiptError, match="fields"):
        parse_untrusted_active_receipt(_mutate(raw, can_launch=True))
    malformed = raw.replace(b'"generation":1,', b'"generation":1,"generation":1,')
    with pytest.raises(ActiveReceiptError, match="duplicate"):
        parse_untrusted_active_receipt(malformed)


def test_noncanonical_json_and_oversized_refused() -> None:
    raw = _draft()
    with pytest.raises(ActiveReceiptError, match="noncanonical"):
        parse_untrusted_active_receipt(raw + b"\n")
    with pytest.raises(ActiveReceiptError, match="size"):
        parse_untrusted_active_receipt(b"X" * (16 * 1024 + 1))


def test_missing_trusted_head_cannot_be_replaced_by_local_receipt() -> None:
    raw = _draft()
    with pytest.raises(ActiveReceiptError, match="checkpoint"):
        verify_externally_pinned_receipt(
            raw,
            head=None,
            predecessor=None,  # type: ignore[arg-type]
        )
    with pytest.raises(ActiveReceiptError, match="checkpoint"):
        ExternallyPinnedReceiptHead(1, "wrong")


def test_unsigned_claims_cannot_become_activation_authority() -> None:
    raw = _draft()
    parsed = parse_untrusted_active_receipt(raw)
    assert not hasattr(parsed, "is_active")
    assert not hasattr(parsed, "trusted")
    assert not hasattr(parsed, "launch")


def test_forged_payload_with_new_self_supplied_head_proves_nothing_about_past() -> None:
    # This is deliberately accepted as a BYTES comparison: the security
    # assertion is that a self-issued head is NOT an independent trust root.
    forged = _mutate(_draft(), stage_relative_path="other/tree")
    synthetic_head = _head(forged)
    checked = verify_externally_pinned_receipt(
        forged, head=synthetic_head, predecessor=None
    )
    assert checked.receipt.stage_relative_path == "other/tree"
    assert not hasattr(checked, "authorized")


def test_candidate_evidence_mismatch_detected_after_pinning() -> None:
    raw = _draft()
    pinned = verify_externally_pinned_receipt(raw, head=_head(raw), predecessor=None)
    with pytest.raises(ActiveReceiptError, match="candidate"):
        compare_receipt_to_observed_candidate(
            pinned,
            replace(_candidate(), pip_inventory_sha256="f" * 64),
            **EVIDENCE,
        )
    with pytest.raises(ActiveReceiptError, match="candidate"):
        compare_receipt_to_observed_candidate(
            pinned, _candidate(), **{**EVIDENCE, "lock_envelope": b"different"}
        )


def test_draft_cannot_skip_or_regress_generation() -> None:
    prior = _head(_draft())
    for generation in (1, 3, 0, True):
        with pytest.raises(ActiveReceiptError, match="continuity"):
            _draft(previous=prior, generation=generation)
    with pytest.raises(ActiveReceiptError, match="continuity"):
        _draft(generation=2)


def test_draft_requires_whole_second_timestamp() -> None:
    with pytest.raises(ActiveReceiptError, match="whole seconds"):
        make_untrusted_active_receipt(
            _candidate(),
            **EVIDENCE,
            generation=1,
            recorded_at=NOW.replace(microsecond=1),
            previous=None,
        )
