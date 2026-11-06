"""Issue #49 Slice 37: explicit, read-only external-witness smoke acceptance.

One operator-initiated HTTPS head-read only. A matching signed head does not
establish that the witness is administered independently, that signing keys are
protected, that active software bytes match, or that activation is authorized.
Neither imported code nor normal Suite launch ever initiates a network request.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_checkpoint_witness import (
    CheckpointWitnessError,
    query_checkpoint_witness,
)
from paper_data_suite.evergreen_witness_https import (
    ProvisionedHttpsWitnessTransport,
    WitnessHttpsError,
)

_MAX_RECEIPT: Final = 16 * 1024
_MAX_KEY: Final = 32


class WitnessAcceptanceError(ValueError):
    """Operator smoke verification is unavailable or rejects its inputs."""


@dataclass(frozen=True, slots=True)
class WitnessAcceptanceObservation:
    """Protocol evidence only; never a deployment certificate or launch token."""

    witness_id: str
    installation_id: str
    generation: int
    witness_revision: int
    receipt_sha256: str
    signed_expires_at: datetime
    status: str = "SIGNED_HEAD_MATCHED_DEPLOYMENT_UNVERIFIED"


def _bounded_file(path: Path, maximum: int, label: str) -> bytes:
    """Read only a bounded regular file, rejecting ordinary symlinks/reparse."""
    if not isinstance(path, Path):
        raise WitnessAcceptanceError(f"invalid {label} path")
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & 0x400
            or not 1 <= before.st_size <= maximum
        ):
            raise WitnessAcceptanceError(f"unsafe or oversized {label}")
        with path.open("rb") as source:
            opened = source.fileno()
            during = os.fstat(opened)
            if (
                not stat.S_ISREG(during.st_mode)
                or during.st_dev != before.st_dev
                or during.st_ino != before.st_ino
                or during.st_size != before.st_size
            ):
                raise WitnessAcceptanceError(f"changed {label} during opening")
            data = source.read(maximum + 1)
        after = path.lstat()
        if (
            len(data) != before.st_size
            or after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            raise WitnessAcceptanceError(f"changed {label} while reading")
        return data
    except OSError as error:
        raise WitnessAcceptanceError(f"unable to read {label}") from error


def probe_witness_head(
    *,
    transport: ProvisionedHttpsWitnessTransport,
    installation_id: str,
    receipt_file: Path,
    public_key_file: Path,
    pinned_public_key_sha256: str,
    witness_id: str,
    now: datetime,
    minimum_witness_revision: int | None = None,
) -> WitnessAcceptanceObservation:
    """Explicit remote query with independently provided pin assertions.

    The operator MUST obtain both trust pins and deployment approval out of
    band. A caller could supply fraudulent pins, so this never certifies
    independent operation or permits production activation/rollback/launch.
    """
    if not isinstance(transport, ProvisionedHttpsWitnessTransport):
        raise WitnessAcceptanceError("missing explicit HTTPS witness transport")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise WitnessAcceptanceError("invalid verifier clock")
    if (
        type(pinned_public_key_sha256) is not str
        or len(pinned_public_key_sha256) != 64
        or any(char not in "0123456789abcdef" for char in pinned_public_key_sha256)
    ):
        raise WitnessAcceptanceError("invalid independently supplied witness-key pin")
    if minimum_witness_revision is not None and (
        type(minimum_witness_revision) is not int
        or minimum_witness_revision < 1
        or minimum_witness_revision > 2**53 - 1
    ):
        raise WitnessAcceptanceError("invalid minimum witness revision")
    public_key = _bounded_file(public_key_file, _MAX_KEY, "witness public key")
    if len(public_key) != 32 or not hmac.compare_digest(
        hashlib.sha256(public_key).hexdigest(), pinned_public_key_sha256
    ):
        raise WitnessAcceptanceError("witness public key does not match external pin")
    receipt = _bounded_file(receipt_file, _MAX_RECEIPT, "active receipt")
    try:
        observation = query_checkpoint_witness(
            transport,
            installation_id=installation_id,
            receipt_bytes=receipt,
            pinned_public_key=public_key,
            expected_witness_id=witness_id,
            now=now,
            minimum_witness_revision=minimum_witness_revision,
        )
    except (CheckpointWitnessError, WitnessHttpsError) as error:
        raise WitnessAcceptanceError(
            "signed witness head verification failed"
        ) from error
    return WitnessAcceptanceObservation(
        witness_id=observation.witness_id,
        installation_id=observation.installation_id,
        generation=observation.receipt.receipt.generation,
        witness_revision=observation.witness_revision,
        receipt_sha256=observation.receipt.digest,
        signed_expires_at=observation.signed_expires_at,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m paper_data_suite.evergreen_witness_acceptance",
        description=(
            "Operator-only witness head smoke check; NOT activation qualification."
        ),
    )
    for name, help_text in (
        ("--origin", "HTTPS DNS origin of separately operated witness"),
        ("--ca-sha256", "independently obtained exact CA file SHA-256"),
        ("--witness-key-sha256", "independently obtained raw Ed25519 key SHA-256"),
        ("--witness-id", "expected independent witness ID"),
        ("--installation-id", "expected installation identity (32 lowercase hex)"),
    ):
        parser.add_argument(name, required=True, help=help_text)
    for name in (
        "--ca-file",
        "--client-cert",
        "--client-key",
        "--witness-key",
        "--receipt",
    ):
        parser.add_argument(name, type=Path, required=True)
    parser.add_argument("--minimum-revision", type=int)
    return parser


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        transport = ProvisionedHttpsWitnessTransport(
            origin=arguments.origin,
            ca_certificate=arguments.ca_file,
            pinned_ca_sha256=arguments.ca_sha256,
            client_certificate=arguments.client_cert,
            client_key=arguments.client_key,
        )
        observation = probe_witness_head(
            transport=transport,
            installation_id=arguments.installation_id,
            receipt_file=arguments.receipt,
            public_key_file=arguments.witness_key,
            pinned_public_key_sha256=arguments.witness_key_sha256,
            witness_id=arguments.witness_id,
            now=(
                datetime.now(timezone.utc).replace(microsecond=0)
                if now is None
                else now
            ),
            minimum_witness_revision=arguments.minimum_revision,
        )
    except (WitnessAcceptanceError, WitnessHttpsError) as error:
        # No key material, raw HTTP body, or private filesystem paths in errors.
        print(f"Witness head check: REFUSED ({error})", file=sys.stderr)
        return 1
    print(f"Witness head check: {observation.status}")
    print(f"Witness ID: {observation.witness_id}")
    print(f"Installation ID: {observation.installation_id}")
    print(f"Receipt generation: {observation.generation}")
    print(f"Witness revision: {observation.witness_revision}")
    print(f"Receipt SHA-256: {observation.receipt_sha256}")
    print("Deployment independence: NOT VERIFIED")
    print("Installation integrity / production activation: NOT AUTHORIZED")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = (
    "WitnessAcceptanceError",
    "WitnessAcceptanceObservation",
    "probe_witness_head",
    "build_parser",
    "main",
)
