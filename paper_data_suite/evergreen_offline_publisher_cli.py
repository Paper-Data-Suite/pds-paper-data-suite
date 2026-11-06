"""Explicit local key ceremony and offline catalog signing for Issue #49.

No production trust policy or launch authority is provisioned by this tool.
The private-key destination must be outside any Git repository.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
from pathlib import Path

from paper_data_suite.evergreen_offline_publisher import (
    OfflinePublisherError,
    generate_encrypted_keypair,
    sign_catalog_payload,
)

_MAX_KEY_FILE = 16 * 1024
_MAX_CLAIM_FILE = 192 * 1024


def _inside_git(path: Path) -> bool:
    for parent in (path.parent, *path.parents):
        if (parent / ".git").exists():
            return True
    return False


def _target(path: Path, *, secret: bool) -> Path:
    value = path.expanduser().resolve(strict=False)
    if not value.parent.is_dir() or value.exists() or value.is_symlink():
        raise OfflinePublisherError(
            "output must be a new file in an existing directory"
        )
    if secret and _inside_git(value):
        raise OfflinePublisherError(
            "private signing key cannot be created in a Git repository"
        )
    return value


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise OfflinePublisherError("input must be a regular non-symlink file")
    info = path.stat()
    if info.st_size < 1 or info.st_size > limit or not stat.S_ISREG(info.st_mode):
        raise OfflinePublisherError("input file size outside permitted bounds")
    raw = path.read_bytes()
    if len(raw) != info.st_size:
        raise OfflinePublisherError("input file changed while reading")
    return raw


def _password(*, confirm: bool) -> bytes:
    first = getpass.getpass("Offline signing key passphrase: ").encode("utf-8")
    if confirm and first != getpass.getpass("Repeat passphrase: ").encode("utf-8"):
        raise OfflinePublisherError("passphrase confirmation mismatch")
    return first


def _write_new(path: Path, data: bytes) -> None:
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise OfflinePublisherError(
            "output could not be created without overwrite"
        ) from error
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    keygen = sub.add_parser(
        "keygen", help="create encrypted private key and public identity"
    )
    keygen.add_argument("--key-id", required=True)
    keygen.add_argument("--private-file", type=Path, required=True)
    keygen.add_argument("--public-file", type=Path, required=True)
    sign = sub.add_parser("sign", help="sign reviewed catalog bytes with encrypted key")
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--private-file", type=Path, required=True)
    sign.add_argument("--payload-file", type=Path, required=True)
    sign.add_argument("--envelope-file", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        if options.action == "keygen":
            private_path = _target(options.private_file, secret=True)
            public_path = _target(options.public_file, secret=False)
            if private_path == public_path:
                raise OfflinePublisherError("key outputs must be distinct")
            pem, identity = generate_encrypted_keypair(
                options.key_id, _password(confirm=True)
            )
            public = (
                json.dumps(
                    {
                        "key_id": identity.key_id,
                        "public_key_b64": identity.public_key_b64,
                        "public_sha256": identity.public_sha256,
                    },
                    sort_keys=True,
                    indent=2,
                ).encode("ascii")
                + b"\n"
            )
            # The key is encrypted; separate OS ACL/hardware custody remains required.
            _write_new(private_path, pem)
            _write_new(public_path, public)
            print("ENCRYPTED_PUBLISHER_KEY_CREATED_NO_PRODUCTION_TRUST")
        else:
            private_path = options.private_file.expanduser().resolve(strict=False)
            if _inside_git(private_path):
                raise OfflinePublisherError(
                    "private signing key path is inside a Git repository"
                )
            target = _target(options.envelope_file, secret=False)
            claim = _read(options.payload_file, _MAX_CLAIM_FILE)
            pem = _read(private_path, _MAX_KEY_FILE)
            signed = sign_catalog_payload(
                claim,
                key_id=options.key_id,
                encrypted_pem=pem,
                password=_password(confirm=False),
            )
            _write_new(target, signed)
            print("OFFLINE_CATALOG_ENVELOPE_ISSUED_NOT_PRODUCTION_AUTHORIZATION")
        return 0
    except (OfflinePublisherError, OSError) as error:
        parser.exit(1, f"REFUSED: {error}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
