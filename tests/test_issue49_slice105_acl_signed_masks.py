"""Slice 105: signed Windows ACL masks must not bypass write checks."""

from __future__ import annotations

import pytest

from paper_data_suite.evergreen_windows_custody import (
    CustodyAuditError,
    inspect_acl_document,
)

_SYSTEM = "S-1-5-18"
_ADMINS = "S-1-5-32-544"
_USERS = "S-1-5-32-545"
_APP = "S-1-15-2-1"


def _document(
    sid: str, rights: object, *, inherit_only: bool = False
) -> dict[str, object]:
    return {
        "owner": _ADMINS,
        "rules": [
            {
                "sid": _SYSTEM,
                "type": "Allow",
                "rights": 2032127,
                "inherited": False,
                "inherit_only": False,
            },
            {
                "sid": sid,
                "type": "Allow",
                "rights": rights,
                "inherited": True,
                "inherit_only": inherit_only,
            },
        ],
    }


@pytest.mark.parametrize(
    "rights",
    [
        -2147483648,  # 0x80000000: generic read
        -1610612736,  # 0xA0000000: generic read + execute
        0x20000000,  # generic execute
        0x80000000,  # unsigned generic read
        0xA0000000,  # unsigned generic read + execute
        131241,  # concrete read and execute
    ],
)
def test_valid_signed_or_unsigned_read_and_execute_aces(rights: int) -> None:
    inspect_acl_document(_document(_APP, rights))


@pytest.mark.parametrize(
    "rights",
    [
        0x40000000,  # GENERIC_WRITE
        0x10000000,  # GENERIC_ALL
        0xC0000000,  # generic read + write (unsigned)
        -1073741824,  # same generic read + write (signed)
        0x90000000,  # generic read + all
        -1879048192,  # same generic read + all (signed)
        -1,  # 0xFFFFFFFF, all access bits set
        0xFFFFFFFF,
        2,  # FILE_WRITE_DATA / FILE_ADD_FILE
        0x40000,  # WRITE_DAC
        0x80000,  # WRITE_OWNER
    ],
)
def test_untrusted_write_is_rejected_in_both_representations(rights: int) -> None:
    with pytest.raises(CustodyAuditError, match="write authority"):
        inspect_acl_document(_document(_USERS, rights))


@pytest.mark.parametrize("rights", [-(2**31) - 1, 2**32, 2**64 - 1, True, "-1", 1.0])
def test_out_of_bounds_or_nonnumeric_mask_refused(rights: object) -> None:
    with pytest.raises(CustodyAuditError, match="invalid DACL"):
        inspect_acl_document(_document(_APP, rights))


def test_inherit_only_generic_full_access_is_not_effective_here() -> None:
    inspect_acl_document(_document("S-1-3-0", -1, inherit_only=True))


def test_existing_concrete_write_grants_remain_refused() -> None:
    with pytest.raises(CustodyAuditError, match="write authority"):
        inspect_acl_document(_document(_USERS, 2032127))
