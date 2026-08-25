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
    assert '"pds-core": ("0.6.3", "pds_core")' in block
    assert '"pds-concord": ("0.2.0", "concord")' in block
    assert '"quillan": ("0.9.0", "quillan")' in block
    assert '"scoreform": ("0.10.0", "scoreform")' in block
    assert '"pds-vitrine": ("0.2.0", "vitrine")' in block
    assert "Environment action: keep_environment" in block
    assert block.count(": keep_exact") >= 6
    assert "Authenticated release artifacts:" in block
    assert "pip 26.2.1: PASS" in block
    assert "none required by this plan" not in block


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



def test_validate_job_uses_official_core_v063_release() -> None:
    text = _workflow_text()
    start = text.index("  validate:")
    end = text.index("  combined-installed-suite:")
    block = text[start:end]

    assert "pds_core-0.6.3-py3-none-any.whl" in block
    assert "Download official Core 0.6.3 wheel" in block
    assert (
        "pds-core/releases/download/v0.6.3/"
        "pds_core-0.6.3-py3-none-any.whl"
    ) in block
    assert "0.6.2" not in block

_CHECKOUT_PIN = (
    "actions/checkout@"
    "11d5960a326750d5838078e36cf38b85af677262 # v4.4.0"
)
_SETUP_PYTHON_PIN = (
    "actions/setup-python@"
    "a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0"
)


def test_release_critical_actions_are_immutably_pinned() -> None:
    text = _workflow_text()

    assert "actions/checkout@v4" not in text
    assert "actions/setup-python@v5" not in text
    assert text.count(_CHECKOUT_PIN) == 4
    assert text.count(_SETUP_PYTHON_PIN) == 4


def test_validate_job_authenticates_core_before_install() -> None:
    text = _workflow_text()
    start = text.index("  validate:")
    end = text.index("  combined-installed-suite:")
    block = text[start:end]

    download_index = block.index("Download official Core 0.6.3 wheel")
    auth_index = block.index("Authenticate Core artifact before install")
    install_index = block.index("Install Core and development package")

    assert download_index < auth_index < install_index
    assert "release_compatibility_v1.json" in block
    assert 'component["component_id"] == "core"' in block
    assert 'digest != release["sha256"]' in block
    assert 'wheel.name != release["wheel"]' in block

def test_release_artifact_jobs_include_exact_release_tooling_contract() -> None:
    text = _workflow_text()

    assert text.count("release_tooling_v1.json") >= 3
    assert text.count('urlretrieve(tool["url"], destination / tool["wheel"])') >= 3

    combined_start = text.index("  combined-installed-suite:")
    release_start = text.index("  release-artifacts:")
    bootstrap_start = text.index("  bootstrap-windows:")

    combined = text[combined_start:release_start]
    release = text[release_start:bootstrap_start]
    bootstrap = text[bootstrap_start:]

    for block in (combined, release, bootstrap):
        assert "Download exact declared release artifacts" in block
        assert "release_tooling_v1.json" in block
        assert 'tool["url"]' in block
        assert 'tool["wheel"]' in block


def test_release_artifact_verifier_runs_after_tooling_download() -> None:
    text = _workflow_text()
    start = text.index("  release-artifacts:")
    end = text.index("  bootstrap-windows:")
    block = text[start:end]

    download_index = block.index("Download exact declared release artifacts")
    verify_index = block.index("Authenticate declared release wheels")
    assert download_index < verify_index

def test_validate_and_combined_smokes_receive_qualified_release_tooling() -> None:
    text = _workflow_text()

    validate_start = text.index("  validate:")
    combined_start = text.index("  combined-installed-suite:")
    release_start = text.index("  release-artifacts:")

    validate = text[validate_start:combined_start]
    combined = text[combined_start:release_start]

    assert "Download exact declared release tooling wheel" in validate
    assert "release_tooling_v1.json" in validate
    assert "PDS_RELEASE_TOOL_WHEEL" in validate
    assert '"$env:PDS_RELEASE_TOOL_WHEEL"' in validate

    assert "pip-*.whl" in combined
    assert "--release-tool-wheel" in combined
