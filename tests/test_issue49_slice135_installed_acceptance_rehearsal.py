"""Slice 135: full installed-machine rehearsal must remain unattested."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "paper_data_suite/evergreen_windows_installed_acceptance_rehearsal.py"
DOC = ROOT / "docs/architecture/issue-49-slice-135-installed-acceptance.md"
NO_AUTHORITY = "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"


@pytest.fixture(scope="module")
def module() -> Any:
    spec = importlib.util.spec_from_file_location("slice135_rehearsal", MODULE)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def evidence() -> dict[str, dict[str, object]]:
    """All five claim consistency, never independent administrator authority."""
    return {
        "teacher": {
            "status": "ALL_EIGHT_SCM_DENIALS_OBSERVED_UNATTESTED",
            "native_read_only": True,
            "ordinary_primary_token_observed": True,
            "service_present": True,
            "access_checks_complete": True,
            "all_eight_dangerous_rights_denied": True,
            "any_dangerous_right_granted": False,
            "independent_teacher_identity_attested": False,
            "installed_service_identity_verified": False,
            "publisher_pin_provisioned": False,
            "protected_write_performed": False,
            "authorized_to_install": False,
            "authority": NO_AUTHORITY,
        },
        "service_access": {
            "status": "SCM_CURRENT_TOKEN_ACCESS_OBSERVED_UNVERIFIED",
            "native_read_only": True,
            "service_present": True,
            "access_query_complete": True,
            **{
                field: False
                for field in (
                    "change_config_access_granted",
                    "delete_access_granted",
                    "write_dac_access_granted",
                    "write_owner_access_granted",
                    "start_access_granted",
                    "stop_access_granted",
                    "pause_access_granted",
                    "user_control_access_granted",
                    "independent_teacher_token_verified",
                    "service_identity_verified",
                    "protected_state_write_performed",
                    "authorized_to_provision",
                    "authorized_to_install",
                )
            },
            "authority": NO_AUTHORITY,
        },
        "service_security": {
            "status": "SCM_SECURITY_METADATA_OBSERVED_UNVERIFIED",
            "native_read_only": True,
            "service_present": True,
            "service_dacl_observed": True,
            "service_sid_type_observed": True,
            "mutation_ace_observed": True,
            "service_identity_verified": False,
            "effective_teacher_rights_verified": False,
            "publisher_pin_provisioned": False,
            "protected_state_write_performed": False,
            "authorized_to_provision": False,
            "authorized_to_install": False,
            "authority": NO_AUTHORITY,
        },
        "service_image": {
            "status": "SCM_PROCESS_IMAGE_LINKAGE_OBSERVED_UNVERIFIED",
            "native_read_only": True,
            "service_present": True,
            "running_process_observed": True,
            "scm_process_image_agreement_observed": True,
            "held_image_attributes_observed": True,
            "image_owner_sid_observed": True,
            "image_dacl_observed": True,
            "image_mutation_allow_ace_observed": True,
            "installed_service_identity_verified": False,
            "executable_custody_verified": False,
            "independent_teacher_identity_attested": False,
            "publisher_pin_verified": False,
            "protected_write_performed": False,
            "authorized_to_install": False,
            "authority": NO_AUTHORITY,
        },
        "publisher_pin": {
            "status": "NATIVE_PIN_CLAIM_OBSERVED_CUSTODY_UNPROVEN",
            "native_read_only": True,
            "publisher_pin_claim_observed": True,
            "independent_provisioner_authenticated": False,
            "rollback_protection_verified": False,
            "publisher_pin_verified": False,
            "authorized_to_install": False,
            "authority": NO_AUTHORITY,
        },
    }


def observations(module: Any) -> dict[str, Any]:
    result = {}
    for name, fields in evidence().items():
        encoded = (
            json.dumps(fields, separators=(",", ":")) + "\n" + NO_AUTHORITY + "\n"
        ).encode()
        result[name] = module.parse_native_output(name, 2, encoded)
    return result


def test_assets_and_explicit_documented_scope() -> None:
    for item in (MODULE, DOC):
        assert item.is_file()
        assert 100 < item.stat().st_size < 22000
    for required in (
        "five",
        "ordinary",
        "installed",
        "unattested",
        "read-only",
        "independent administrator",
        "no installation",
        "rollback",
    ):
        assert required in DOC.read_text(encoding="utf-8").lower()


def test_complete_observations_still_refuse_installer_authority(module: Any) -> None:
    report = module.review_rehearsal(observations(module))
    assert report == "INSTALLED_MACHINE_NEGATIVE_REHEARSAL_OBSERVED_UNATTESTED"


@pytest.mark.parametrize("missing", list(evidence()))
def test_missing_any_independent_probe_refuses(module: Any, missing: str) -> None:
    record = observations(module)
    del record[missing]
    with pytest.raises(module.RehearsalRefused):
        module.review_rehearsal(record)


@pytest.mark.parametrize(
    ("probe", "field", "value"),
    (
        ("teacher", "ordinary_primary_token_observed", False),
        ("teacher", "all_eight_dangerous_rights_denied", False),
        ("teacher", "any_dangerous_right_granted", True),
        ("teacher", "independent_teacher_identity_attested", True),
        ("teacher", "installed_service_identity_verified", True),
        ("service_access", "write_dac_access_granted", True),
        ("service_access", "delete_access_granted", True),
        ("service_access", "service_present", False),
        ("service_security", "service_sid_type_observed", False),
        ("service_image", "running_process_observed", False),
        ("service_image", "held_image_attributes_observed", False),
        ("service_image", "image_owner_sid_observed", False),
        ("service_image", "image_dacl_observed", False),
        ("publisher_pin", "publisher_pin_claim_observed", False),
        ("publisher_pin", "independent_provisioner_authenticated", True),
        ("publisher_pin", "rollback_protection_verified", True),
    ),
)
def test_conflicting_probes_fail_closed(
    module: Any, probe: str, field: str, value: bool
) -> None:
    report = observations(module)
    data = dict(report[probe].fields)
    data[field] = value
    report[probe] = module.ProbeObservation(report[probe].status, 2, data)
    with pytest.raises(module.RehearsalRefused):
        module.review_rehearsal(report)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("teacher", "CURRENT_TOKEN_NOT_ORDINARY_NO_ACCEPTANCE"),
        ("teacher", "SERVICE_NOT_INSTALLED_NO_TEACHER_ACCEPTANCE"),
        ("service_image", "SERVICE_NOT_RUNNING_NO_IMAGE_ACCEPTANCE"),
        ("publisher_pin", "NATIVE_PIN_CLAIM_NOT_OBSERVED"),
    ),
)
def test_wrong_status_refuses(module: Any, name: str, value: str) -> None:
    report = observations(module)
    data = dict(report[name].fields)
    data["status"] = value
    report[name] = module.ProbeObservation(value, 1, data)
    with pytest.raises(module.RehearsalRefused):
        module.review_rehearsal(report)


@pytest.mark.parametrize(
    "raw",
    (
        b"{}\n" + NO_AUTHORITY.encode() + b"\n",
        b'{"status":"SCM_X","status":"SCM_Y","authority":"'
        + NO_AUTHORITY.encode()
        + b'"}\n'
        + NO_AUTHORITY.encode()
        + b"\n",
        b"\xef\xbb\xbf{}\n" + NO_AUTHORITY.encode() + b"\n",
        b"\xff{}\n" + NO_AUTHORITY.encode() + b"\n",
        b"{}\r\n" + NO_AUTHORITY.encode() + b"\n",
        b"{}\nEXTRA\n" + NO_AUTHORITY.encode() + b"\n",
        b"x" * 8193,
        b"{}\x00\n" + NO_AUTHORITY.encode() + b"\n",
    ),
)
def test_bounded_strict_native_parser_refuses(module: Any, raw: bytes) -> None:
    with pytest.raises(module.RehearsalRefused):
        module.parse_native_output("teacher", 2, raw)


def test_windows_crlf_native_output_is_accepted(module: Any) -> None:
    record = evidence()["teacher"]
    text = json.dumps(record, separators=(",", ":"))
    raw = (text + "\r\n" + NO_AUTHORITY + "\r\n").encode()
    accepted = module.parse_native_output("teacher", 2, raw)
    assert accepted.status == "ALL_EIGHT_SCM_DENIALS_OBSERVED_UNATTESTED"


def test_unknown_boolean_and_duplicate_authority_refuse(module: Any) -> None:
    data = evidence()["teacher"]
    data["new_install_approval"] = True
    serialized = (json.dumps(data) + "\n" + NO_AUTHORITY + "\n").encode()
    result = module.parse_native_output("teacher", 2, serialized)
    report = observations(module)
    report["teacher"] = result
    with pytest.raises(module.RehearsalRefused):
        module.review_rehearsal(report)


def test_non_boolean_and_wrong_code_refuse(module: Any) -> None:
    data = evidence()["teacher"]
    data["authorized_to_install"] = 0
    raw = (json.dumps(data) + "\n" + NO_AUTHORITY + "\n").encode()
    with pytest.raises(module.RehearsalRefused):
        module.parse_native_output("teacher", 2, raw)
    with pytest.raises(module.RehearsalRefused):
        module.parse_native_output("teacher", 0, raw)


def test_rehearsal_never_passes_on_non_windows(module: Any, tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("non-Windows guard only")
    with pytest.raises(module.RehearsalRefused, match="requires Windows"):
        module.run_local_rehearsal(tmp_path)


def test_executable_provenance_is_not_claimed(module: Any) -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert "subprocess.run(" in source
    assert "capture_output=True" in source
    assert "shell=True" not in source
    assert "CreateService" not in source
    assert "SetNamedSecurityInfo" not in source
    assert 'rollback_protection_verified": False' in source
    assert "return 2  # Observations only." in source


def test_cli_complete_case_is_still_exit_two(
    module: Any, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(
        module,
        "run_local_rehearsal",
        lambda unused: module.review_rehearsal(observations(module)),
    )
    rc = module.main(["--build-dir", "/disposable/build"])
    text = capsys.readouterr().out.splitlines()
    assert rc == 2
    assert text[1] == NO_AUTHORITY
    message = json.loads(text[0])
    assert message["native_observations_complete"] is True
    assert message["authorized_to_install"] is False
    assert message["independent_administrator_approved"] is False
    assert message["publisher_pin_verified"] is False


def test_cli_missing_machine_state_refuses_exit_one(
    module: Any, capsys: Any, monkeypatch: Any
) -> None:
    def refuse(_unused: Path) -> str:
        raise module.RehearsalRefused("service unavailable")

    monkeypatch.setattr(module, "run_local_rehearsal", refuse)
    rc = module.main(["--build-dir", "/disposable/build"])
    output = capsys.readouterr()
    assert rc == 1
    assert "REFUSED_INSTALLED_MACHINE_REHEARSAL" in output.err
    assert NO_AUTHORITY in output.err
    assert output.out == ""


def test_all_five_executables_have_fixed_names(module: Any) -> None:
    assert [name for name, _ in module._PROBES] == list(evidence())
    assert len({name for _, name in module._PROBES}) == 5
    assert all(filename.endswith(".exe") for _, filename in module._PROBES)


def test_no_writable_rehearsal_artifacts(module: Any, monkeypatch: Any) -> None:
    """No program state or protected file should be generated by CLI refusal."""
    monkeypatch.setattr(
        module,
        "run_local_rehearsal",
        lambda _: (_ for _ in ()).throw(module.RehearsalRefused("missing")),
    )
    assert module.main(["--build-dir", "/nonexistent/build"]) == 1
