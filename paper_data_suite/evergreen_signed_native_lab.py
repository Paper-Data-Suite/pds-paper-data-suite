"""Issue #49 Slice 103: root-signed lab-only Windows executable byte custody.

A signature authenticates *reviewed bytes* against a supplied independently
pinned development root; it does not attest vendor provenance, OS ownership,
process isolation, a protected install record, or production launch authority.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, TypedDict, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from paper_data_suite.evergreen_offline_publisher import (
    OfflinePublisherError,
    public_key_from_encrypted,
)
from paper_data_suite.evergreen_release_artifacts import (
    ReleaseArtifactError,
    verify_signed_release_wheel,
)
from paper_data_suite.evergreen_trust_provisioning import (
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)

_CONTEXT: Final = b"pds-issue49-signed-disposable-native-v1\x00"
_LAB_NAME: Final = "historical_suite_010_quillan_0106_FULL_DEPS_LAB"
_WHEEL_SHA: Final = "7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb"
_HASH: Final = re.compile(r"[0-9a-f]{64}\Z")
_UTC: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_MAX_BINARY: Final = 64 * 1024 * 1024
_MAX_JSON: Final = 32 * 1024
_BINARIES: Final = ("Scripts/python.exe", "Scripts/quillan.exe")


class _BaseEvidenceArgs(TypedDict):
    wheel: Path
    policy: Path
    independent_policy_sha256: str
    registry: Path
    module: Path
    now: datetime


class NativeLabEvidenceError(ValueError):
    """A reviewed, signed Windows native-binary claim cannot be accepted."""


@dataclass(frozen=True, slots=True)
class NativeLabObservation:
    policy_sha256: str
    wheel_sha256: str
    python_sha256: str
    launcher_sha256: str
    native_binary_digest_attested: bool = True
    production_launch_authority: bool = False
    status: str = "LOCAL_ROOT_SIGNED_NATIVE_BYTES_MATCH_LAB_ONLY"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    found: dict[str, object] = {}
    for key, value in pairs:
        if key in found:
            raise NativeLabEvidenceError("duplicate JSON field")
        found[key] = value
    return found


def _json(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_JSON:
        raise NativeLabEvidenceError("native evidence JSON outside bounds")
    try:
        result: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except NativeLabEvidenceError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise NativeLabEvidenceError("malformed native evidence JSON") from error
    if not isinstance(result, dict):
        raise NativeLabEvidenceError("native evidence must be an object")
    return cast(dict[str, object], result)


def _encode(document: object) -> bytes:
    data = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(data) > _MAX_JSON:
        raise NativeLabEvidenceError("native evidence too large")
    return data


def _read(path: Path, maximum: int = _MAX_JSON) -> bytes:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, "st_file_attributes", 0) & 0x400)
            or not 1 <= info.st_size <= maximum
        ):
            raise NativeLabEvidenceError("unsafe or oversized input file")
        with path.open("rb") as handle:
            raw = handle.read(maximum + 1)
        if len(raw) != info.st_size:
            raise NativeLabEvidenceError("input file changed while reading")
        return raw
    except OSError as error:
        raise NativeLabEvidenceError("required input file cannot be read") from error


def _hash_file(path: Path) -> tuple[str, int]:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, "st_file_attributes", 0) & 0x400)
            or not 1 <= info.st_size <= _MAX_BINARY
        ):
            raise NativeLabEvidenceError("unsafe Windows launcher executable")
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                total += len(block)
                if total > _MAX_BINARY:
                    raise NativeLabEvidenceError("native executable too large")
                digest.update(block)
        if total != info.st_size:
            raise NativeLabEvidenceError("native executable changed while hashing")
        return digest.hexdigest(), total
    except OSError as error:
        raise NativeLabEvidenceError("could not inspect native executable") from error


def _lab_files(lab: Path) -> list[dict[str, object]]:
    if not isinstance(lab, Path) or lab.name != _LAB_NAME:
        raise NativeLabEvidenceError("only exact disposable Quillan lab is permitted")
    for folder in (lab, lab / "Scripts"):
        try:
            info = folder.lstat()
        except OSError as error:
            raise NativeLabEvidenceError("missing lab folder") from error
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, "st_file_attributes", 0) & 0x400)
        ):
            raise NativeLabEvidenceError("lab folder is a link or reparse point")
    output: list[dict[str, object]] = []
    for name in _BINARIES:
        digest, size = _hash_file(lab / Path(name))
        output.append({"relative_path": name, "sha256": digest, "size": size})
    return output


def _time(value: str) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise NativeLabEvidenceError("invalid native-evidence UTC clock")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise NativeLabEvidenceError("invalid native-evidence timestamp") from error


def _checked_basis(
    *, wheel: Path, policy: Path, pin: str, registry: Path, module: Path, now: datetime
) -> tuple[bytes, bytes, bytes]:
    if type(pin) is not str or not _HASH.fullmatch(pin):
        raise NativeLabEvidenceError("independently pinned trust hash required")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise NativeLabEvidenceError("timezone-aware clock required")
    policy_bytes = _read(policy)
    registry_bytes = _read(registry, 256 * 1024)
    module_bytes = _read(module, 256 * 1024)
    try:
        trusted = load_digest_pinned_trust_policy(policy_bytes, pinned_sha256=pin)
        verified = verify_signed_release_wheel(
            wheel,
            registry_envelope=registry_bytes,
            module_envelope=module_bytes,
            trust=trusted.keyring,
            now=now,
            version="0.10.6",
        )
    except (TrustProvisioningError, ReleaseArtifactError, ValueError) as error:
        raise NativeLabEvidenceError("signed release basis refused") from error
    if (
        verified.component_id != "quillan"
        or verified.sha256 != _WHEEL_SHA
        or verified.console_script != "quillan"
        or verified.console_target != "quillan.cli:main"
    ):
        raise NativeLabEvidenceError("signed native evidence release binding mismatch")
    return policy_bytes, registry_bytes, module_bytes


def _claim(
    lab: Path,
    *,
    pin: str,
    registry_bytes: bytes,
    module_bytes: bytes,
    issued: datetime,
) -> dict[str, object]:
    when = issued.astimezone(timezone.utc).replace(microsecond=0)
    return {
        "record_type": "pds_issue49_disposable_native_lab",
        "schema_version": 1,
        "lab_name": _LAB_NAME,
        "trust_policy_sha256": pin,
        "wheel_sha256": _WHEEL_SHA,
        "registry_envelope_sha256": _digest(registry_bytes),
        "module_envelope_sha256": _digest(module_bytes),
        "issued_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (when + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "binaries": _lab_files(lab),
    }


def prepare_native_lab_review(
    lab: Path,
    *,
    wheel: Path,
    policy: Path,
    independent_policy_sha256: str,
    registry: Path,
    module: Path,
    now: datetime,
) -> bytes:
    """Reviewable exact digests only; NOT signed or safe to execute."""
    _, registry_bytes, module_bytes = _checked_basis(
        wheel=wheel,
        policy=policy,
        pin=independent_policy_sha256,
        registry=registry,
        module=module,
        now=now,
    )
    return _encode(
        _claim(
            lab,
            pin=independent_policy_sha256,
            registry_bytes=registry_bytes,
            module_bytes=module_bytes,
            issued=now,
        )
    )


def _claimed_review(
    reviewed: bytes,
    lab: Path,
    *,
    pin: str,
    registry_bytes: bytes,
    module_bytes: bytes,
    now: datetime,
) -> dict[str, object]:
    data = _json(reviewed)
    if data.keys() != {
        "record_type",
        "schema_version",
        "lab_name",
        "trust_policy_sha256",
        "wheel_sha256",
        "registry_envelope_sha256",
        "module_envelope_sha256",
        "issued_at",
        "expires_at",
        "binaries",
    }:
        raise NativeLabEvidenceError("unexpected native review fields")
    if (
        data["record_type"] != "pds_issue49_disposable_native_lab"
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise NativeLabEvidenceError("wrong native-evidence schema")
    issued = _time(cast(str, data["issued_at"]))
    expiry = _time(cast(str, data["expires_at"]))
    if not issued <= now.astimezone(timezone.utc) < expiry:
        raise NativeLabEvidenceError("native evidence expired or not yet valid")
    expected = _claim(
        lab,
        pin=pin,
        registry_bytes=registry_bytes,
        module_bytes=module_bytes,
        issued=issued,
    )
    if data != expected or reviewed != _encode(expected):
        raise NativeLabEvidenceError("native bytes or reviewed binding changed")
    return data


def _unb64(value: object, *, size: int) -> bytes:
    if not isinstance(value, str) or len(value) > 4 * ((size + 2) // 3):
        raise NativeLabEvidenceError("invalid signed native base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise NativeLabEvidenceError("invalid native signature encoding") from error
    if len(decoded) != size or base64.b64encode(decoded).decode() != value:
        raise NativeLabEvidenceError("noncanonical native signature")
    return decoded


def _envelope(payload: bytes, signature: bytes) -> bytes:
    return _encode(
        {
            "envelope_version": 1,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "signature": {
                "key_id": "publisher-root",
                "algorithm": "ed25519",
                "signature_b64": base64.b64encode(signature).decode("ascii"),
            },
        }
    )


def issue_native_lab_envelope(
    lab: Path,
    *,
    reviewed: bytes,
    root_private: bytes,
    root_password: bytes,
    wheel: Path,
    policy: Path,
    independent_policy_sha256: str,
    registry: Path,
    module: Path,
    now: datetime,
) -> bytes:
    """Root-sign unchanged reviewed bytes; a local, non-production trust ceremony."""
    policy_bytes, registry_bytes, module_bytes = _checked_basis(
        wheel=wheel,
        policy=policy,
        pin=independent_policy_sha256,
        registry=registry,
        module=module,
        now=now,
    )
    _claimed_review(
        reviewed,
        lab,
        pin=independent_policy_sha256,
        registry_bytes=registry_bytes,
        module_bytes=module_bytes,
        now=now,
    )
    trusted = load_digest_pinned_trust_policy(
        policy_bytes, pinned_sha256=independent_policy_sha256
    )
    if (
        trusted.keyring.root_key_ids != ("publisher-root",)
        or trusted.keyring.root_threshold != 1
    ):
        raise NativeLabEvidenceError("unsupported local native root quorum")
    public = public_key_from_encrypted("publisher-root", root_private, root_password)
    key = trusted.keyring.key("publisher-root")
    if key is None or base64.b64decode(public.public_key_b64) != key.public_bytes:
        raise NativeLabEvidenceError("encrypted signer does not match pinned root")
    try:
        loaded = serialization.load_pem_private_key(
            root_private, password=root_password
        )
    except (TypeError, ValueError) as error:
        raise NativeLabEvidenceError("signer could not be unlocked") from error
    if not isinstance(loaded, Ed25519PrivateKey):
        raise NativeLabEvidenceError("signer is not an Ed25519 key")
    result = _envelope(reviewed, loaded.sign(_CONTEXT + reviewed))
    inspect_native_lab_envelope(
        lab,
        envelope=result,
        wheel=wheel,
        policy=policy,
        independent_policy_sha256=independent_policy_sha256,
        registry=registry,
        module=module,
        now=now,
    )
    return result


def inspect_native_lab_envelope(
    lab: Path,
    *,
    envelope: bytes,
    wheel: Path,
    policy: Path,
    independent_policy_sha256: str,
    registry: Path,
    module: Path,
    now: datetime,
) -> NativeLabObservation:
    """Reauthenticate the signed exact native digests; NEVER launch anything."""
    policy_bytes, registry_bytes, module_bytes = _checked_basis(
        wheel=wheel,
        policy=policy,
        pin=independent_policy_sha256,
        registry=registry,
        module=module,
        now=now,
    )
    signed = _json(envelope)
    if signed.keys() != {"envelope_version", "payload_b64", "signature"}:
        raise NativeLabEvidenceError("unexpected native signature fields")
    if type(signed["envelope_version"]) is not int or signed["envelope_version"] != 1:
        raise NativeLabEvidenceError("unsupported native signature envelope")
    payload_b64 = signed["payload_b64"]
    if not isinstance(payload_b64, str) or len(payload_b64) > 4 * (
        (_MAX_JSON + 2) // 3
    ):
        raise NativeLabEvidenceError("invalid native evidence payload encoding")
    try:
        payload = base64.b64decode(payload_b64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise NativeLabEvidenceError("invalid native evidence payload") from error
    if (
        not payload
        or len(payload) > _MAX_JSON
        or base64.b64encode(payload).decode() != payload_b64
    ):
        raise NativeLabEvidenceError("noncanonical native evidence payload")
    _claimed_review(
        payload,
        lab,
        pin=independent_policy_sha256,
        registry_bytes=registry_bytes,
        module_bytes=module_bytes,
        now=now,
    )
    signature = signed["signature"]
    if (
        not isinstance(signature, dict)
        or signature.keys() != {"key_id", "algorithm", "signature_b64"}
        or signature["key_id"] != "publisher-root"
        or signature["algorithm"] != "ed25519"
    ):
        raise NativeLabEvidenceError("unauthorized native signing identity")
    trusted = load_digest_pinned_trust_policy(
        policy_bytes, pinned_sha256=independent_policy_sha256
    )
    if (
        trusted.keyring.root_key_ids != ("publisher-root",)
        or trusted.keyring.root_threshold != 1
    ):
        raise NativeLabEvidenceError("unsupported native root quorum")
    key = trusted.keyring.key("publisher-root")
    if key is None:
        raise NativeLabEvidenceError("missing native signing key")
    try:
        Ed25519PublicKey.from_public_bytes(key.public_bytes).verify(
            _unb64(signature["signature_b64"], size=64), _CONTEXT + payload
        )
    except (InvalidSignature, ValueError) as error:
        raise NativeLabEvidenceError("native signature invalid") from error
    actual = _lab_files(lab)
    return NativeLabObservation(
        policy_sha256=independent_policy_sha256,
        wheel_sha256=_WHEEL_SHA,
        python_sha256=cast(str, actual[0]["sha256"]),
        launcher_sha256=cast(str, actual[1]["sha256"]),
    )


def _new_file(path: Path, data: bytes) -> None:
    if not path.parent.is_dir() or path.is_symlink():
        raise NativeLabEvidenceError("native evidence parent missing or unsafe")
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise NativeLabEvidenceError("refusing overwrite of native evidence") from error
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def _no_git_key(path: Path) -> None:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise NativeLabEvidenceError("private signing key may not be in Git")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "issue", "verify"))
    parser.add_argument("--lab-venv", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--trust-policy", type=Path, required=True)
    parser.add_argument("--trust-sha256", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--root-private", type=Path)
    parser.add_argument("--native-envelope", type=Path)
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("native executable lab requires Windows")
    now = datetime.now(timezone.utc)
    base: _BaseEvidenceArgs = {
        "wheel": args.wheel,
        "policy": args.trust_policy,
        "independent_policy_sha256": args.trust_sha256,
        "registry": args.registry,
        "module": args.module,
        "now": now,
    }
    try:
        if args.operation == "prepare":
            if args.review_file is None or args.root_private or args.native_envelope:
                raise NativeLabEvidenceError("prepare requires only --review-file")
            document = prepare_native_lab_review(args.lab_venv, **base)
            _new_file(args.review_file, document)
            print("NATIVE_LAB_REVIEW_CREATED_UNSIGNED_NO_LAUNCH_AUTHORITY")
        elif args.operation == "issue":
            if (
                args.review_file is None
                or args.root_private is None
                or args.native_envelope is None
            ):
                raise NativeLabEvidenceError(
                    "issue requires review, private key and envelope output"
                )
            _no_git_key(args.root_private)
            reviewed = _read(args.review_file)
            pem = _read(args.root_private, 16 * 1024)
            signed = issue_native_lab_envelope(
                args.lab_venv,
                reviewed=reviewed,
                root_private=pem,
                root_password=getpass.getpass("Root-key passphrase: ").encode("utf-8"),
                **base,
            )
            _new_file(args.native_envelope, signed)
            print("NATIVE_LAB_ROOT_SIGNATURE_VERIFIED_NO_PRODUCTION_LAUNCH")
        else:
            if args.native_envelope is None:
                raise NativeLabEvidenceError("verify requires --native-envelope")
            observation = inspect_native_lab_envelope(
                args.lab_venv, envelope=_read(args.native_envelope), **base
            )
            print(json.dumps(asdict(observation), sort_keys=True, indent=2))
            print("NATIVE_LAB_SIGNED_BYTES_VERIFIED_NO_PRODUCTION_LAUNCH")
        return 0
    except (
        NativeLabEvidenceError,
        OfflinePublisherError,
        TrustProvisioningError,
        ReleaseArtifactError,
        OSError,
        ValueError,
    ) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
