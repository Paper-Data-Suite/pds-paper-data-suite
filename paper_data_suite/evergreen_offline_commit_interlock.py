"""Issue #49 Slice 49: fail-closed marker interlock for legacy inert rollback.

This local check blocks cooperating offline-recovery paths once any successor
proposal could have been submitted to an independently operated witness.
It is NOT evidence that a CAS was or was not sent, nor a rollback credential.
Same-user filesystem deletion and uncoordinated writers defeat this check.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")


class OfflineCommitInterlockError(ValueError):
    """Potentially committed witness successor requires protected reconciliation."""


def refuse_if_local_successor_proposal_exists(
    software_root: Path, transaction_id: str
) -> None:
    """Reject *any* proposal-path entry without opening/following its content.

    Called after a cooperating selection lock is held; the proposal writer
    acquires the same lock before creating the record. A corrupt/symlinked or
    otherwise unsafe proposal is as blocking as a canonical proposal. Absence
    does NOT prove that no external witness CAS occurred: independent service
    evidence is still needed for a protected activation/recovery decision.
    """
    if (
        not isinstance(software_root, Path)
        or type(transaction_id) is not str
        or _TX.fullmatch(transaction_id) is None
    ):
        raise OfflineCommitInterlockError("invalid recovery transaction identity")
    proposal = (
        software_root / "transactions" / f"{transaction_id}.successor-proposal.json"
    )
    try:
        proposal.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise OfflineCommitInterlockError(
            "cannot inspect pending successor proposal path"
        ) from error
    raise OfflineCommitInterlockError(
        "successor proposal exists; offline rollback needs protected reconciliation"
    )


__all__ = (
    "OfflineCommitInterlockError",
    "refuse_if_local_successor_proposal_exists",
)
