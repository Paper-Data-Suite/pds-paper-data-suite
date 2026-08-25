from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_GITIGNORE = _ROOT / ".gitignore"

_EXPECTED_PDS_SAFETY_PATTERNS = {
    "pds-workspace-backup-*/",
    ".pds-workspace-backup-*.incomplete-*/",
    ".*.pds-restore.incomplete-*/",
    "local_outputs/",
    "scans_inbox/",
    "classes/",
    "*.log",
}


def test_gitignore_covers_known_sensitive_runtime_residue() -> None:
    lines = {
        line.strip()
        for line in _GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert _EXPECTED_PDS_SAFETY_PATTERNS <= lines
