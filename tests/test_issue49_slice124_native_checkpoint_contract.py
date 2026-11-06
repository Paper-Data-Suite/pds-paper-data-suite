"""Slice 124: source assertions; native C++ execution is a distinct CI gate."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native/windows/bootstrap"
HEADER = NATIVE / "checkpoint_contract.h"
UNIT = NATIVE / "checkpoint_contract_test.cpp"
PROBE = NATIVE / "bootstrap_probe.cpp"
CMAKE = NATIVE / "CMakeLists.txt"
GATE = NATIVE / "qualify_native_bootstrap.ps1"
SPEC = ROOT / "docs/architecture/issue-49-slice-124-native-checkpoint-validation.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_exact_native_contract_sources_exist() -> None:
    assert all(p.is_file() for p in (HEADER, UNIT, PROBE, CMAKE, GATE, SPEC))
    assert 1000 < HEADER.stat().st_size < 16000
    assert 1000 < UNIT.stat().st_size < 20000


def test_native_parser_limits_input_and_schema() -> None:
    source = _text(HEADER)
    assert "kMaxBytes = 4096" in source
    assert "kMaxRevision = 9007199254740991ULL" in source
    assert "schema == 1" in source
    assert "cp.generation == 0" in source
    assert "cp.generation == 1" in source
    assert "cp.trust_revision == 0" in source
    assert "r.finish()" in source


@pytest.mark.parametrize(
    "required",
    [
        'field("last_request_sha256")',
        'field("last_transaction_id")',
        'field("trust_policy_sha256")',
        'field("lock_revision")',
        'field("registry_revision")',
        'field("previous_checkpoint_sha256")',
        'field("proposed_checkpoint_sha256")',
        'field("previous_generation")',
        'field("proposed_generation")',
        'field("transaction_id")',
        'literal("\\"INTENT_PREPARED\\"")',
        'literal("\\"CHECKPOINT_REPLACED_CLAIMED\\"")',
    ],
    ids=(
        "request",
        "checkpoint-tx",
        "trust-root",
        "lock-revision",
        "registry-revision",
        "prior-hash",
        "next-hash",
        "prior-generation",
        "next-generation",
        "journal-tx",
        "prepared",
        "replaced",
    ),
)
def test_native_contract_has_strict_fields(required: str) -> None:
    assert required in _text(HEADER)


def test_native_parser_rejects_unknown_noncanonical_content() -> None:
    source = _text(HEADER)
    assert "count > text_.size() - pos_" in source
    assert "text_[pos_] == '0'" in source
    assert "c >= 'a' && c <= 'f'" in source
    assert "previous == 0 && proposed == 1" in source
    assert "return Relationship::invalid" in source
    assert "Relationship::prepared_previous" in source
    assert "Relationship::replacement_claimed_commit_unverified" in source


def test_win32_probe_hashes_held_bytes_with_windows_cng() -> None:
    source = _text(PROBE)
    assert '#include "checkpoint_contract.h"' in source
    assert "BCryptOpenAlgorithmProvider" in source
    assert "BCRYPT_SHA256_ALGORITHM" in source
    assert "BCryptHash(" in source
    assert "BCryptCloseAlgorithmProvider" in source
    assert "sha256_checkpoint(checkpoint_bytes, observed_digest)" in source
    assert "classify_claims(" in source
    assert "Relationship::invalid" in source
    assert "bounded_read(checkpoint_file.get(), checkpoint_bytes)" in source
    assert "bounded_read(journal_file.get(), journal_bytes)" in source
    assert "WriteFile(" not in source


def test_native_build_and_runtime_gate_requires_real_cxx_contract_execution() -> None:
    cmake = _text(CMAKE)
    gate = _text(GATE)
    assert "PRIVATE advapi32 shell32 ole32 bcrypt" in cmake
    assert (
        "add_executable(pds_checkpoint_contract_test checkpoint_contract_test.cpp)"
        in cmake
    )
    assert "pds_checkpoint_contract_test --parallel 2" in gate
    assert "SLICE124_NATIVE_CHECKPOINT_CONTRACT_TESTS_PASSED" in gate
    assert "if ($contractExit -ne 0" in gate
    assert "SLICE124_NATIVE_CHECKPOINT_CONTRACT_PASSED_$Architecture" in gate
    assert "if ($Architecture -ne $hostArchitecture)" in gate
    assert "SLICE123_NATIVE_ARM64_RUNTIME_PASSED" in gate
    assert gate.rstrip().endswith("exit 0")


def test_native_cxx_test_has_positive_and_negative_evidence() -> None:
    source = _text(UNIT)
    for evidence in (
        "genesis-prepared",
        "new-unfinalized",
        "new-claimed",
        "replaced-with-genesis",
        "duplicate-json-field",
        "oversized-checkpoint",
        "unknown-phase",
        "wrong-journal-request",
        "altered-proposed-digest",
        "SLICE124_NATIVE_CHECKPOINT_CONTRACT_TESTS_PASSED",
    ):
        assert evidence in source
    assert "return 1;" in source


def test_doc_disclaims_receipt_and_os_custody() -> None:
    spec = _text(SPEC).lower()
    for phrase in (
        "native x64",
        "native arm64",
        "read-only",
        "no service",
        "no receipt",
        "independent antirollback",
    ):
        assert phrase in spec
