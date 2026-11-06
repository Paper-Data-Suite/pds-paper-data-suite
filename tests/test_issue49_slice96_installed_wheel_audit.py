"""Issue #49 Slice 96: local wheel observations cannot grant trust or launch."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from dataclasses import fields, replace
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

from paper_data_suite.evergreen_installed_wheel_audit import (
    APPROVED_DISTRIBUTIONS,
    InstalledAuditError,
    InstalledWheelEvidence,
    _canonical_name,
    audit_active_interpreter,
    inspect_distribution,
    main,
)


def _digest(content: bytes) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
    )


def _put_record(info: Path, rows: list[tuple[str, str, str]]) -> None:
    output = io.StringIO()
    csv.writer(output, lineterminator="\n").writerows(rows)
    (info / "RECORD").write_text(output.getvalue(), encoding="utf-8")


@pytest.fixture
def installed(tmp_path: Path) -> dict[str, Any]:
    environment = tmp_path / "env"
    package_root = environment / "Lib" / "site-packages"
    info = package_root / "pds_core-0.6.6.dist-info"
    info.mkdir(parents=True)
    package = package_root / "pds_core"
    package.mkdir()
    content = b"__version__ = '0.6.6'\n"
    (package / "__init__.py").write_bytes(content)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.3\nName: pds-core\nVersion: 0.6.6\n",
        encoding="utf-8",
    )
    (info / "WHEEL").write_text(
        "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\n"
        "Tag: py3-none-any\n",
        encoding="utf-8",
    )
    (info / "entry_points.txt").write_text(
        "[console_scripts]\npds-core = pds_core.cli:main\n", encoding="utf-8"
    )
    rows = [
        ("pds_core/__init__.py", f"sha256={_digest(content)}", str(len(content))),
        ("pds_core-0.6.6.dist-info/RECORD", "", ""),
    ]
    _put_record(info, rows)
    return {
        "env": environment,
        "info": info,
        "pkg": package,
        "rows": rows,
        "dist": metadata.Distribution.at(str(info)),
    }


def _observe(r: dict[str, Any]) -> InstalledWheelEvidence:
    return inspect_distribution("pds-core", r["dist"], r["env"])


def test_local_inventory_never_grants_provenance_or_launch(
    installed: dict[str, Any],
) -> None:
    item = _observe(installed)
    assert item.status == "LOCAL_INVENTORY_ONLY"
    assert item.record_status == "LOCAL_MATCH"
    assert item.record_files_checked == 1
    assert item.installed_version == "0.6.6"
    assert item.wheel_tags == ("py3-none-any",)
    assert item.launcher_names == ("pds-core",)
    assert item.inside_active_interpreter is True
    assert item.editable is None
    assert item.provenance == "UNAUTHENTICATED_LOCAL_EVIDENCE_ONLY"
    assert "NO_INSTALL_LAUNCH" in item.authority
    assert not any(f.name == "authenticated" for f in fields(item))


def test_changed_installed_bytes_detected(installed: dict[str, Any]) -> None:
    (installed["pkg"] / "__init__.py").write_bytes(b"__version__ = '0.6.7'\n")
    item = _observe(installed)
    assert item.status == "REVIEW_REQUIRED"
    assert item.record_status == "DRIFT"
    assert "installed_file_digest_changed" in item.findings


def test_missing_installed_file_detected(installed: dict[str, Any]) -> None:
    (installed["pkg"] / "__init__.py").unlink()
    assert _observe(installed).record_status == "DRIFT"


def test_size_change_detected(installed: dict[str, Any]) -> None:
    (installed["pkg"] / "__init__.py").write_bytes(b"bad")
    assert "installed_file_size_changed" in _observe(installed).findings


def test_unsafe_record_entry_path_refused(installed: dict[str, Any]) -> None:
    _put_record(installed["info"], [("../../../../../outside", "", "")])
    item = _observe(installed)
    assert item.record_status == "INVALID"
    assert "record_path_outside_environment" in item.findings


def test_absolute_record_path_refused(installed: dict[str, Any]) -> None:
    _put_record(installed["info"], [("/unexpected/path", "", "")])
    assert "invalid_record_path" in _observe(installed).findings


def test_backslash_record_path_refused(installed: dict[str, Any]) -> None:
    _put_record(installed["info"], [(r"..\other", "", "")])
    assert "invalid_record_path" in _observe(installed).findings


def test_duplicate_record_entries_refused(installed: dict[str, Any]) -> None:
    _put_record(installed["info"], [installed["rows"][0]] * 2)
    assert "invalid_record_row" in _observe(installed).findings


def test_unsupported_record_digest_does_not_establish_integrity(
    installed: dict[str, Any],
) -> None:
    _put_record(installed["info"], [("pds_core/__init__.py", "md5=fake", "")])
    item = _observe(installed)
    assert item.record_status == "UNVERIFIABLE"
    assert item.status == "REVIEW_REQUIRED"


def test_missing_record_does_not_establish_integrity(
    installed: dict[str, Any],
) -> None:
    (installed["info"] / "RECORD").unlink()
    assert _observe(installed).record_status == "MISSING"


def test_unhashed_code_file_is_review_required(installed: dict[str, Any]) -> None:
    _put_record(
        installed["info"],
        [("pds_core/__init__.py", "", "")],
    )
    assert "record_contains_unhashed_entries" in _observe(installed).findings


def test_metadata_identity_mismatch_refused(installed: dict[str, Any]) -> None:
    raw = (installed["info"] / "METADATA").read_text(encoding="utf-8")
    (installed["info"] / "METADATA").write_text(
        raw.replace("Name: pds-core", "Name: foreign-package"), encoding="utf-8"
    )
    assert "installed_identity_mismatch" in _observe(installed).findings


def test_editable_install_cannot_be_accepted(installed: dict[str, Any]) -> None:
    (installed["info"] / "direct_url.json").write_text(
        json.dumps({"dir_info": {"editable": True}, "url": "file:///ignored"}),
        encoding="utf-8",
    )
    item = _observe(installed)
    assert item.editable is True
    assert "editable_install_not_accepted" in item.findings


def test_missing_wheel_tags_reported(installed: dict[str, Any]) -> None:
    (installed["info"] / "WHEEL").unlink()
    assert "wheel_tags_unavailable" in _observe(installed).findings


def test_missing_launcher_reported(installed: dict[str, Any]) -> None:
    (installed["info"] / "entry_points.txt").unlink()
    assert "console_script_not_observed" in _observe(installed).findings


def test_wrong_interpreter_environment_refused(installed: dict[str, Any]) -> None:
    foreign = installed["env"].parent / "different-env"
    item = inspect_distribution("pds-core", installed["dist"], foreign)
    assert "distribution_outside_active_interpreter" in item.findings
    assert item.inside_active_interpreter is False


def test_unapproved_distribution_refused(installed: dict[str, Any]) -> None:
    with pytest.raises(InstalledAuditError, match="unapproved"):
        inspect_distribution("random-user-package", installed["dist"], installed["env"])


@pytest.mark.parametrize("name", ["", "../pkg", "foo/bar", "a" * 65])
def test_unsafe_distribution_identity_refused(name: str) -> None:
    with pytest.raises(InstalledAuditError, match="invalid"):
        _canonical_name(name)


def test_dashes_and_underscores_normalized() -> None:
    assert _canonical_name("PDS_CORE") == "pds-core"


def test_missing_distributions_reported_without_importing_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> metadata.Distribution:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "distribution", missing)
    result = audit_active_interpreter(("pds-core",))
    assert len(result) == 1
    assert result[0].status == "NOT_INSTALLED_IN_THIS_INTERPRETER"
    assert result[0].provenance == "UNAUTHENTICATED_LOCAL_EVIDENCE_ONLY"


def test_duplicate_selection_refused() -> None:
    with pytest.raises(InstalledAuditError, match="duplicate"):
        audit_active_interpreter(("pds-core", "PDS_CORE"))


def test_unknown_selection_refused() -> None:
    with pytest.raises(InstalledAuditError, match="unapproved"):
        audit_active_interpreter(("other",))


def test_two_distributions_claiming_same_script_flagged(
    installed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = installed["dist"]
    original = inspect_distribution("pds-core", source, installed["env"])
    colliding = replace(
        original,
        distribution="quillan",
    )
    assert original.launcher_names == colliding.launcher_names

    def lookup(name: str) -> metadata.Distribution:
        return source

    monkeypatch.setattr(metadata, "distribution", lookup)
    monkeypatch.setattr("sys.prefix", str(installed["env"]))
    observations = audit_active_interpreter(("pds-core", "quillan"))
    assert len(observations) == 2
    assert all("shared_console_script_identity" in o.findings for o in observations)


def test_cli_emits_anonymized_and_non_authorizing_json(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["audit", "--distribution", "pds-core"])

    def fake(names: tuple[str, ...]) -> tuple[InstalledWheelEvidence, ...]:
        assert names == ("pds-core",)
        return (
            InstalledWheelEvidence(
                distribution="pds-core",
                status="NOT_INSTALLED_IN_THIS_INTERPRETER",
                installed_version=None,
                inside_active_interpreter=None,
                editable=None,
                wheel_tags=(),
                launcher_names=(),
                record_status="NOT_AVAILABLE",
                record_files_checked=0,
                findings=("module_not_installed",),
            ),
        )

    monkeypatch.setattr(
        "paper_data_suite.evergreen_installed_wheel_audit.audit_active_interpreter",
        fake,
    )
    assert main() == 0
    body = capsys.readouterr().out
    item = json.loads(body)
    assert item["acceptance"] == "NOT_ESTABLISHED"
    assert "NO_INSTALL_LAUNCH" in item["authority"]
    assert "root" not in item
    assert len(item["distributions"]) == 1


def test_official_distribution_names_are_not_repo_names() -> None:
    assert APPROVED_DISTRIBUTIONS == (
        "paper-data-suite",
        "pds-core",
        "scoreform",
        "quillan",
        "pds-concord",
        "pds-meridian",
        "pds-vitrine",
        "pds-portia",
    )
    assert "pds-scoreform" not in APPROVED_DISTRIBUTIONS
    assert "pds-quillan" not in APPROVED_DISTRIBUTIONS


def test_metadata_lookup_requests_official_distribution_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def missing(name: str) -> metadata.Distribution:
        observed.append(name)
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "distribution", missing)
    result = audit_active_interpreter(("scoreform", "quillan"))
    assert observed == ["scoreform", "quillan"]
    assert all(x.status == "NOT_INSTALLED_IN_THIS_INTERPRETER" for x in result)


def test_repository_labels_cannot_replace_distribution_identity(
    installed: dict[str, Any],
) -> None:
    for repo_label in ("pds-scoreform", "pds-quillan"):
        with pytest.raises(InstalledAuditError, match="unapproved"):
            inspect_distribution(repo_label, installed["dist"], installed["env"])


def test_approved_inventory_does_not_expand_to_arbitrary_packages() -> None:
    assert len(APPROVED_DISTRIBUTIONS) == 8
    assert "clavis" not in APPROVED_DISTRIBUTIONS
    assert all(_canonical_name(p) == p for p in APPROVED_DISTRIBUTIONS)
