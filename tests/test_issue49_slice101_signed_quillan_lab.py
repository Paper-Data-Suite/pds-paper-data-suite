"""Slice 101: isolated signed Quillan lab is not production launch authority."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import zipfile
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from paper_data_suite import evergreen_signed_lab_launch as subject


def _digest(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def _dist(site: Path, name: str, version: str, requirements: list[str]) -> None:
    dest = site / f"{name.replace('-', '_')}-{version}.dist-info"
    dest.mkdir()
    lines = ["Metadata-Version: 2.3", f"Name: {name}", f"Version: {version}"]
    lines.extend(f"Requires-Dist: {req}" for req in requirements)
    (dest / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / subject._EXPECTED_NAME
    site = root / "Lib" / "site-packages"
    scripts = root / "Scripts"
    scripts.mkdir(parents=True)
    site.mkdir(parents=True)
    (scripts / "python.exe").write_bytes(b"MZTEST")
    (scripts / "quillan.exe").write_bytes(b"MZTEST")
    (root / "pyvenv.cfg").write_text(
        "include-system-site-packages = false\nversion = 3.11.9\n"
    )
    _dist(site, "pds-core", "0.6.6", [])
    _dist(site, "qrcode", "8.2", ['pillow>=10; extra == "pil"'])
    _dist(site, "pillow", "13.0.0", [])
    folder = site / "quillan-0.10.6.dist-info"
    folder.mkdir()
    contents = {
        "quillan/__init__.py": b"",
        "quillan/cli.py": b"def main():\n    return 0\n",
        "quillan-0.10.6.dist-info/METADATA": (
            b"Metadata-Version: 2.3\nName: quillan\nVersion: 0.10.6\n"
            b"Requires-Dist: pds-core>=0.6.5,<0.7\n"
            b"Requires-Dist: qrcode[pil]>=8\n"
            b'Requires-Dist: pytest; extra == "dev"\n'
        ),
        "quillan-0.10.6.dist-info/WHEEL": (b"Wheel-Version: 1.0\nTag: py3-none-any\n"),
        "quillan-0.10.6.dist-info/entry_points.txt": (
            b"[console_scripts]\nquillan = quillan.cli:main\n"
        ),
    }
    for name, data in contents.items():
        dest = site / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for name, data in contents.items():
        writer.writerow((name, "sha256=" + _digest(data), len(data)))
    writer.writerow(("quillan-0.10.6.dist-info/RECORD", "", ""))
    wheel = tmp_path / "quillan-0.10.6-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
        archive.writestr("quillan-0.10.6.dist-info/RECORD", buffer.getvalue())
    (folder / "RECORD").write_text(buffer.getvalue())
    pin = hashlib.sha256(b"policy").hexdigest()
    files = {}
    for name in (
        "trust-policy.json",
        "registry-envelope.json",
        "quillan-envelope.json",
    ):
        dest = tmp_path / name
        dest.write_bytes(b"policy" if name == "trust-policy.json" else b"envelope")
        files[name] = dest
    signed = SimpleNamespace(
        component_id="quillan",
        distribution="quillan",
        version="0.10.6",
        console_script="quillan",
        console_target="quillan.cli:main",
        sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
    )

    def check_pin(data: bytes, *, pinned_sha256: str) -> Any:
        if data != b"policy" or pinned_sha256 != pin:
            raise subject.TrustProvisioningError("pin mismatch")
        return SimpleNamespace(keyring=object(), sha256=pin)

    monkeypatch.setattr(subject, "load_digest_pinned_trust_policy", check_pin)
    monkeypatch.setattr(subject, "verify_signed_release_wheel", lambda *a, **k: signed)
    monkeypatch.setattr(subject, "_wrapper", lambda *a, **k: "a" * 64)
    return {
        "root": root,
        "site": site,
        "wheel": wheel,
        "pin": pin,
        "files": files,
        "signed": signed,
    }


def _run(data: dict[str, Any]) -> subject.SignedLabObservation:
    return subject.inspect_signed_quillan_lab(
        data["root"],
        wheel=data["wheel"],
        policy=data["files"]["trust-policy.json"],
        independent_policy_sha256=data["pin"],
        registry=data["files"]["registry-envelope.json"],
        module=data["files"]["quillan-envelope.json"],
        now=datetime.now(timezone.utc),
    )


def test_matching_signed_lab_is_not_launch_authority(lab: dict[str, Any]) -> None:
    result = _run(lab)
    assert result.files_checked == 5
    assert result.dependency_distributions_checked == 4
    assert result.native_executable_authenticated is False
    assert "NO_PRODUCTION_LAUNCH_AUTHORITY" in result.status
    assert not {"permit", "launch", "approved"} & {f.name for f in fields(result)}


def test_drift_in_installed_python_file_refused(lab: dict[str, Any]) -> None:
    (lab["site"] / "quillan" / "cli.py").write_text("def main(): return 5\n")
    with pytest.raises(subject.SignedLabLaunchError, match="installed wheel"):
        _run(lab)


def test_wrong_trust_pin_refused(lab: dict[str, Any]) -> None:
    lab["pin"] = "a" * 64
    with pytest.raises(subject.SignedLabLaunchError, match="signed release"):
        _run(lab)


def test_changed_public_trust_file_refused(lab: dict[str, Any]) -> None:
    lab["files"]["trust-policy.json"].write_bytes(b"attacker-policy")
    with pytest.raises(subject.SignedLabLaunchError, match="signed release"):
        _run(lab)


def test_wrong_signed_version_refused(lab: dict[str, Any]) -> None:
    lab["signed"].version = "0.10.7"
    with pytest.raises(subject.SignedLabLaunchError, match="wrong signed"):
        _run(lab)


def test_missing_transitive_dependency_refused(lab: dict[str, Any]) -> None:
    for path in (lab["site"] / "pillow-13.0.0.dist-info").iterdir():
        path.unlink()
    (lab["site"] / "pillow-13.0.0.dist-info").rmdir()
    with pytest.raises(
        subject.SignedLabLaunchError, match="runtime dependency missing"
    ):
        _run(lab)


def test_incompatible_core_refused(lab: dict[str, Any]) -> None:
    old = lab["site"] / "pds_core-0.6.6.dist-info"
    new = lab["site"] / "pds_core-0.6.3.dist-info"
    old.rename(new)
    (new / "METADATA").write_text(
        "Metadata-Version: 2.3\nName: pds-core\nVersion: 0.6.3\n"
    )
    with pytest.raises(subject.SignedLabLaunchError, match="dependency version"):
        _run(lab)


def test_second_launcher_owner_refused(lab: dict[str, Any]) -> None:
    owner = lab["site"] / "evil-1.0.dist-info"
    owner.mkdir()
    (owner / "METADATA").write_text("Metadata-Version: 2.3\nName: evil\nVersion: 1.0\n")
    (owner / "entry_points.txt").write_text(
        "[console_scripts]\nquillan = evil.cli:main\n"
    )
    with pytest.raises(subject.SignedLabLaunchError, match="ownership"):
        _run(lab)


def test_wrong_lab_name_refused(lab: dict[str, Any]) -> None:
    with pytest.raises(subject.SignedLabLaunchError, match="non-lab"):
        subject.inspect_signed_quillan_lab(
            lab["site"],
            wheel=lab["wheel"],
            policy=lab["files"]["trust-policy.json"],
            independent_policy_sha256=lab["pin"],
            registry=lab["files"]["registry-envelope.json"],
            module=lab["files"]["quillan-envelope.json"],
            now=datetime.now(timezone.utc),
        )


def test_inherited_site_packages_refused(lab: dict[str, Any]) -> None:
    (lab["root"] / "pyvenv.cfg").write_text(
        "include-system-site-packages = true\nversion = 3.11.9\n"
    )
    with pytest.raises(subject.SignedLabLaunchError, match="inherit"):
        _run(lab)


def test_direct_url_requirement_refused(lab: dict[str, Any]) -> None:
    info = lab["site"] / "qrcode-8.2.dist-info" / "METADATA"
    info.write_text(
        "Metadata-Version: 2.3\nName: qrcode\nVersion: 8.2\n"
        "Requires-Dist: pillow @ https://example.invalid/unsafe.whl\n"
    )
    with pytest.raises(subject.SignedLabLaunchError, match="direct-URL"):
        _run(lab)


def test_missing_windows_launcher_refused(lab: dict[str, Any]) -> None:
    (lab["root"] / "Scripts" / "quillan.exe").unlink()
    with pytest.raises(subject.SignedLabLaunchError, match="required lab path"):
        _run(lab)


def test_python_version_bound_refused(lab: dict[str, Any]) -> None:
    info = lab["site"] / "pds_core-0.6.6.dist-info" / "METADATA"
    info.write_text(
        "Metadata-Version: 2.3\nName: pds-core\nVersion: 0.6.6\n"
        "Requires-Python: >=3.15\n"
    )
    with pytest.raises(subject.SignedLabLaunchError, match="lab Python"):
        _run(lab)


def test_default_mode_does_not_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subject, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        subject,
        "inspect_signed_quillan_lab",
        lambda *a, **k: subject.SignedLabObservation(
            "quillan", "0.10.6", "a" * 64, "b" * 64, 5, 4, "quillan", "c" * 64
        ),
    )
    monkeypatch.setattr(
        subject.subprocess,
        "run",
        lambda *a, **k: pytest.fail("the default check must never launch"),
    )
    assert (
        subject.main(
            [
                "--lab-venv",
                "lab",
                "--wheel",
                "wheel",
                "--trust-policy",
                "policy",
                "--trust-sha256",
                "b" * 64,
                "--registry",
                "registry",
                "--module",
                "module",
            ]
        )
        == 0
    )
