from __future__ import annotations

from pathlib import Path

import pytest

from paper_data_suite.cli import main


def test_backup_group_without_subcommand_shows_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("backup",)) == 0
    output = capsys.readouterr().out
    normalized = " ".join(output.split())
    assert "usage: pds backup" in normalized
    assert "{create}" in normalized
    assert "currently resolved Core workspace" in normalized


def test_backup_create_help_documents_explicit_sensitive_copy_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("backup", "create", "--help"))

    assert raised.value.code == 0
    output = capsys.readouterr().out
    normalized = " ".join(output.split())
    assert "usage: pds backup create" in normalized
    assert "--destination" in normalized
    assert "--yes" in normalized
    assert "currently resolved Core workspace" in normalized
    assert "potentially sensitive data" in normalized
    assert "does not encrypt, upload, or cloud-sync" in normalized


def test_backup_create_dispatches_destination_and_yes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    calls: list[tuple[Path, bool]] = []

    def run_backup(destination: Path, *, assume_yes: bool = False) -> int:
        calls.append((destination, assume_yes))
        return 7

    monkeypatch.setattr(cli, "run_workspace_backup_create", run_backup)

    assert (
        main(
            (
                "backup",
                "create",
                "--destination",
                "C:/PDS Backups",
                "--yes",
            )
        )
        == 7
    )
    assert calls == [(Path("C:/PDS Backups"), True)]


def test_backup_create_dispatches_interactive_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    calls: list[tuple[Path, bool]] = []

    def run_backup(destination: Path, *, assume_yes: bool = False) -> int:
        calls.append((destination, assume_yes))
        return 0

    monkeypatch.setattr(cli, "run_workspace_backup_create", run_backup)

    assert main(("backup", "create", "--destination", "backups")) == 0
    assert calls == [(Path("backups"), False)]
