from __future__ import annotations

from pathlib import Path

_WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
)


def _workflow_text() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_bootstrap_acceptance_is_one_bounded_windows_job() -> None:
    text = _workflow_text()
    block = text[text.index("  bootstrap-windows:") :]

    assert "runs-on: windows-latest" in block
    assert 'python-version: "3.11"' in block
    assert "matrix:" not in block


def test_bootstrap_acceptance_uses_external_suite_digest() -> None:
    text = _workflow_text()
    block = text[text.index("  bootstrap-windows:") :]

    hash_index = block.index("Get-FileHash -Algorithm SHA256")
    plan_index = block.index("Prove plan mode is non-mutating")
    assert hash_index < plan_index
    assert "-SuiteWheelSha256 $env:PDS_BOOTSTRAP_SUITE_SHA256" in block


def test_bootstrap_acceptance_proves_plan_before_apply() -> None:
    text = _workflow_text()
    block = text[text.index("  bootstrap-windows:") :]

    plan_index = block.index("Prove plan mode is non-mutating")
    apply_index = block.index("Apply exact all-component composition")
    verify_index = block.index("Verify installed composition and import roots")
    assert plan_index < apply_index < verify_index
    assert "Plan mode created the requested target environment" in block
    assert "-AllComponents" in block
    assert "-Apply" in block
    assert "-Yes" in block


def test_bootstrap_acceptance_checks_exact_install_and_idempotence() -> None:
    text = _workflow_text()
    block = text[text.index("  bootstrap-windows:") :]

    assert '"paper-data-suite": ("0.1.0.dev0", "paper_data_suite")' in block
    assert '"pds-core": ("0.6.0", "pds_core")' in block
    assert '"pds-concord": ("0.2.0", "concord")' in block
    assert '"quillan": ("0.9.0", "quillan")' in block
    assert '"scoreform": ("0.10.0", "scoreform")' in block
    assert '"pds-vitrine": ("0.2.0", "vitrine")' in block
    assert "Environment action: keep_environment" in block
    assert block.count(": keep_exact") >= 6


def test_bootstrap_acceptance_checks_no_workspace_or_repo_residue() -> None:
    text = _workflow_text()
    block = text[text.index("  bootstrap-windows:") :]

    assert "pds bootstrap empty cwd" in block
    assert "workspace-shaped working-directory state" in block
    assert "git diff --check" in block
    assert "git status --porcelain --untracked-files=all" in block

def test_release_artifact_audit_installs_suite_tooling_before_authentication() -> None:
    text = _workflow_text()
    start = text.index("  release-artifacts:")
    end = text.index("  bootstrap-windows:")
    block = text[start:end]

    install_index = block.index("Install suite package for audit tooling")
    auth_index = block.index("Authenticate declared release wheels")
    assert install_index < auth_index
    assert "python -m pip install --no-deps -e ." in block
