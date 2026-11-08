"""Suite #52 Slice 3: source-wheel identity and isolated-consumer guardrails."""

from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import issue52_core_header_acceptance as witness


def _fake_wheel(
    path: Path,
    *, package: str = "pds_core",
    version: str = "0.6.6",
    metadata_name: str = "pds-core",
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{package}/__init__.py", "__version__ = '0.6.6'\n")
        archive.writestr(
            f"pds_core-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: {metadata_name}\n"
            f"Version: {version}\n\n",
        )
    return path


def test_sha256_file_reports_actual_bytes(tmp_path: Path) -> None:
    document = tmp_path / "artifact.bin"
    document.write_bytes(b"published artifact")
    assert witness.sha256_file(document) == hashlib.sha256(
        b"published artifact"
    ).hexdigest()


def test_official_verifier_requires_exact_bytes_not_version(
    tmp_path: Path,
) -> None:
    wheel = _fake_wheel(tmp_path / "pds_core-0.6.6-py3-none-any.whl")
    digest = witness.verify_wheel(wheel)
    assert digest == witness.sha256_file(wheel)
    with pytest.raises(witness.CoreAcceptanceError, match="SHA-256"):
        witness.verify_wheel(wheel, required_sha256=witness.OFFICIAL_SHA256)
    wheel.write_bytes(wheel.read_bytes() + b"one changed byte")
    assert witness.sha256_file(wheel) != digest


@pytest.mark.parametrize(
    ("package", "version", "metadata_name"),
    [
        ("wrong", "0.6.6", "pds-core"),
        ("pds_core", "0.6.5", "pds-core"),
        ("pds_core", "0.6.6", "other-core"),
    ],
)
def test_wheel_identity_refuses_wrong_name_version_or_package(
    tmp_path: Path, package: str, version: str, metadata_name: str,
) -> None:
    wheel = _fake_wheel(
        tmp_path / "pds_core-0.6.6-py3-none-any.whl",
        package=package, version=version, metadata_name=metadata_name,
    )
    with pytest.raises(witness.CoreAcceptanceError, match="identity"):
        witness.verify_wheel(wheel)


def test_verifier_rejects_nonwheel_or_bad_zip(tmp_path: Path) -> None:
    with pytest.raises(witness.CoreAcceptanceError, match="missing or invalid"):
        witness.verify_wheel(tmp_path / "no.whl")
    invalid = tmp_path / "bad.whl"
    invalid.write_bytes(b"not-a-zip")
    with pytest.raises(witness.CoreAcceptanceError, match="cannot be inspected"):
        witness.verify_wheel(invalid)


def test_isolated_probe_requires_exact_kind_and_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = _fake_wheel(tmp_path / "pds_core-0.6.6-py3-none-any.whl")
    observed: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        observed.append(command)
        return SimpleNamespace(
            returncode=0, stdout='{"kind":"developer", "header_available":true}',
            stderr="",
        )

    monkeypatch.setattr(witness.subprocess, "run", fake_run)
    assert witness.isolated_probe(
        wheel, kind="developer", suite_root=tmp_path,
    )["header_available"]
    assert observed[0][1:3] == ["-I", "-B"]
    assert observed[0][3].endswith("issue52_core_header_acceptance.py")
    with pytest.raises(witness.CoreAcceptanceError, match="unexpected evidence"):
        witness.isolated_probe(wheel, kind="official", suite_root=tmp_path)


def test_isolated_probe_rejects_nonzero_and_nonjson(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = tmp_path / "synthetic.whl"
    monkeypatch.setattr(
        witness.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="private path"
        ),
    )
    with pytest.raises(witness.CoreAcceptanceError, match="probe failed"):
        witness.isolated_probe(wheel, kind="official", suite_root=tmp_path)
    monkeypatch.setattr(
        witness.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="warning", stderr=""
        ),
    )
    with pytest.raises(witness.CoreAcceptanceError, match="did not return JSON"):
        witness.isolated_probe(wheel, kind="official", suite_root=tmp_path)


@pytest.mark.parametrize("autocrlf", ["true", "false", "input"])
def test_pinned_git_archive_ignores_untracked_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, autocrlf: str,
) -> None:
    repo = tmp_path / "core"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.org"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    # Repeat on every platform. The true case reproduces Windows behavior
    # where git archive would turn LF blobs into CRLF without the override.
    subprocess.run(
        ["git", "-C", str(repo), "config", "core.autocrlf", autocrlf],
        check=True, capture_output=True,
    )
    (repo / "source.txt").write_text("committed\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "source.txt"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "source"],
        check=True, capture_output=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    monkeypatch.setattr(witness, "CORE_SOURCE_SHA", sha)
    (repo / "source.txt").write_text("working-tree mutation\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("private\n", encoding="utf-8")
    archive = tmp_path / "pinned.zip"
    witness.pinned_core_archive(repo, archive)
    # The archive must contain committed bytes even with core.autocrlf=true;
    # neither dirty working-tree content nor untracked files may enter it.
    committed_blob = subprocess.run(
        ["git", "-C", str(repo), "show", f"{sha}:source.txt"],
        check=True, capture_output=True,
    ).stdout
    assert committed_blob.replace(b"\r\n", b"\n") == b"committed\n"
    with zipfile.ZipFile(archive) as payload:
        assert payload.read("source.txt") == committed_blob
        assert "untracked.txt" not in payload.namelist()
    assert (repo / "source.txt").read_text(encoding="utf-8") == (
        "working-tree mutation\n"
    )


def test_cli_needs_explicit_both_tracks() -> None:
    with pytest.raises(SystemExit) as result:
        witness.main([])
    assert result.value.code == 2
    assert witness.OFFICIAL_VERSION == "0.6.6"
    assert len(witness.CORE_SOURCE_SHA) == 40
    assert len(witness.OFFICIAL_SHA256) == 64


def test_build_failure_reports_phase_and_hides_local_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_command: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=(
                "error: subprocess-exited-with-error\n"
                "ModuleNotFoundError: No module named 'setuptools'\n"
                "  File \"C:/Users/Example/private/build.py\", line 2\n"
            ),
        )

    monkeypatch.setattr(witness.subprocess, "run", fail)
    with pytest.raises(witness.CoreAcceptanceError) as caught:
        witness._execute(["python.exe", "-m", "pip"], phase="developer-wheel-build")
    message = str(caught.value)
    assert "developer-wheel-build failed (status 1)" in message
    assert "No module named 'setuptools'" in message
    assert "C:/Users/" not in message
    assert "private" not in message


def test_sensitive_error_summary_has_no_paths() -> None:
    assert "C:/Users/" not in witness._safe_error_summary(
        "error: C:/Users/Example/private-path\n"
        "ModuleNotFoundError: No module named 'setuptools'\n"
    )
    assert witness._safe_error_summary(
        "error: C:/Users/Example/private-path\n"
        "ModuleNotFoundError: No module named 'setuptools'\n"
    ) == "ModuleNotFoundError: No module named 'setuptools'"
