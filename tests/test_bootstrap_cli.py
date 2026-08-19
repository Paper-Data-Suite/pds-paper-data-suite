from __future__ import annotations

import json
from pathlib import Path

from paper_data_suite import bootstrap_cli
from paper_data_suite.compatibility import (
    load_release_compatibility_manifest,
    release_compatibility_manifest_bytes,
    release_compatibility_manifest_sha256,
)


def test_manifest_digest_matches_exact_resource_bytes() -> None:
    import hashlib

    assert release_compatibility_manifest_sha256() == hashlib.sha256(
        release_compatibility_manifest_bytes()
    ).hexdigest()


def test_manifest_summary_is_machine_readable(capsys) -> None:
    assert bootstrap_cli.main(["manifest-summary", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    manifest = load_release_compatibility_manifest()

    assert payload["suite_version"] == manifest.suite.version
    assert payload["compatibility_manifest_sha256"] == (
        release_compatibility_manifest_sha256()
    )
    assert payload["optional_component_ids"] == [
        "concord",
        "quillan",
        "scoreform",
        "vitrine",
    ]


def test_plan_for_missing_environment_is_plan_only(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "future environment"

    result = bootstrap_cli.main(
        [
            "plan",
            "--environment-path",
            str(target),
            "--seed-python-version",
            "3.11.9",
            "--component",
            "scoreform",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "Environment action: create_environment" in output
    assert "ScoreForm 0.10.0: install_missing" in output
    assert "No changes have been made." in output
    assert not target.exists()


def test_plan_blocker_returns_three(tmp_path: Path, capsys) -> None:
    target = tmp_path / "existing"
    target.mkdir()

    result = bootstrap_cli.main(
        [
            "plan",
            "--environment-path",
            str(target),
            "--seed-python-version",
            "3.11.9",
        ]
    )

    output = capsys.readouterr().out
    assert result == 3
    assert "existing target is not a validated virtual environment" in output
    assert "No changes have been made." in output


def test_plan_json_is_deterministic(tmp_path: Path, capsys) -> None:
    target = tmp_path / "missing"
    args = [
        "plan",
        "--environment-path",
        str(target),
        "--seed-python-version",
        "3.12.8",
        "--component",
        "vitrine",
        "--json",
    ]

    assert bootstrap_cli.main(args) == 0
    first = capsys.readouterr().out
    assert bootstrap_cli.main(args) == 0
    second = capsys.readouterr().out

    assert first == second
    payload = json.loads(first)
    assert payload["can_apply"] is True
    assert payload["environment"]["python_minor"] == "3.12"

def test_artifact_requirements_are_machine_readable(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "missing"

    result = bootstrap_cli.main(
        [
            "artifact-requirements",
            "--environment-path",
            str(target),
            "--seed-python-version",
            "3.11.9",
            "--component",
            "vitrine",
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert [
        item["component_id"] for item in payload["required_artifacts"]
    ] == ["core", "vitrine"]
    assert payload["constraints"] == [
        "paper-data-suite==0.1.0.dev0",
        "pds-concord==0.2.0",
        "pds-core==0.6.0",
        "pds-vitrine==0.2.0",
        "quillan==0.9.0",
        "scoreform==0.10.0",
    ]
    assert all(
        "/releases/download/" in item["url"]
        and "/latest/" not in item["url"]
        for item in payload["required_artifacts"]
    )


def test_verify_artifacts_failure_does_not_write_constraints(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "missing-target"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    constraints = tmp_path / "pds-constraints.txt"

    result = bootstrap_cli.main(
        [
            "verify-artifacts",
            "--environment-path",
            str(target),
            "--seed-python-version",
            "3.11.9",
            "--artifact-dir",
            str(artifacts),
            "--constraints-path",
            str(constraints),
            "--json",
        ]
    )

    assert result == 4
    assert "artifact verification failed" in capsys.readouterr().out
    assert not constraints.exists()



def _write_dist_info(
    site_packages: Path,
    name: str,
    version: str,
) -> None:
    dist_info = (
        site_packages
        / f"{name.replace('-', '_')}-{version}.dist-info"
    )
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.4\n"
        f"Name: {name}\n"
        f"Version: {version}\n\n",
        encoding="utf-8",
    )


def _write_installed_target(
    root: Path,
    *,
    include_vitrine: bool = False,
) -> None:
    manifest = load_release_compatibility_manifest()
    (root / "Scripts").mkdir(parents=True)
    (root / "Scripts" / "python.exe").write_bytes(b"synthetic")
    site_packages = root / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    (root / "pyvenv.cfg").write_text(
        "home = C:\\Python311\n"
        "include-system-site-packages = false\n"
        "version = 3.11.9\n",
        encoding="utf-8",
    )
    _write_dist_info(
        site_packages,
        manifest.suite.distribution,
        manifest.suite.version,
    )
    (site_packages / "paper_data_suite").mkdir()
    for component in manifest.components:
        if component.required or (
            include_vitrine and component.component_id == "vitrine"
        ):
            _write_dist_info(
                site_packages,
                component.distribution,
                component.version,
            )
            (
                site_packages
                / Path(*component.import_name.split("."))
            ).mkdir(parents=True, exist_ok=True)


def test_verify_installed_does_not_require_marker(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "target"
    _write_installed_target(target)

    result = bootstrap_cli.main(
        [
            "verify-installed",
            "--environment-path",
            str(target),
            "--seed-python-version",
            "3.11.9",
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert [
        item["component_id"] for item in payload["verified_packages"]
    ] == ["suite", "core"]
    assert payload["marker_path"] is None
    assert not (target / ".pds-suite-environment.json").exists()


def test_finalize_environment_writes_marker_after_exact_verification(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "target"
    _write_installed_target(target, include_vitrine=True)

    result = bootstrap_cli.main(
        [
            "finalize-environment",
            "--environment-path",
            str(target),
            "--seed-python-version",
            "3.11.9",
            "--component",
            "vitrine",
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    marker = target / ".pds-suite-environment.json"
    assert payload["marker_path"] == str(marker.resolve())
    assert marker.is_file()


def test_finalize_environment_fails_before_marker_when_selected_missing(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "target"
    _write_installed_target(target)

    result = bootstrap_cli.main(
        [
            "finalize-environment",
            "--environment-path",
            str(target),
            "--seed-python-version",
            "3.11.9",
            "--component",
            "quillan",
            "--json",
        ]
    )

    assert result == 2
    assert "required installed distribution is missing" in capsys.readouterr().out
    assert not (target / ".pds-suite-environment.json").exists()
