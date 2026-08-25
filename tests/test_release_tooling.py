from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest

from paper_data_suite.artifact_verification import (
    ArtifactVerificationError,
    verify_release_tool_wheel,
)
from paper_data_suite.release_tooling import (
    QualifiedReleaseTool,
    ReleaseToolingError,
    load_release_tooling_contract,
    parse_release_tooling_contract,
    release_tooling_contract_bytes,
    release_tooling_contract_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
TOOLING_PATH = ROOT / "paper_data_suite" / "data" / "release_tooling_v1.json"


def _raw() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(TOOLING_PATH.read_text(encoding="utf-8")))


def test_bundled_release_tooling_contract_is_exact() -> None:
    contract = load_release_tooling_contract()
    assert contract.record_type == "paper_data_suite_release_tooling"
    assert contract.contract_version == "1"
    assert len(contract.tools) == 1
    pip = contract.tools[0]
    assert pip.tool_id == "pip"
    assert pip.distribution == "pip"
    assert pip.version == "26.2.1"
    assert pip.requires_python == ">=3.10"
    assert pip.requires_dist == ()
    assert pip.wheel == "pip-26.2.1-py3-none-any.whl"
    assert pip.sha256 == (
        "71138adf1f4ca900cdb7d289c21b7494"
        "329f2332b6d85f0e1c42108c0384ed3e"
    )
    assert pip.url.startswith("https://files.pythonhosted.org/packages/")
    assert pip.url.endswith("/pip-26.2.1-py3-none-any.whl")


def test_release_tooling_digest_matches_exact_resource_bytes() -> None:
    assert release_tooling_contract_sha256() == hashlib.sha256(
        release_tooling_contract_bytes()
    ).hexdigest()


@pytest.mark.parametrize("field", ["version", "wheel", "sha256", "url"])
def test_release_tooling_contract_rejects_identity_tampering(field: str) -> None:
    data = copy.deepcopy(_raw())
    values = {
        "version": "26.2.0",
        "wheel": "pip-26.2.0-py3-none-any.whl",
        "sha256": "0" * 63,
        "url": "https://example.invalid/pip-26.2.1-py3-none-any.whl",
    }
    data["tools"][0][field] = values[field]
    with pytest.raises(ReleaseToolingError):
        parse_release_tooling_contract(json.dumps(data))


def _write_synthetic_pip_wheel(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "pip-26.2.1.dist-info/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: pip\n"
            "Version: 26.2.1\n"
            "Requires-Python: >=3.10\n\n",
        )


def test_release_tool_wheel_verifier_checks_hash_and_metadata(tmp_path: Path) -> None:
    wheel = tmp_path / "pip-26.2.1-py3-none-any.whl"
    _write_synthetic_pip_wheel(wheel)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    tool = QualifiedReleaseTool(
        tool_id="pip",
        distribution="pip",
        version="26.2.1",
        requires_python=">=3.10",
        requires_dist=(),
        wheel=wheel.name,
        sha256=digest,
        url="https://files.pythonhosted.org/packages/test/" + wheel.name,
    )
    verify_release_tool_wheel(tool, wheel)

    bad = QualifiedReleaseTool(
        tool_id=tool.tool_id,
        distribution=tool.distribution,
        version=tool.version,
        requires_python=tool.requires_python,
        requires_dist=tool.requires_dist,
        wheel=tool.wheel,
        sha256="0" * 64,
        url=tool.url,
    )
    with pytest.raises(ArtifactVerificationError, match="SHA-256 mismatch"):
        verify_release_tool_wheel(bad, wheel)
