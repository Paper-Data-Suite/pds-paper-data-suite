"""#18 Slice 6A: official wheel identity and fail-closed producer admission."""

from __future__ import annotations

import hashlib
import sys
import types
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

import paper_data_suite.returned_paper_installed_wheels as wheels
from paper_data_suite.returned_paper_installed_wheels import (
    OfficialWheel,
    WheelQualificationError,
    qualify_installed_profiles,
    verify_official_wheel,
    verify_official_wheelhouse,
)


def _synthetic_wheel(
    root: Path,
    specification: OfficialWheel,
    *,
    wrong_owner: bool = False,
    wrong_entry: bool = False,
    unsafe: bool = False,
) -> OfficialWheel:
    path = root / specification.filename
    dist = specification.filename.split("-")[0]
    prefix = f"{dist}-{specification.version}.dist-info/"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(prefix + "WHEEL", "Wheel-Version: 1.0\n")
        archive.writestr(
            prefix + "METADATA",
            "Metadata-Version: 2.2\n"
            f"Name: {'other' if wrong_owner else specification.distribution}\n"
            f"Version: {specification.version}\n",
        )
        if specification.module is not None:
            target = (
                "wrong.factory:load" if wrong_entry else specification.entrypoint
            )
            archive.writestr(
                prefix + "entry_points.txt",
                "[paper_data_suite.modules]\n"
                f"{specification.module} = {target}\n",
            )
        if unsafe:
            archive.writestr("../escape.txt", "unsafe")
    return replace(specification, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def _fake_wheelhouse(tmp_path: Path) -> tuple[OfficialWheel, ...]:
    specs = (
        OfficialWheel("pds-core", "0.6.6", "pds_core-0.6.6-py3-none-any.whl", "0" * 64),
        OfficialWheel(
            "scoreform", "0.13.0", "scoreform-0.13.0-py3-none-any.whl",
            "0" * 64, "scoreform", "scoreform.pds_module:get_module_profile",
        ),
        OfficialWheel(
            "quillan", "0.10.6", "quillan-0.10.6-py3-none-any.whl",
            "0" * 64, "quillan", "quillan.pds_module:get_module_profile",
        ),
    )
    return tuple(_synthetic_wheel(tmp_path, item) for item in specs)


def test_official_manifest_identity_and_distinct_checksums() -> None:
    assert tuple(item.distribution for item in wheels.OFFICIAL_WHEELS) == (
        "pds-core", "scoreform", "quillan",
    )
    assert all(len(item.sha256) == 64 for item in wheels.OFFICIAL_WHEELS)
    assert len({item.sha256 for item in wheels.OFFICIAL_WHEELS}) == 3
    assert {item.module for item in wheels.OFFICIAL_WHEELS} == {
        None, "scoreform", "quillan",
    }


def test_exact_three_synthetic_wheel_structures_are_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = _fake_wheelhouse(tmp_path)
    monkeypatch.setattr(wheels, "OFFICIAL_WHEELS", specs)
    assert verify_official_wheelhouse(tmp_path) == tuple(
        tmp_path / item.filename for item in specs
    )


@pytest.mark.parametrize("kind", [
    "missing", "tampered", "bad_sha", "bad_metadata",
    "bad_entrypoint", "unsafe_member", "not_a_wheel", "symlink",
])
def test_wheel_refuses_invalid_or_unsafe_inputs(
    tmp_path: Path,
    kind: str,
) -> None:
    specification = OfficialWheel(
        "scoreform", "0.13.0", "scoreform-0.13.0-py3-none-any.whl",
        "0" * 64, "scoreform", "scoreform.pds_module:get_module_profile",
    )
    if kind == "missing":
        with pytest.raises(WheelQualificationError):
            verify_official_wheel(tmp_path, specification)
        return
    if kind == "bad_metadata":
        actual = _synthetic_wheel(tmp_path, specification, wrong_owner=True)
    elif kind == "bad_entrypoint":
        actual = _synthetic_wheel(tmp_path, specification, wrong_entry=True)
    elif kind == "unsafe_member":
        actual = _synthetic_wheel(tmp_path, specification, unsafe=True)
    else:
        actual = _synthetic_wheel(tmp_path, specification)
    path = tmp_path / specification.filename
    if kind == "tampered":
        path.write_bytes(path.read_bytes() + b"tamper")
    if kind == "symlink":
        target = tmp_path / "target.whl"
        path.rename(target)
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"symlink privilege unavailable: {error}")
    if kind == "bad_sha":
        actual = replace(actual, sha256="f" * 64)
    if kind == "not_a_wheel":
        path.write_bytes(b"not a wheel")
        actual = replace(actual, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(WheelQualificationError):
        verify_official_wheel(tmp_path, actual)


def test_wheelhouse_never_writes_or_imports_producers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = _fake_wheelhouse(tmp_path)
    monkeypatch.setattr(wheels, "OFFICIAL_WHEELS", specs)
    before = {x.name: x.read_bytes() for x in tmp_path.iterdir()}
    loaded_before = {
        name for name in sys.modules
        if name == "scoreform" or name.startswith("scoreform.")
        or name == "quillan" or name.startswith("quillan.")
    }
    assert len(verify_official_wheelhouse(tmp_path)) == 3
    assert {x.name: x.read_bytes() for x in tmp_path.iterdir()} == before
    loaded_after = {
        name for name in sys.modules
        if name == "scoreform" or name.startswith("scoreform.")
        or name == "quillan" or name.startswith("quillan.")
    }
    assert loaded_after == loaded_before


class _FakeRegistry:
    def __init__(self, *, wrong: bool = False) -> None:
        self.wrong = wrong

    def module_ids(self) -> tuple[str, ...]:
        if self.wrong:
            return ("quillan",)
        return ("quillan", "scoreform")

    def require(self, name: str) -> object:
        return types.SimpleNamespace(
            module_id=name, route_handler=lambda *_: None,
            supported_core_routing_contract_versions=frozenset({"1"}),
            supported_qr_schemas=frozenset({"PDS2"}),
            supported_route_registration_schema_versions=frozenset({"1"}),
            dispatchable_route_statuses=frozenset({"active"}),
        )


def _fake_installed_core(monkeypatch: pytest.MonkeyPatch, wrong: bool) -> None:
    fake_package = types.ModuleType("pds_core")
    fake_module = types.ModuleType("pds_core.module_profiles")
    fake_module.CORE_ROUTING_CONTRACT_VERSION = "1"  # type: ignore[attr-defined]
    fake_module.build_module_registry = (  # type: ignore[attr-defined]
        lambda **_: _FakeRegistry(wrong=wrong)
    )
    monkeypatch.setitem(sys.modules, "pds_core", fake_package)
    monkeypatch.setitem(sys.modules, "pds_core.module_profiles", fake_module)


def test_installed_fails_closed_on_incompatible_core_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_installed_core(monkeypatch, wrong=True)
    versions = {item.distribution: item.version for item in wheels.OFFICIAL_WHEELS}
    monkeypatch.setattr(wheels.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(
        wheels, "_installed_entry_points",
        lambda: {
            "quillan": ("quillan", "quillan.pds_module:get_module_profile"),
            "scoreform": ("scoreform", "scoreform.pds_module:get_module_profile"),
        },
    )
    with pytest.raises(WheelQualificationError, match="registry membership"):
        qualify_installed_profiles()


def test_installed_identity_and_compatible_core_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_installed_core(monkeypatch, wrong=False)
    versions = {item.distribution: item.version for item in wheels.OFFICIAL_WHEELS}
    monkeypatch.setattr(wheels.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(
        wheels, "_installed_entry_points",
        lambda: {
            "quillan": ("quillan", "quillan.pds_module:get_module_profile"),
            "scoreform": ("scoreform", "scoreform.pds_module:get_module_profile"),
        },
    )
    assert qualify_installed_profiles() == ("quillan", "scoreform")


def test_installed_wrong_provider_owner_rejected_before_registry_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_installed_core(monkeypatch, wrong=False)
    versions = {item.distribution: item.version for item in wheels.OFFICIAL_WHEELS}
    monkeypatch.setattr(wheels.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(
        wheels, "_installed_entry_points",
        lambda: {
            "quillan": ("not_quillan", "quillan.pds_module:get_module_profile"),
            "scoreform": ("scoreform", "scoreform.pds_module:get_module_profile"),
        },
    )
    with pytest.raises(WheelQualificationError, match="owners"):
        qualify_installed_profiles()
