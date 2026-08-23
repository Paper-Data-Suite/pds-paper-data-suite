from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"
_README = _ROOT / "README.md"
_DOC = _ROOT / "docs" / "operations" / "combined-installed-suite-acceptance.md"


def _combined_job() -> str:
    text = _WORKFLOW.read_text(encoding="utf-8")
    start = text.index("  combined-installed-suite:")
    end = text.index("  release-artifacts:", start)
    return text[start:end]


def test_combined_acceptance_ci_has_full_supported_matrix() -> None:
    block = _combined_job()

    assert "fail-fast: false" in block
    assert "os: [ubuntu-latest, windows-latest]" in block
    assert 'python: ["3.11", "3.12", "3.13", "3.14"]' in block
    assert "runs-on: ${{ matrix.os }}" in block
    assert "python-version: ${{ matrix.python }}" in block


def test_combined_ci_is_manifest_driven_and_authenticates_artifacts() -> None:
    block = _combined_job()

    assert "release_compatibility_v1.json" in block
    assert 'for component in manifest["components"]:' in block
    assert "releases/download/{release['tag']}/{release['wheel']}" in block
    assert "scripts/verify_compatibility_artifacts.py" in block
    assert "--artifact-dir" in block
    assert "pds_concord-0.2.0" not in block
    assert "quillan-0.9.0" not in block
    assert "scoreform-0.10.0" not in block
    assert "pds_vitrine-0.2.0" not in block


def test_combined_acceptance_ci_builds_candidate_and_runs_installed_harness() -> None:
    block = _combined_job()

    build_index = block.index("Build candidate suite wheel")
    tooling_index = block.index("Install suite package for audit tooling")
    auth_index = block.index("Authenticate exact component artifacts")
    acceptance_index = block.index("Run combined installed-suite acceptance")
    hygiene_index = block.index("Verify combined-acceptance repository hygiene")

    assert build_index < tooling_index < auth_index < acceptance_index < hygiene_index
    assert "python -m build --outdir" in block
    assert "python -m twine check" in block
    assert "python scripts/check_package.py" in block
    assert "python -m pip install --no-deps -e ." in block
    assert "python scripts/smoke_test_combined_suite_wheels.py" in block


def test_combined_acceptance_ci_checks_repository_hygiene() -> None:
    block = _combined_job()

    assert "git diff --check" in block
    assert "git status --porcelain --untracked-files=all" in block
    assert "Combined installed-suite acceptance left repository residue." in block


def test_combined_docs_link_local_entrypoint() -> None:
    readme = _README.read_text(encoding="utf-8")
    normalized_readme = readme.replace("\\", "/")
    document = _DOC.read_text(encoding="utf-8")
    normalized = " ".join(document.replace("**", "").split())

    assert "docs/operations/combined-installed-suite-acceptance.md" in readme
    assert "scripts/smoke_test_combined_suite_wheels.py" in normalized_readme
    assert "one isolated installed environment" in normalized
    assert "one continuous synthetic Core workspace" in normalized
    assert "ubuntu-latest" in document
    assert "windows-latest" in document
    assert "3.14" in document
