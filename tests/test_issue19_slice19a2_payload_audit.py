"""Suite #19A2: on-disk wheel evidence never grants Core handler permission."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import zipfile
from dataclasses import FrozenInstanceError, replace
from importlib import metadata
from pathlib import Path

import pytest

from paper_data_suite.returned_paper_installed_wheels import OfficialWheel
from paper_data_suite.returned_paper_payload_audit import (
    InstalledPayloadAuditError,
    InstalledPayloadAuditV1,
    MatchedWheelPayloadV1,
    audit_installed_paper_payloads,
)


class InstalledFixture:
    def __init__(self, base: Path) -> None:
        self.root = base / "env"
        self.site = self.root / "Lib" / "site-packages"
        self.wheelhouse = base / "wheels"
        self.site.mkdir(parents=True)
        self.wheelhouse.mkdir()
        self.specifications: list[OfficialWheel] = []
        self.dists: dict[str, metadata.Distribution] = {}
        for dist, version, package in (
            ("pds-core", "0.6.6", "pds_core"),
            ("scoreform", "0.13.0", "scoreform"),
            ("quillan", "0.10.6", "quillan"),
        ):
            self._write_wheel(dist, version, package)

    def _write_wheel(self, dist: str, version: str, package: str) -> None:
        root = f"{package}-{version}.dist-info"
        metadata_text = (
            "Metadata-Version: 2.2\n"
            f"Name: {dist}\n"
            f"Version: {version}\n"
        )
        members = {
            f"{package}/__init__.py": "__version__ = 'test'\n".encode(),
            f"{package}/routing.py": b"def stable(): return True\n",
            f"{root}/WHEEL": b"Wheel-Version: 1.0\n",
            f"{root}/METADATA": metadata_text.encode(),
            f"{root}/RECORD": b"",
        }
        if dist != "pds-core":
            members[f"{root}/entry_points.txt"] = (
                "[paper_data_suite.modules]\n"
                f"{dist} = {package}.pds_module:get_module_profile\n"
            ).encode()
        filename = f"{package}-{version}-py3-none-any.whl"
        wheel = self.wheelhouse / filename
        with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
            for member, data in members.items():
                archive.writestr(member, data)
        record = io.StringIO(newline="")
        writer = csv.writer(record)
        for member, data in members.items():
            target = self.site / member
            target.parent.mkdir(parents=True, exist_ok=True)
            if not member.endswith("/RECORD"):
                target.write_bytes(data)
            writer.writerow([member, "", ""])
        # Preserve CSV CRLF once: Windows text-mode translation doubles CR.
        (self.site / root / "RECORD").write_bytes(
            record.getvalue().encode("utf-8")
        )
        self.specifications.append(OfficialWheel(
            dist, version, filename, hashlib.sha256(wheel.read_bytes()).hexdigest(),
            None if dist == "pds-core" else dist,
            None if dist == "pds-core" else (
                f"{package}.pds_module:get_module_profile"
            ),
        ))
        self.dists[dist] = metadata.PathDistribution(self.site / root)

    def audit(self) -> InstalledPayloadAuditV1:
        return audit_installed_paper_payloads(
            self.wheelhouse,
            environment_root=self.root,
            distribution_lookup=self.dists.__getitem__,
            specifications=tuple(self.specifications),
        )


@pytest.fixture
def fixture(tmp_path: Path) -> InstalledFixture:
    return InstalledFixture(tmp_path)


def test_three_exact_payloads_are_matched_but_dispatch_still_denied(
    fixture: InstalledFixture,
) -> None:
    result = fixture.audit()
    assert tuple(row.distribution for row in result.wheels) == (
        "pds-core", "scoreform", "quillan"
    )
    assert tuple(row.version for row in result.wheels) == (
        "0.6.6", "0.13.0", "0.10.6"
    )
    assert all(row.file_count >= 4 for row in result.wheels)
    assert result.contract_version == "1"
    assert result.producer_dispatch_authorized is False


def test_installed_record_has_one_line_per_csv_row(
    fixture: InstalledFixture,
) -> None:
    # Python 3.11 importlib.metadata splits lines before csv.reader.
    # Do not create CRCRLF through Windows text-mode newline translation.
    record = fixture.site / "scoreform-0.13.0.dist-info" / "RECORD"
    raw = record.read_bytes()
    assert b"\r\n" in raw
    assert b"\r\r\n" not in raw
    assert len(raw.splitlines()) == len(tuple(fixture.dists["scoreform"].files or ()))


def test_malformed_record_csv_fails_closed(
    fixture: InstalledFixture,
) -> None:
    record = fixture.site / "scoreform-0.13.0.dist-info" / "RECORD"
    record.write_bytes(b"\r\n" + record.read_bytes())
    with pytest.raises(InstalledPayloadAuditError, match="RECORD"):
        fixture.audit()


def test_pip_generated_record_is_not_falsely_compared(
    fixture: InstalledFixture,
) -> None:
    assert fixture.audit().wheels[0].file_count == 4


@pytest.mark.parametrize("case", [
    "source_modified", "source_missing", "metadata_modified", "metadata_missing",
    "wheel_modified", "wheel_missing", "wheel_symlink", "record_missing",
    "wrong_dist_name", "wrong_version", "wheelhouse_missing", "different_root",
])
def test_changed_or_unavailable_installed_evidence_refused(
    fixture: InstalledFixture, case: str, tmp_path: Path,
) -> None:
    file = fixture.site / "scoreform" / "routing.py"
    meta = fixture.site / "scoreform-0.13.0.dist-info" / "METADATA"
    archive = fixture.wheelhouse / "scoreform-0.13.0-py3-none-any.whl"
    if case == "source_modified":
        file.write_bytes(b"untrusted")
    elif case == "source_missing":
        file.unlink()
    elif case == "metadata_modified":
        meta.write_bytes(b"untrusted")
    elif case == "metadata_missing":
        meta.unlink()
    elif case == "wheel_modified":
        archive.write_bytes(archive.read_bytes() + b"untrusted")
    elif case == "wheel_missing":
        archive.unlink()
    elif case == "wheel_symlink":
        target = tmp_path / "wheel-original.whl"
        archive.rename(target)
        try:
            archive.symlink_to(target)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"symlink privilege unavailable: {error}")
    elif case == "record_missing":
        (fixture.site / "scoreform-0.13.0.dist-info" / "RECORD").unlink()
    elif case == "wrong_dist_name":
        text = meta.read_text(encoding="utf-8")
        meta.write_text(text.replace("Name: scoreform", "Name: other"))
    elif case == "wrong_version":
        text = meta.read_text(encoding="utf-8")
        meta.write_text(text.replace("Version: 0.13.0", "Version: 0.13.1"))
    elif case == "wheelhouse_missing":
        fixture.wheelhouse.rename(tmp_path / "moved_wheels")
    elif case == "different_root":
        fixture.root = tmp_path / "elsewhere"
        fixture.root.mkdir()
    with pytest.raises(InstalledPayloadAuditError):
        fixture.audit()


def test_a_second_symlink_to_an_installed_file_is_refused(
    fixture: InstalledFixture, tmp_path: Path,
) -> None:
    file = fixture.site / "scoreform" / "routing.py"
    target = tmp_path / "original.py"
    file.rename(target)
    try:
        file.symlink_to(target)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink privilege unavailable: {error}")
    with pytest.raises(InstalledPayloadAuditError):
        fixture.audit()


def test_changed_installed_record_inventory_refused(
    fixture: InstalledFixture,
) -> None:
    record = fixture.site / "scoreform-0.13.0.dist-info" / "RECORD"
    lines = record.read_text(encoding="utf-8").splitlines()
    record.write_text("\n".join(
        item for item in lines if "routing.py" not in item
    ) + "\n")
    with pytest.raises(InstalledPayloadAuditError):
        fixture.audit()


def test_profile_factories_are_not_imported(
    fixture: InstalledFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    original = builtins.__import__
    forbidden = ("scoreform", "quillan", "pds_core.module_profiles")

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith(forbidden):
            raise AssertionError(f"unexpected producer import: {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert fixture.audit().producer_dispatch_authorized is False


def test_report_cannot_be_converted_into_permission(
    fixture: InstalledFixture,
) -> None:
    report = fixture.audit()
    with pytest.raises(InstalledPayloadAuditError):
        replace(report, producer_dispatch_authorized=True)  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        report.wheels = ()  # type: ignore[misc]
    with pytest.raises(InstalledPayloadAuditError):
        MatchedWheelPayloadV1("scoreform", "0.13.0", "bad", 1)


def test_untrusted_override_still_never_authorizes_dispatch(
    fixture: InstalledFixture,
) -> None:
    cloned = tuple(replace(s, sha256=s.sha256) for s in fixture.specifications)
    result = audit_installed_paper_payloads(
        fixture.wheelhouse, environment_root=fixture.root,
        distribution_lookup=fixture.dists.__getitem__, specifications=cloned,
    )
    assert result.producer_dispatch_authorized is False


def test_missing_producer_is_not_silently_omitted(
    fixture: InstalledFixture,
) -> None:
    specs = tuple(fixture.specifications[:2])
    with pytest.raises(InstalledPayloadAuditError):
        audit_installed_paper_payloads(
            fixture.wheelhouse, environment_root=fixture.root,
            distribution_lookup=fixture.dists.__getitem__, specifications=specs,
        )


def test_no_network_or_outside_workspace_writes(
    fixture: InstalledFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = {str(path.relative_to(fixture.root)): path.read_bytes()
              for path in fixture.root.rglob("*") if path.is_file()}
    monkeypatch.setattr(os, "system", lambda *_: (_ for _ in ()).throw(
        AssertionError("no shell network calls")
    ))
    fixture.audit()
    after = {str(path.relative_to(fixture.root)): path.read_bytes()
             for path in fixture.root.rglob("*") if path.is_file()}
    assert before == after
