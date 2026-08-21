from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from paper_data_suite.workspace_backup import (
    BACKUP_HASH_ALGORITHM,
    BACKUP_MANIFEST_RECORD_TYPE,
    BACKUP_MANIFEST_SCHEMA_VERSION,
    BACKUP_PAYLOAD_ROOT,
    BackupFileEntry,
    WorkspaceBackupManifest,
)
from paper_data_suite.workspace_backup_cli import (
    render_workspace_backup_verification_result,
    render_workspace_restore_plan,
    render_workspace_restore_result,
)
from paper_data_suite.workspace_backup_verification import (
    WorkspaceBackupVerificationResult,
)
from paper_data_suite.workspace_restore import (
    WorkspaceRestorePlan,
    WorkspaceRestoreResult,
)

FIXED = datetime(2026, 8, 20, 17, 48, 12, 123456, tzinfo=timezone.utc)
BACKUP_ID = "pds-workspace-backup-20260820T174812123456Z"


def _manifest() -> WorkspaceBackupManifest:
    name = "classes/student-private.csv"
    payload = b"synthetic-only"
    return WorkspaceBackupManifest(
        record_type=BACKUP_MANIFEST_RECORD_TYPE,
        schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
        backup_id=BACKUP_ID,
        created_at=FIXED,
        suite_version="0.1.0.dev0",
        core_version="0.6.0",
        payload_root=BACKUP_PAYLOAD_ROOT,
        hash_algorithm=BACKUP_HASH_ALGORITHM,
        directory_count=1,
        file_count=1,
        total_bytes=len(payload),
        directories=("classes",),
        files=(
            BackupFileEntry(
                path=name,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            ),
        ),
        exclusions=(),
    )


def test_verification_and_restore_normal_output_does_not_dump_payload_paths(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    backup = tmp_path / BACKUP_ID
    verification = WorkspaceBackupVerificationResult(
        backup_root=backup,
        manifest=manifest,
        manifest_sha256="a" * 64,
    )
    plan = WorkspaceRestorePlan(
        verification=verification,
        workspace_root=tmp_path / "active",
        workspace_source="saved_config",
        destination_root=tmp_path / "restored",
        destination_parent=tmp_path,
        destination_anchor=tmp_path,
        destination_free_bytes=10**9,
        required_free_bytes=64 * 1024 * 1024,
        destination_parent_exists=True,
    )
    result = WorkspaceRestoreResult(
        destination_root=plan.destination_root,
        manifest=manifest,
        manifest_sha256=verification.manifest_sha256,
    )

    output = (
        render_workspace_backup_verification_result(verification)
        + render_workspace_restore_plan(plan)
        + render_workspace_restore_result(plan, result)
    )

    assert "student-private.csv" not in output
    assert "synthetic-only" not in output
    assert manifest.files[0].sha256 not in output
    assert "Manifest SHA-256" in output


def test_importing_verification_and_restore_creates_no_workspace_state(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "must-not-be-created"
    user_home = tmp_path / "user"
    user_home.mkdir()
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PDS_WORKSPACE_ROOT"] = str(workspace)
    env["HOME"] = str(user_home)
    env["USERPROFILE"] = str(user_home)
    code = """
import sys
import paper_data_suite.workspace_backup_verification
import paper_data_suite.workspace_restore

for name in (
    "pds_concord",
    "quillan",
    "scoreform",
    "pds_vitrine",
    "pds_meridian",
    "pds_portia",
):
    if name in sys.modules:
        raise SystemExit("unexpected sibling module import: " + name)
""".strip()

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert not workspace.exists()


def test_ci_runs_installed_restore_smoke_on_supported_platforms() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Installed workspace restore acceptance" in workflow
    assert "matrix.python == '3.11'" in workflow
    assert "scripts/smoke_test_workspace_restore_wheel.py" in workflow
