"""Issue #49 Slice 26: per-feature exact attestation over real-pip evidence."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice25_journal_pip_preflight as prior_fixtures
from test_issue49_slice3_signature_verification import (
    _encode,
    _integration,
    _signed,
)

from paper_data_suite.evergreen_exact_integration import (
    ExactEvidenceStatus,
    ExactIntegrationError,
    inspect_journal_exact_integration,
)

# Reuse Slice 25's module-scoped fixture without shadowing test parameters.
prior_journal_candidate = prior_fixtures.journal_candidate


@pytest.fixture(name="journal_candidate", scope="module")
def _reuse_journal_candidate(request: pytest.FixtureRequest) -> dict[str, Any]:
    return request.getfixturevalue("prior_journal_candidate")


_FEATURE = "core.public-routing"


def _claims(source: dict[str, Any], **changes: Any) -> dict[str, Any]:
    prepared = json.loads(source["prepared_record"])
    wheel = next(
        item for item in prepared["wheels"] if item["distribution"] == "demo-app"
    )
    doc = _integration()
    doc.update(
        {
            "feature_id": _FEATURE,
            "result": "passed",
            "artifacts": [{"component_id": "demo", "wheel_sha256": wheel["sha256"]}],
            "python_minors": [prepared["python_minor"]],
            "platforms": [prepared["platform"]],
        }
    )
    doc.update(changes)
    return doc


def _inputs(source: dict[str, Any], **changes: Any) -> dict[str, Any]:
    values = dict(source)
    values["module_envelopes"] = dict(values["module_envelopes"])
    values.update(
        integration_envelope=_signed(_claims(source), "suite-integration"),
        feature_id=_FEATURE,
        required_component_ids=("demo",),
    )
    values.update(changes)
    return values


def _inspect(source: dict[str, Any], **changes: Any):
    return inspect_journal_exact_integration(**_inputs(source, **changes))


def test_signed_exact_feature_matches_real_installed_wheel(
    journal_candidate: dict[str, Any],
) -> None:
    with patch("subprocess.run", side_effect=AssertionError("must be read-only")):
        seen = _inspect(journal_candidate)
    assert seen.status is ExactEvidenceStatus.EXACT_ATTESTED
    assert seen.feature_id == _FEATURE
    assert seen.participants == ("demo",)
    assert seen.transaction_id == "e" * 32
    assert (
        seen.attestation_sha256
        == hashlib.sha256(_encode(_claims(journal_candidate))).hexdigest()
    )
    assert len(seen.pip_inventory_sha256) == 64
    assert not hasattr(seen, "can_launch")
    assert not hasattr(seen, "activate")


def test_missing_attestation_remains_unqualified_without_blocking_module(
    journal_candidate: dict[str, Any],
) -> None:
    result = _inspect(journal_candidate, integration_envelope=None)
    assert result.status is ExactEvidenceStatus.UNQUALIFIED
    assert result.attestation_sha256 is None
    assert result.signed_result is None
    assert result.pip_inventory_sha256


@pytest.mark.parametrize(
    "field", ["feature_id", "artifacts", "python_minors", "platforms"]
)
def test_signed_claims_do_not_inherit_other_feature_or_platform(
    journal_candidate: dict[str, Any],
    field: str,
) -> None:
    change: dict[str, Any] = {
        "feature_id": "other.feature",
        "artifacts": [{"component_id": "demo", "wheel_sha256": "f" * 64}],
        "python_minors": ["3.19"],
        "platforms": ["different_platform"],
    }
    doc = _claims(journal_candidate, **{field: change[field]})
    result = _inspect(
        journal_candidate,
        integration_envelope=_signed(doc, "suite-integration"),
    )
    assert result.status is ExactEvidenceStatus.UNQUALIFIED
    assert result.attestation_sha256 is not None


def test_signed_failure_is_negative_only_for_named_feature(
    journal_candidate: dict[str, Any],
) -> None:
    signed = _signed(_claims(journal_candidate, result="failed"), "suite-integration")
    result = _inspect(journal_candidate, integration_envelope=signed)
    assert result.status is ExactEvidenceStatus.ATTESTED_FAILURE
    assert result.signed_result == "failed"
    assert not hasattr(result, "can_launch")


def test_missing_required_core_identity_cannot_be_inferred_from_external_lock(
    journal_candidate: dict[str, Any],
) -> None:
    result = _inspect(
        journal_candidate,
        required_component_ids=("demo", "core"),
    )
    assert result.status is ExactEvidenceStatus.UNQUALIFIED


def test_wrong_integration_signer_fails_closed(
    journal_candidate: dict[str, Any],
) -> None:
    envelope = _signed(_claims(journal_candidate), "root-primary")
    with pytest.raises(ExactIntegrationError, match="signature"):
        _inspect(journal_candidate, integration_envelope=envelope)


def test_modified_integration_payload_signature_fails_closed(
    journal_candidate: dict[str, Any],
) -> None:
    original = json.loads(_signed(_claims(journal_candidate), "suite-integration"))
    original["payload_b64"] = "YQ=="
    with pytest.raises(ExactIntegrationError, match="signature"):
        _inspect(journal_candidate, integration_envelope=_encode(original))


def test_missing_or_duplicate_contract_scope_is_rejected(
    journal_candidate: dict[str, Any],
) -> None:
    for scope in ((), ("demo", "demo"), ("../escape",), ("demo", 2)):
        with pytest.raises(ExactIntegrationError, match="scope"):
            _inspect(journal_candidate, required_component_ids=scope)


def test_modified_journal_evidence_cannot_be_bypassed_by_signed_feature(
    journal_candidate: dict[str, Any],
) -> None:
    with pytest.raises(ExactIntegrationError, match="candidate"):
        _inspect(
            journal_candidate,
            prepared_record=journal_candidate["prepared_record"] + b"\n",
        )


def test_installed_source_drift_blocks_even_valid_signed_feature(
    journal_candidate: dict[str, Any],
) -> None:
    root = journal_candidate["software_root"] / "private-staged-venv"
    site = root / (
        "Lib/site-packages"
        if os.name == "nt"
        else f"lib/python{sys.version_info.major}."
        f"{sys.version_info.minor}/site-packages"
    )
    source = site / "demo_app/__init__.py"
    old = source.read_bytes()
    try:
        source.write_bytes(old + b"# modified")
        with pytest.raises(ExactIntegrationError, match="candidate"):
            _inspect(journal_candidate)
    finally:
        source.write_bytes(old)


def test_pending_recovery_blocks_signed_feature(
    journal_candidate: dict[str, Any],
) -> None:
    marker = journal_candidate["software_root"] / "pending-slot-recovery.json"
    marker.write_bytes(b"bad-pending-marker")
    try:
        with pytest.raises(ExactIntegrationError, match="candidate"):
            _inspect(journal_candidate)
    finally:
        marker.unlink()


def test_no_unsigned_claim_can_upgrade_unqualified_feature(
    journal_candidate: dict[str, Any],
) -> None:
    doc = _claims(journal_candidate)
    doc["artifacts"] = [{"component_id": "demo", "wheel_sha256": "0" * 64}]
    signed = _signed(doc, "suite-integration")
    with pytest.raises(ExactIntegrationError, match="signature"):
        unsigned = json.loads(signed)
        unsigned["payload_b64"] = "e30="
        _inspect(journal_candidate, integration_envelope=_encode(unsigned))
