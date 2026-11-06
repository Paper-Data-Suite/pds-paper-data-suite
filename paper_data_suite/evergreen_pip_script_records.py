"""Read-only parser for pip RECORD entries naming owned console launchers.

Only the caller's exact stage-relative Scripts/bin paths may cross outside
site-packages. All script hashes use the same strict parser as wheel-owned
site files. A caller must authenticate the actual wrapper bytes separately.
"""

from __future__ import annotations

import csv
import io
from typing import Final

from paper_data_suite.evergreen_staged_install import (
    StageAuditError,
    _record_entries,
)

_MAX_RECORD: Final = 2 * 1024 * 1024
_MAX_ROWS: Final = 30000


class PipScriptRecordError(ValueError):
    """The installed pip RECORD contains an unsafe or mismatched script row."""


def _rows_bytes(rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    return stream.getvalue().encode("utf-8")


def split_pip_record(
    raw: bytes, *, allowed_scripts: frozenset[str]
) -> tuple[dict[str, tuple[str, int]], dict[str, tuple[str, int]]]:
    """Partition strict installed RECORD rows into site and exact script paths.

    Allowed script names are supplied by the independently inspected wheel
    console entry points, never inferred from the installed RECORD. Other
    parent traversal always fails via the ordinary site RECORD parser.
    """
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= _MAX_RECORD
        or not isinstance(allowed_scripts, frozenset)
        or len(allowed_scripts) > 64
        or any(type(name) is not str for name in allowed_scripts)
    ):
        raise PipScriptRecordError("invalid installed pip RECORD inputs")
    try:
        original = list(
            csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
        )
        if not 1 <= len(original) <= _MAX_ROWS:
            raise PipScriptRecordError("installed pip RECORD row count invalid")
        site_rows: list[list[str]] = []
        script_rows: dict[str, tuple[str, int]] = {}
        seen: set[str] = set()
        for row in original:
            if len(row) != 3:
                raise PipScriptRecordError("malformed installed pip RECORD row")
            name = row[0]
            if name in seen:
                raise PipScriptRecordError("duplicate installed pip RECORD path")
            seen.add(name)
            if name not in allowed_scripts:
                site_rows.append(row)
                continue
            # Sanitize ONLY the known-good key for reuse of the strict sha256
            # and decimal-size parser. Never normalize or resolve a path from
            # the RECORD itself.
            shadow = _rows_bytes([["pds_verified_launcher", row[1], row[2]]])
            value = _record_entries(shadow)["pds_verified_launcher"]
            if value[1] < 1:
                raise PipScriptRecordError("unhashed installed console launcher")
            script_rows[name] = value
        site_entries = _record_entries(_rows_bytes(site_rows))
        return site_entries, script_rows
    except PipScriptRecordError:
        raise
    except (StageAuditError, UnicodeDecodeError, csv.Error, ValueError) as error:
        raise PipScriptRecordError(
            "unsafe or malformed installed pip RECORD"
        ) from error


__all__ = ("PipScriptRecordError", "split_pip_record")
