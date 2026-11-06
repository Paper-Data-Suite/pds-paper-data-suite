"""PR #55 repair 3: platform-neutral source bounds and safe bootstrap deps."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap_windows.ps1"
NATIVE = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
COMBINED = ROOT / "scripts/smoke_test_combined_suite_wheels.py"


def test_bootstrap_resolves_declared_suite_runtime_wheel_dependencies() -> None:
    script = BOOTSTRAP.read_text(encoding="utf-8")
    block = script.split('Invoke-Required "Install exact authenticated suite"', 1)[1]
    block = block.split("foreach ($PackagePlan in $PackagePlans)", 1)[0]
    assert "'--only-binary=:all:'" in block
    assert "'--constraint', $ConstraintsPath" in block
    assert "$ResolvedSuiteWheel" in block
    assert "'--no-deps'" not in block
    assert "'--no-index'" not in block
    assert 'Invoke-Required "pip check"' in script


def test_native_source_bound_is_line_ending_independent() -> None:
    raw = NATIVE.read_bytes()
    assert 1_000 < len(raw.replace(b"\r\n", b"\n")) < 16_000


def test_combined_smoke_uses_truthful_historical_manifest_label() -> None:
    script = COMBINED.read_text(encoding="utf-8")
    assert 'f"Historical manifest version: {application.version}"' in script
    assert 'f"Suite-qualified version: {application.version}"' not in script
