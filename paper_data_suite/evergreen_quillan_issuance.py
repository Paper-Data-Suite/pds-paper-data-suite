"""Issue #49 Slice 100: reviewed local ceremony for the exact Quillan 0.10.6 wheel.

Create reviewable claims from already-hash-inspected official wheel bytes; sign
using explicitly provided offline keys; verify through existing PDS contracts.
This is NOT proof that a publisher has authorized those keys, an installed
receipt, dependency-lock authorization, nor permission to launch or activate.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Final, cast

from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    verify_registry_document,
)
from paper_data_suite.evergreen_offline_publisher import (
    OfflinePublisherError,
    public_key_from_encrypted,
    sign_catalog_payload,
)
from paper_data_suite.evergreen_release_artifacts import (
    ReleaseArtifactError,
    verify_signed_release_wheel,
)
from paper_data_suite.evergreen_trust_provisioning import (
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)

_WHEEL: Final = "quillan-0.10.6-py3-none-any.whl"
_SHA256: Final = "7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb"
_HEX: Final = re.compile(r"[0-9a-f]{64}\Z")
_NAMES: Final = (
    "trust-policy.json",
    "registry-payload.json",
    "quillan-payload.json",
    "review.json",
)


class IssuanceError(ValueError):
    """No claims were safely issued."""


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, limit: int) -> bytes:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or (getattr(info, "st_file_attributes", 0) & 0x400)
            or not 1 <= info.st_size <= limit
        ):
            raise IssuanceError("source must be bounded ordinary file")
        with path.open("rb") as stream:
            value = stream.read(limit + 1)
        if len(value) != info.st_size:
            raise IssuanceError("source changed during read")
        return value
    except OSError as error:
        raise IssuanceError("source cannot be read") from error


def _public(path: Path, expected_name: str) -> dict[str, str]:
    try:
        data = json.loads(_read(path, 8192))
        if (
            not isinstance(data, dict)
            or data.keys() != {"key_id", "public_key_b64", "public_sha256"}
            or data["key_id"] != expected_name
        ):
            raise IssuanceError("unapproved public key identity")
        encoded = data["public_key_b64"]
        raw = base64.b64decode(encoded, validate=True)
        if (
            len(raw) != 32
            or base64.b64encode(raw).decode() != encoded
            or _sha(raw) != data["public_sha256"]
        ):
            raise IssuanceError("invalid public key fingerprint")
        return cast(dict[str, str], data)
    except (ValueError, KeyError, TypeError) as error:
        if isinstance(error, IssuanceError):
            raise
        raise IssuanceError("malformed public key document") from error


def _wheel_metadata(path: Path) -> tuple[str, tuple[str, ...]]:
    if path.name != _WHEEL or _sha(_read(path, 64 * 1024 * 1024)) != _SHA256:
        raise IssuanceError("wheel differs from observed official Quillan release")
    prefix = "quillan-0.10.6.dist-info/"
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read(prefix + "METADATA")
            if len(raw) > 128 * 1024:
                raise IssuanceError("wheel metadata too large")
            message = BytesParser(policy=policy.default).parsebytes(raw)
            if (
                str(message.get("Name", "")).lower() != "quillan"
                or message.get("Version") != "0.10.6"
            ):
                raise IssuanceError("wheel metadata identity mismatch")
            python_header = message.get("Requires-Python")
            requirements = tuple(
                str(x).strip() for x in message.get_all("Requires-Dist", [])
            )
            if python_header is None or len(requirements) > 128:
                raise IssuanceError("invalid wheel requirements")
            return str(python_header), requirements
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        if isinstance(error, IssuanceError):
            raise
        raise IssuanceError("wheel cannot be inspected") from error


def _date(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IssuanceError("aware issuance clock required")
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def plan_documents(
    wheel: Path,
    root: dict[str, str],
    module: dict[str, str],
    integration: dict[str, str],
    *,
    now: datetime,
) -> dict[str, bytes]:
    """Review documents only; no signing, installed-state or trust authority."""
    ids = (root["key_id"], module["key_id"], integration["key_id"])
    if ids != ("publisher-root", "quillan-publisher", "suite-integration"):
        raise IssuanceError("unexpected signing roles")
    if len({k["public_key_b64"] for k in (root, module, integration)}) != 3:
        raise IssuanceError("same signing public key assigned to multiple roles")
    python, requirements = _wheel_metadata(wheel)
    window: dict[str, object] = {
        "schema_version": 1,
        "revision": 1,
        "issued_at": _date(now),
        "expires_at": _date(now + timedelta(days=30)),
    }
    keys = sorted((root, module, integration), key=lambda item: item["key_id"])
    policy_document = {
        "record_type": "pds_evergreen_pinned_keyring",
        "schema_version": 1,
        "revision": 1,
        "keys": [
            {"key_id": k["key_id"], "public_key_b64": k["public_key_b64"]} for k in keys
        ],
        "root_key_ids": ["publisher-root"],
        "root_threshold": 1,
    }
    registry = {
        "kind": "registry",
        **window,
        "modules": [
            {
                "component_id": "quillan",
                "distribution": "quillan",
                "repository": "Paper-Data-Suite/pds-quillan",
                "signing_key_ids": ["quillan-publisher"],
            }
        ],
        "integration_signing_key_ids": ["suite-integration"],
    }
    module_doc = {
        "kind": "module_release",
        **window,
        "component_id": "quillan",
        "repository": "Paper-Data-Suite/pds-quillan",
        "distribution": "quillan",
        "releases": [
            {
                "version": "0.10.6",
                "tag": "v0.10.6",
                "wheel": _WHEEL,
                "sha256": _SHA256,
                "requires_python": python,
                "requires_dist": list(requirements),
                "console_script": "quillan",
                "console_target": "quillan.cli:main",
                "revoked": False,
            }
        ],
    }
    public_policy = _encode(policy_document)
    return {
        "trust-policy.json": public_policy,
        "registry-payload.json": _encode(registry),
        "quillan-payload.json": _encode(module_doc),
        "review.json": _encode(
            {
                "schema": "pds-quillan-issuance-review-v1",
                "wheel_sha256": _SHA256,
                "trust_policy_sha256": _sha(public_policy),
                "status": "UNSIGNED_REVIEW_ONLY_NOT_TRUST_PROVISIONED",
            }
        ),
    }


def _new_file(path: Path, content: bytes) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        raise IssuanceError("refusing to overwrite or create output") from error


def _outside_git(path: Path) -> None:
    resolved = path.resolve(strict=False)
    for candidate in (path, resolved):
        for parent in candidate.parents:
            if (parent / ".git").exists():
                raise IssuanceError("private signing material inside repository")


def _review(
    directory: Path, policy_sha: str, wheel: Path
) -> tuple[bytes, bytes, bytes]:
    if not _HEX.fullmatch(policy_sha):
        raise IssuanceError("invalid independent trust-policy pin")
    policy_bytes = _read(directory / "trust-policy.json", 24 * 1024)
    if _sha(policy_bytes) != policy_sha:
        raise IssuanceError("trust policy does not match supplied pin")
    registry = _read(directory / "registry-payload.json", 192 * 1024)
    module = _read(directory / "quillan-payload.json", 192 * 1024)
    review = json.loads(_read(directory / "review.json", 4096))
    if not isinstance(review, dict) or review != {
        "schema": "pds-quillan-issuance-review-v1",
        "wheel_sha256": _SHA256,
        "trust_policy_sha256": policy_sha,
        "status": "UNSIGNED_REVIEW_ONLY_NOT_TRUST_PROVISIONED",
    }:
        raise IssuanceError("review is inconsistent")
    # Re-derive immutable release claims from the observed wheel; prevents
    # signing a silently modified release payload after its review.
    expected = plan_documents(
        wheel,
        *_public_from_policy(policy_bytes),
        now=_issued_time(registry),
    )
    if any(expected[n] != _read(directory / n, 192 * 1024) for n in _NAMES):
        raise IssuanceError("reviewed payloads or keyring differ from official wheel")
    return policy_bytes, registry, module


def _issued_time(registry: bytes) -> datetime:
    try:
        value = json.loads(registry)["issued_at"]
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (KeyError, ValueError, TypeError) as error:
        raise IssuanceError("invalid reviewed issuance time") from error


def _public_from_policy(raw: bytes) -> tuple[dict[str, str], ...]:
    data = json.loads(raw)
    result = []
    for key_id in ("publisher-root", "quillan-publisher", "suite-integration"):
        items = [k for k in data["keys"] if k["key_id"] == key_id]
        if len(items) != 1:
            raise IssuanceError("trust policy key identities changed")
        k = items[0]
        result.append(
            {
                "key_id": key_id,
                "public_key_b64": k["public_key_b64"],
                "public_sha256": _sha(base64.b64decode(k["public_key_b64"])),
            }
        )
    return tuple(result)


def issue_envelopes(
    directory: Path,
    wheel: Path,
    *,
    policy_sha: str,
    root_key: Path,
    module_key: Path,
    root_password: bytes,
    module_password: bytes,
    now: datetime,
) -> dict[str, bytes]:
    """Sign reviewed documents, then reverify signatures + exact wheel."""
    for key in (root_key, module_key):
        _outside_git(key)
    policy_raw, registry_payload, module_payload = _review(directory, policy_sha, wheel)
    pinned = load_digest_pinned_trust_policy(policy_raw, pinned_sha256=policy_sha)
    pub = _public_from_policy(policy_raw)
    root_pem = _read(root_key, 16 * 1024)
    module_pem = _read(module_key, 16 * 1024)
    for name, pem, password, expected in (
        ("publisher-root", root_pem, root_password, pub[0]),
        ("quillan-publisher", module_pem, module_password, pub[1]),
    ):
        if (
            public_key_from_encrypted(name, pem, password).public_key_b64
            != expected["public_key_b64"]
        ):
            raise IssuanceError("encrypted key differs from reviewed public identity")
    registry = sign_catalog_payload(
        registry_payload,
        key_id="publisher-root",
        encrypted_pem=root_pem,
        password=root_password,
    )
    module = sign_catalog_payload(
        module_payload,
        key_id="quillan-publisher",
        encrypted_pem=module_pem,
        password=module_password,
    )
    verified_registry = verify_registry_document(
        registry, trust=pinned.keyring, now=now
    )
    verified = verify_signed_release_wheel(
        wheel,
        registry_envelope=registry,
        module_envelope=module,
        trust=pinned.keyring,
        now=now,
        version="0.10.6",
    )
    if (verified.component_id, verified.sha256) != ("quillan", _SHA256):
        raise IssuanceError("signed identity differs from reviewed release")
    return {
        "registry-envelope.json": registry,
        "quillan-envelope.json": module,
        "issuance-result.json": _encode(
            {
                "result": "SIGNED_LOCAL_QUILLAN_RELEASE_BYTES_VERIFIED",
                "registry_sha256": _sha(registry),
                "module_sha256": _sha(module),
                "trust_policy_sha256": policy_sha,
                "signed_registry_payload_sha256": verified_registry.payload_sha256,
                "wheel_sha256": verified.sha256,
                "authority": (
                    "LOCAL_CEREMONY_ONLY_NO_PRODUCTION_LAUNCH_"
                    "OR_OFFICIAL_PUBLISHER_AUTHORITY"
                ),
            }
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    prepare = sub.add_parser("prepare", help="create new unsigned review directory")
    prepare.add_argument("--wheel", required=True, type=Path)
    prepare.add_argument("--root-public", required=True, type=Path)
    prepare.add_argument("--quillan-public", required=True, type=Path)
    prepare.add_argument("--integration-public", required=True, type=Path)
    prepare.add_argument("--directory", required=True, type=Path)
    issue = sub.add_parser("issue", help="sign reviewed release using private keys")
    issue.add_argument("--wheel", required=True, type=Path)
    issue.add_argument("--directory", required=True, type=Path)
    issue.add_argument("--trust-sha256", required=True)
    issue.add_argument("--root-private", required=True, type=Path)
    issue.add_argument("--quillan-private", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == "prepare":
            documents = plan_documents(
                args.wheel,
                _public(args.root_public, "publisher-root"),
                _public(args.quillan_public, "quillan-publisher"),
                _public(args.integration_public, "suite-integration"),
                now=datetime.now(timezone.utc).replace(microsecond=0),
            )
            dest: Path = args.directory.resolve(strict=False)
            if dest.exists() or dest.is_symlink() or not dest.parent.is_dir():
                raise IssuanceError("review directory must be new with existing parent")
            dest.mkdir(mode=0o700)
            for name, data in documents.items():
                _new_file(dest / name, data)
            print(
                "REVIEW_CREATED_NO_SIGNATURES\nTrust-policy SHA-256: "
                + _sha(documents["trust-policy.json"])
            )
        else:
            target = args.directory.resolve(strict=True)
            if any(
                (target / name).exists()
                for name in (
                    "registry-envelope.json",
                    "quillan-envelope.json",
                    "issuance-result.json",
                )
            ):
                raise IssuanceError("signed output already exists")
            issued = issue_envelopes(
                target,
                args.wheel,
                policy_sha=args.trust_sha256,
                root_key=args.root_private,
                module_key=args.quillan_private,
                root_password=getpass.getpass("Root-key passphrase: ").encode(),
                module_password=getpass.getpass("Quillan-key passphrase: ").encode(),
                now=datetime.now(timezone.utc),
            )
            for name, data in issued.items():
                _new_file(target / name, data)
            print("SIGNED_LOCAL_QUILLAN_RELEASE_BYTES_VERIFIED_NOT_PRODUCTION_LAUNCH")
        return 0
    except (
        IssuanceError,
        OfflinePublisherError,
        CatalogVerificationError,
        ReleaseArtifactError,
        TrustProvisioningError,
        OSError,
        ValueError,
    ) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
