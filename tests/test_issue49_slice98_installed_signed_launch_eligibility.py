"""Slice 98: signed-wheel-to-installed-bytes correlation is not launch authority."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import sys
import zipfile
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from paper_data_suite import evergreen_installed_launch_eligibility as subject


def _hash(raw: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "isolated-venv"
    site = root / "Lib" / "site-packages"
    info = site / "quillan-0.10.6.dist-info"
    info.mkdir(parents=True)
    package = site / "quillan"
    package.mkdir()
    contents = {
        "quillan/__init__.py": b"from .cli import main\n",
        "quillan/cli.py": b"def main():\n    return 0\n",
        "quillan-0.10.6.dist-info/METADATA": (
            b"Metadata-Version: 2.3\nName: quillan\nVersion: 0.10.6\n"
        ),
        "quillan-0.10.6.dist-info/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
        "quillan-0.10.6.dist-info/entry_points.txt": (
            b"[console_scripts]\nquillan = quillan.cli:main\n"
        ),
    }
    for name, raw in contents.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    record = io.StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for name, raw in contents.items():
        writer.writerow((name, "sha256=" + _hash(raw), str(len(raw))))
    writer.writerow(("quillan-0.10.6.dist-info/RECORD", "", ""))
    record_bytes = record.getvalue().encode("utf-8")
    wheel = tmp_path / "quillan-0.10.6-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, raw in contents.items():
            archive.writestr(name, raw)
        archive.writestr("quillan-0.10.6.dist-info/RECORD", record_bytes)
    (info / "RECORD").write_bytes(record_bytes)
    dist = SimpleNamespace(
        metadata={"Name": "quillan"},
        version="0.10.6",
        locate_file=lambda name: site / name,
        name="quillan",
    )
    signed = SimpleNamespace(
        component_id="quillan",
        distribution="quillan",
        version="0.10.6",
        sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        console_script="quillan",
        console_target="quillan.cli:main",
        requires_dist=("pds-core>=0.6.5,<0.7",),
    )
    ep = SimpleNamespace(name="quillan", value="quillan.cli:main", dist=dist)
    monkeypatch.setattr(subject, "verify_signed_release_wheel", lambda *a, **kw: signed)
    monkeypatch.setattr(subject.metadata, "distribution", lambda name: dist)
    monkeypatch.setattr(
        subject.metadata,
        "version",
        lambda name: "0.6.6" if name == "pds-core" else "0.10.6",
    )
    monkeypatch.setattr(subject.metadata, "entry_points", lambda **kw: [ep])
    monkeypatch.setattr(sys, "prefix", str(root))
    return {
        "root": root,
        "site": site,
        "wheel": wheel,
        "signed": signed,
        "ep": ep,
        "dist": dist,
        "contents": contents,
        "info": info,
    }


def _inspect(
    installation: dict[str, Any], *, component: str = "quillan"
) -> subject.InstalledSignedLaunchObservation:
    return subject.inspect_signed_installed_launch_candidate(
        component,
        wheel=installation["wheel"],
        registry_envelope=b"registry",
        module_envelope=b"module",
        trust=None,  # type: ignore[arg-type]  # test verifier is stubbed
        now=datetime.now(timezone.utc),
        version="0.10.6",
    )


def test_matching_installed_bytes_are_only_observations(
    installed: dict[str, Any],
) -> None:
    result = _inspect(installed)
    assert result.status == "SIGNED_WHEEL_INSTALLED_BYTES_MATCH_OBSERVED_ONLY"
    assert result.files_checked == 5
    assert result.runtime_dependencies_checked == 1
    assert "NO_LAUNCH" in result.authority
    assert not any(
        f.name in {"can_launch", "permit", "approved"} for f in fields(result)
    )


def test_wrong_component_cannot_use_same_signed_wheel(
    installed: dict[str, Any],
) -> None:
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="component"):
        _inspect(installed, component="scoreform")


def test_unregistered_module_rejected_before_signature(
    installed: dict[str, Any],
) -> None:
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="module"):
        _inspect(installed, component="unknown")


def test_changed_installed_module_refused(installed: dict[str, Any]) -> None:
    (installed["site"] / "quillan" / "cli.py").write_text("def main():\n return 1\n")
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="installed file"):
        _inspect(installed)


def test_deleted_installed_module_refused(installed: dict[str, Any]) -> None:
    (installed["site"] / "quillan" / "cli.py").unlink()
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="installed file"):
        _inspect(installed)


def test_wrong_interpreter_environment_refused(
    installed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "prefix", str(installed["root"].parent / "other-venv"))
    with pytest.raises(
        subject.InstalledLaunchEvidenceError, match="environment|identity"
    ):
        _inspect(installed)


def test_missing_runtime_dependency_refused(
    installed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(name: str) -> str:
        raise subject.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(subject.metadata, "version", missing)
    with pytest.raises(
        subject.InstalledLaunchEvidenceError, match="required distribution"
    ):
        _inspect(installed)


def test_incompatible_runtime_dependency_refused(
    installed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subject.metadata, "version", lambda name: "0.6.3")
    with pytest.raises(
        subject.InstalledLaunchEvidenceError, match="dependency version"
    ):
        _inspect(installed)


def test_launcher_target_drift_refused(installed: dict[str, Any]) -> None:
    installed["ep"].value = "quillan.other:main"
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="owner/target"):
        _inspect(installed)


def test_duplicate_launcher_refused(
    installed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subject.metadata,
        "entry_points",
        lambda **kw: [installed["ep"], installed["ep"]],
    )
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="owner/target"):
        _inspect(installed)


def test_launcher_owned_by_another_distribution_refused(
    installed: dict[str, Any],
) -> None:
    installed["ep"].dist = SimpleNamespace(name="evil")
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="owner/target"):
        _inspect(installed)


def test_signed_release_revocation_or_signature_failure_refused(
    installed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from paper_data_suite.evergreen_release_artifacts import ReleaseArtifactError

    def reject(*args: Any, **kwargs: Any) -> Any:
        raise ReleaseArtifactError("bad signature")

    monkeypatch.setattr(subject, "verify_signed_release_wheel", reject)
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="signed wheel"):
        _inspect(installed)


def test_signed_component_identity_cannot_be_forged(installed: dict[str, Any]) -> None:
    installed["signed"].component_id = "scoreform"
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="component"):
        _inspect(installed)


def test_untrusted_direct_url_dependency_rejected(installed: dict[str, Any]) -> None:
    installed["signed"].requires_dist = (
        "pds-core @ https://untrusted.example/file.whl",
    )
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="direct-URL"):
        _inspect(installed)


def test_optional_extra_is_not_a_runtime_requirement(installed: dict[str, Any]) -> None:
    installed["signed"].requires_dist = (
        "pds-core>=0.6.5,<0.7",
        'pytest; extra == "dev"',
    )
    assert _inspect(installed).runtime_dependencies_checked == 1


def test_bad_wheel_record_refused(installed: dict[str, Any]) -> None:
    old = installed["wheel"]
    revised = old.with_name("quillan-corrupt.whl")
    with zipfile.ZipFile(old) as source, zipfile.ZipFile(revised, "w") as target:
        for item in source.infolist():
            raw = source.read(item.filename)
            if item.filename.endswith(".dist-info/RECORD"):
                raw = raw.replace(b"sha256=", b"sha256=BAD")
            target.writestr(item.filename, raw)
    installed["wheel"] = revised
    with pytest.raises(subject.InstalledLaunchEvidenceError, match="RECORD"):
        _inspect(installed)


def test_unverified_installed_file_symlink_refused(
    installed: dict[str, Any], tmp_path: Path
) -> None:
    path = installed["site"] / "quillan" / "cli.py"
    clone = tmp_path / "copy.py"
    clone.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(clone)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(
        subject.InstalledLaunchEvidenceError, match="environment|reparse"
    ):
        _inspect(installed)
