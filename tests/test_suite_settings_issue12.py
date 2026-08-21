from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from paper_data_suite.application_launching import (
    ApplicationLaunchExecutionError,
    ApplicationLaunchResult,
)
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
    ApplicationObservation,
)
from paper_data_suite.cli import main
from paper_data_suite.settings import (
    MAX_RECENT_COMPONENTS,
    SuiteSettings,
    SuiteSettingsPathError,
    SuiteSettingsReadError,
    SuiteSettingsSchemaError,
    SuiteSettingsWriteError,
    clear_recent_components,
    default_suite_settings,
    load_suite_settings,
    parse_suite_settings,
    record_recent_component,
    reset_suite_settings,
    save_suite_settings,
    serialize_suite_settings,
    suite_settings_path,
)
from paper_data_suite.settings_cli import render_suite_settings

_ALLOWED = ("concord", "meridian", "quillan", "scoreform", "vitrine", "portia")


def _settings_path(tmp_path: Path) -> Path:
    return tmp_path / "config" / "settings.json"


def _document(recent: tuple[str, ...] = ()) -> str:
    return json.dumps(
        {
            "record_type": "paper_data_suite_settings",
            "schema_version": "1",
            "recent_components": list(recent),
        }
    )


def _application(
    component_id: str,
    *,
    status: ApplicationLaunchStatus = ApplicationLaunchStatus.AVAILABLE,
) -> ApplicationObservation:
    return ApplicationObservation(
        component_id=component_id,
        display_name=component_id.title(),
        purpose=f"Teacher purpose for {component_id}.",
        distribution=component_id,
        qualified_version="1.0.0",
        installed_version=(
            "1.0.0"
            if status is not ApplicationLaunchStatus.NOT_INSTALLED
            else None
        ),
        console_script_name=component_id,
        console_script_target=f"{component_id}.cli:main",
        status=status,
        reason="synthetic status",
        launcher_path=(
            Path(f"/synthetic/{component_id}")
            if status is ApplicationLaunchStatus.AVAILABLE
            else None
        ),
    )


def test_valid_v1_settings_parse_to_immutable_model() -> None:
    parsed = parse_suite_settings(
        _document(("quillan", "scoreform")),
        allowed_component_ids=_ALLOWED,
    )

    assert parsed == SuiteSettings(recent_components=("quillan", "scoreform"))


@pytest.mark.parametrize(
    "payload, message",
    [
        ("[]", "JSON object"),
        (
            json.dumps(
                {
                    "record_type": "wrong",
                    "schema_version": "1",
                    "recent_components": [],
                }
            ),
            "record_type",
        ),
        (
            json.dumps(
                {
                    "record_type": "paper_data_suite_settings",
                    "schema_version": "2",
                    "recent_components": [],
                }
            ),
            "unsupported",
        ),
        (
            json.dumps(
                {
                    "record_type": "paper_data_suite_settings",
                    "schema_version": "1",
                    "recent_components": [],
                    "future": True,
                }
            ),
            "unknown fields",
        ),
        (
            json.dumps(
                {
                    "record_type": "paper_data_suite_settings",
                    "schema_version": "1",
                }
            ),
            "missing fields",
        ),
    ],
)
def test_schema_is_strict(payload: str, message: str) -> None:
    with pytest.raises(SuiteSettingsSchemaError, match=message):
        parse_suite_settings(payload, allowed_component_ids=_ALLOWED)


def test_duplicate_json_keys_are_rejected() -> None:
    text = (
        '{"record_type":"paper_data_suite_settings",'
        '"schema_version":"1","schema_version":"1","recent_components":[]}'
    )
    with pytest.raises(SuiteSettingsSchemaError, match="duplicate JSON object key"):
        parse_suite_settings(text, allowed_component_ids=_ALLOWED)


def test_unknown_component_id_is_rejected() -> None:
    with pytest.raises(
        SuiteSettingsSchemaError,
        match="suite-qualified application ID",
    ):
        parse_suite_settings(
            _document(("student-123",)),
            allowed_component_ids=_ALLOWED,
        )


def test_duplicate_recent_components_are_rejected_on_parse() -> None:
    with pytest.raises(SuiteSettingsSchemaError, match="duplicates"):
        parse_suite_settings(
            _document(("quillan", "quillan")),
            allowed_component_ids=_ALLOWED,
        )


def test_recent_component_document_is_bounded() -> None:
    recent = tuple(f"app{index}" for index in range(MAX_RECENT_COMPONENTS + 1))
    with pytest.raises(SuiteSettingsSchemaError, match="cannot contain more than"):
        parse_suite_settings(
            _document(recent),
            allowed_component_ids=recent,
        )


def test_serialization_is_deterministic_utf8_json_with_stable_newline() -> None:
    settings = SuiteSettings(recent_components=("quillan", "scoreform"))
    first = serialize_suite_settings(settings, allowed_component_ids=_ALLOWED)
    second = serialize_suite_settings(settings, allowed_component_ids=_ALLOWED)

    assert first == second
    assert first.endswith("\n")
    assert not first.endswith("\n\n")
    assert first.encode("utf-8").decode("utf-8") == first
    assert list(json.loads(first)) == [
        "record_type",
        "schema_version",
        "recent_components",
    ]


def test_missing_settings_file_returns_defaults_without_creating_parent(
    tmp_path: Path,
) -> None:
    path = _settings_path(tmp_path)

    assert (
        load_suite_settings(path, allowed_component_ids=_ALLOWED)
        == default_suite_settings()
    )
    assert not path.exists()
    assert not path.parent.exists()


def test_platform_settings_locations_are_deterministic_and_workspace_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)

    windows = suite_settings_path(
        platform="win32",
        environ={"LOCALAPPDATA": str(tmp_path / "local")},
        home=home,
    )
    linux = suite_settings_path(
        platform="linux",
        environ={"XDG_CONFIG_HOME": str(tmp_path / "xdg")},
        home=home,
    )
    macos = suite_settings_path(platform="darwin", environ={}, home=home)

    assert windows == tmp_path / "local" / "Paper Data Suite" / "settings.json"
    assert linux == tmp_path / "xdg" / "paper-data-suite" / "settings.json"
    assert macos == (
        home / "Library" / "Application Support" / "Paper Data Suite" / "settings.json"
    )
    assert "workspace" not in windows.parts
    assert "workspace" not in linux.parts
    assert "workspace" not in macos.parts


def test_windows_relative_local_app_data_falls_back_to_home(tmp_path: Path) -> None:
    path = suite_settings_path(
        platform="win32",
        environ={"LOCALAPPDATA": "relative-local"},
        home=tmp_path / "home",
    )
    assert path == (
        tmp_path
        / "home"
        / "AppData"
        / "Local"
        / "Paper Data Suite"
        / "settings.json"
    )


def test_linux_relative_xdg_config_home_falls_back_to_home(tmp_path: Path) -> None:
    path = suite_settings_path(
        platform="linux",
        environ={"XDG_CONFIG_HOME": "relative-config"},
        home=tmp_path / "home",
    )
    assert path == tmp_path / "home" / ".config" / "paper-data-suite" / "settings.json"


def test_record_recent_component_is_mru_deduplicated_and_bounded(
    tmp_path: Path,
) -> None:
    path = _settings_path(tmp_path)
    allowed = tuple(f"app{index}" for index in range(7))

    for component_id in allowed[:6]:
        record_recent_component(
            component_id,
            path,
            allowed_component_ids=allowed,
        )
    updated = record_recent_component(
        "app3",
        path,
        allowed_component_ids=allowed,
    )

    assert updated.recent_components == ("app3", "app5", "app4", "app2", "app1")
    assert len(updated.recent_components) == MAX_RECENT_COMPONENTS
    assert len(set(updated.recent_components)) == len(updated.recent_components)


def test_clear_recent_only_clears_recent_context(tmp_path: Path) -> None:
    path = _settings_path(tmp_path)
    save_suite_settings(
        SuiteSettings(recent_components=("quillan", "scoreform")),
        path,
        allowed_component_ids=_ALLOWED,
    )

    cleared = clear_recent_components(path, allowed_component_ids=_ALLOWED)

    assert cleared == default_suite_settings()
    assert (
        load_suite_settings(path, allowed_component_ids=_ALLOWED)
        == default_suite_settings()
    )


def test_reset_replaces_malformed_settings_without_reading_it(tmp_path: Path) -> None:
    path = _settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    reset_suite_settings(path, allowed_component_ids=_ALLOWED)

    assert (
        load_suite_settings(path, allowed_component_ids=_ALLOWED)
        == default_suite_settings()
    )


def test_malformed_settings_fail_with_bounded_read_error(tmp_path: Path) -> None:
    path = _settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(SuiteSettingsReadError, match="invalid settings JSON"):
        load_suite_settings(path, allowed_component_ids=_ALLOWED)


def test_settings_target_directory_is_rejected(tmp_path: Path) -> None:
    path = _settings_path(tmp_path)
    path.mkdir(parents=True)

    with pytest.raises(SuiteSettingsPathError, match="ordinary file"):
        load_suite_settings(path, allowed_component_ids=_ALLOWED)


def test_settings_target_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text(_document(), encoding="utf-8")
    path = _settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    with pytest.raises(SuiteSettingsPathError, match="symbolic link"):
        load_suite_settings(path, allowed_component_ids=_ALLOWED)


def test_dangling_settings_symlink_is_rejected(tmp_path: Path) -> None:
    path = _settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    try:
        path.symlink_to(tmp_path / "missing.json")
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    with pytest.raises(SuiteSettingsPathError, match="symbolic link"):
        load_suite_settings(path, allowed_component_ids=_ALLOWED)


def test_settings_parent_symlink_is_rejected(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-config"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-config"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    with pytest.raises(SuiteSettingsPathError, match="symbolic link"):
        save_suite_settings(
            default_suite_settings(),
            linked_parent / "settings.json",
            allowed_component_ids=_ALLOWED,
        )


def test_replacement_failure_preserves_previous_valid_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.settings as settings_module

    path = _settings_path(tmp_path)
    save_suite_settings(
        SuiteSettings(recent_components=("quillan",)),
        path,
        allowed_component_ids=_ALLOWED,
    )
    before = path.read_bytes()

    def fail_replace(source: object, destination: object) -> None:
        del source, destination
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(settings_module.os, "replace", fail_replace)
    with pytest.raises(SuiteSettingsWriteError, match="atomically"):
        save_suite_settings(
            SuiteSettings(recent_components=("scoreform",)),
            path,
            allowed_component_ids=_ALLOWED,
        )

    assert path.read_bytes() == before
    assert tuple(path.parent.glob(".settings.json.*.tmp")) == ()




def test_temporary_creation_failure_preserves_previous_valid_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.settings as settings_module

    path = _settings_path(tmp_path)
    save_suite_settings(
        SuiteSettings(recent_components=("quillan",)),
        path,
        allowed_component_ids=_ALLOWED,
    )
    before = path.read_bytes()

    def fail_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        del args, kwargs
        raise OSError("synthetic temporary creation failure")

    monkeypatch.setattr(settings_module.tempfile, "mkstemp", fail_mkstemp)
    with pytest.raises(SuiteSettingsWriteError, match="atomically"):
        save_suite_settings(
            SuiteSettings(recent_components=("scoreform",)),
            path,
            allowed_component_ids=_ALLOWED,
        )

    assert path.read_bytes() == before

def test_serialization_failure_preserves_previous_valid_document(
    tmp_path: Path,
) -> None:
    path = _settings_path(tmp_path)
    save_suite_settings(
        SuiteSettings(recent_components=("quillan",)),
        path,
        allowed_component_ids=_ALLOWED,
    )
    before = path.read_bytes()

    with pytest.raises(SuiteSettingsSchemaError):
        save_suite_settings(
            SuiteSettings(recent_components=("student-123",)),
            path,
            allowed_component_ids=_ALLOWED,
        )

    assert path.read_bytes() == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode semantics only")
def test_successful_settings_write_uses_private_posix_file_mode(tmp_path: Path) -> None:
    path = _settings_path(tmp_path)

    save_suite_settings(
        SuiteSettings(recent_components=("quillan",)),
        path,
        allowed_component_ids=_ALLOWED,
    )

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_temporary_file_is_created_only_inside_settings_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.settings as settings_module

    path = _settings_path(tmp_path)
    observed: list[Path] = []
    original = settings_module.tempfile.mkstemp

    def observe_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        directory = Path(str(kwargs["dir"]))
        observed.append(directory)
        return original(*args, **kwargs)

    monkeypatch.setattr(settings_module.tempfile, "mkstemp", observe_mkstemp)
    save_suite_settings(
        SuiteSettings(recent_components=("quillan",)),
        path,
        allowed_component_ids=_ALLOWED,
    )

    assert observed == [path.parent]


def test_settings_model_has_no_surface_for_domain_or_student_state() -> None:
    with pytest.raises(TypeError):
        SuiteSettings(  # type: ignore[call-arg]
            recent_components=("quillan",),
            student_id="student-001",
            score=99,
            feedback="synthetic private feedback",
        )

    attempted = json.dumps(
        {
            "record_type": "paper_data_suite_settings",
            "schema_version": "1",
            "recent_components": ["quillan"],
            "student_id": "student-001",
            "answers": ["A"],
            "score": 99,
            "writing": "synthetic student writing",
            "teacher_note": "synthetic note",
            "raw_scan": "scan-001.png",
            "grouping_band": 4,
            "portfolio_candidate": "candidate-001",
            "behavior_narrative": "synthetic behavior narrative",
        }
    )
    with pytest.raises(SuiteSettingsSchemaError, match="unknown fields"):
        parse_suite_settings(attempted, allowed_component_ids=_ALLOWED)


def _workspace_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        sorted(
            (
                path.relative_to(root).as_posix(),
                path.read_bytes(),
            )
            for path in root.rglob("*")
            if path.is_file()
        )
    )


def test_settings_operations_do_not_touch_synthetic_domain_state(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    sentinels = {
        "core/roster.json": b"synthetic roster",
        "scoreform/work.json": b"synthetic answers",
        "quillan/review.json": b"synthetic writing review",
        "concord/group-plan.json": b"synthetic grouping",
        "meridian/grades.json": b"synthetic grades",
        "vitrine/portfolio.json": b"synthetic portfolio",
        "portia/event.json": b"synthetic support event",
    }
    for relative, content in sentinels.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = _workspace_snapshot(workspace)
    settings_path = tmp_path / "outside-workspace" / "settings.json"

    record_recent_component(
        "quillan",
        settings_path,
        allowed_component_ids=_ALLOWED,
    )
    clear_recent_components(settings_path, allowed_component_ids=_ALLOWED)
    reset_suite_settings(settings_path, allowed_component_ids=_ALLOWED)

    assert _workspace_snapshot(workspace) == before
    assert settings_path.is_file()


def test_importing_settings_does_not_create_user_configuration(tmp_path: Path) -> None:
    user_home = tmp_path / "user"
    local = user_home / "AppData" / "Local"
    xdg = user_home / ".config"
    env = dict(os.environ)
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(user_home),
            "USERPROFILE": str(user_home),
            "LOCALAPPDATA": str(local),
            "XDG_CONFIG_HOME": str(xdg),
        }
    )

    code = """
import sys
import paper_data_suite
import paper_data_suite.settings

for name in ("scoreform", "quillan", "concord", "meridian", "vitrine", "portia"):
    if name in sys.modules:
        raise SystemExit(f"unexpected sibling import: {name}")
""".strip()
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (local / "Paper Data Suite").exists()
    assert not (xdg / "paper-data-suite").exists()


def test_render_settings_revalidates_and_marks_current_availability() -> None:
    settings = SuiteSettings(recent_components=("quillan", "scoreform", "concord"))
    inventory = ApplicationInventory(
        (
            _application("quillan"),
            _application("scoreform", status=ApplicationLaunchStatus.NOT_INSTALLED),
        )
    )

    output = render_suite_settings(settings, inventory)

    assert "1. Quillan (available)" in output
    assert "2. Scoreform (not installed)" in output
    assert "3. concord (not in current inventory)" in output
    assert "Managed by PDS Core" in output
    assert "workspace_root" not in output
    assert "settings.json" not in output


def test_settings_help_and_missing_subcommand_are_deterministic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("settings", "--help"))
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "usage: pds settings" in output
    assert "clear-recent" in output
    assert "reset" in output

    assert main(("settings",)) == 0
    assert "usage: pds settings" in capsys.readouterr().out


def test_launch_records_recency_after_child_started_and_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    application = _application("quillan")
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((application,)),
    )
    recorded: list[str] = []

    def launch(value: ApplicationObservation) -> ApplicationLaunchResult:
        assert value.launcher_path is not None
        return ApplicationLaunchResult(
            component_id=value.component_id,
            display_name=value.display_name,
            launcher_path=value.launcher_path,
            exit_code=0,
        )

    monkeypatch.setattr(cli, "launch_application", launch)
    monkeypatch.setattr(cli, "record_recent_component", recorded.append)

    assert main(("launch", "quillan")) == 0
    assert recorded == ["quillan"]


def test_launch_nonzero_still_records_because_child_did_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    application = _application("quillan")
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((application,)),
    )
    recorded: list[str] = []

    def launch(value: ApplicationObservation) -> ApplicationLaunchResult:
        assert value.launcher_path is not None
        return ApplicationLaunchResult(
            component_id=value.component_id,
            display_name=value.display_name,
            launcher_path=value.launcher_path,
            exit_code=4,
        )

    monkeypatch.setattr(cli, "launch_application", launch)
    monkeypatch.setattr(cli, "record_recent_component", recorded.append)

    assert main(("launch", "quillan")) == 1
    assert recorded == ["quillan"]


def test_launch_start_failure_does_not_record_recency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    application = _application("quillan")
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((application,)),
    )
    recorded: list[str] = []

    def fail(value: ApplicationObservation) -> ApplicationLaunchResult:
        del value
        raise ApplicationLaunchExecutionError("synthetic start failure")

    monkeypatch.setattr(cli, "launch_application", fail)
    monkeypatch.setattr(cli, "record_recent_component", recorded.append)

    assert main(("launch", "quillan")) == 1
    assert recorded == []


def test_unavailable_launch_does_not_record_recency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    application = _application(
        "quillan",
        status=ApplicationLaunchStatus.NOT_INSTALLED,
    )
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((application,)),
    )
    recorded: list[str] = []
    monkeypatch.setattr(cli, "record_recent_component", recorded.append)

    assert main(("launch", "quillan")) == 1
    assert recorded == []


def test_settings_failure_after_launch_is_warning_not_domain_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli

    application = _application("quillan")
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((application,)),
    )

    def launch(value: ApplicationObservation) -> ApplicationLaunchResult:
        assert value.launcher_path is not None
        return ApplicationLaunchResult(
            component_id=value.component_id,
            display_name=value.display_name,
            launcher_path=value.launcher_path,
            exit_code=0,
        )

    def fail_settings(component_id: str) -> object:
        del component_id
        raise SuiteSettingsWriteError("synthetic settings failure")

    monkeypatch.setattr(cli, "launch_application", launch)
    monkeypatch.setattr(cli, "record_recent_component", fail_settings)

    assert main(("launch", "quillan")) == 0
    error = capsys.readouterr().err
    assert "Warning:" in error
    assert "recent component context was not saved" in error
    assert "module data" not in error.casefold()


def test_settings_reset_dispatch_is_distinct_from_workspace_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    observed: list[str] = []
    monkeypatch.setattr(
        cli,
        "run_settings_reset",
        lambda: observed.append("settings") or 0,
    )
    monkeypatch.setattr(
        cli,
        "run_workspace_reset",
        lambda: (_ for _ in ()).throw(AssertionError("workspace reset called")),
    )

    assert main(("settings", "reset")) == 0
    assert observed == ["settings"]


def test_settings_cli_read_failure_is_bounded_and_points_only_to_settings_reset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.settings_cli as settings_cli

    def fail_load() -> SuiteSettings:
        raise SuiteSettingsReadError("synthetic malformed settings")

    monkeypatch.setattr(settings_cli, "load_suite_settings", fail_load)

    assert settings_cli.run_settings_show() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "settings could not be read" in captured.err
    assert "pds settings reset" in captured.err
    assert "workspace reset" not in captured.err


@pytest.mark.parametrize(
    "subcommand,function_name",
    [
        ("show", "run_settings_show"),
        ("clear-recent", "run_settings_clear_recent"),
        ("reset", "run_settings_reset"),
    ],
)
def test_settings_subcommands_dispatch_only_to_settings_handlers(
    subcommand: str,
    function_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    observed: list[str] = []
    monkeypatch.setattr(
        cli,
        function_name,
        lambda: observed.append(subcommand) or 0,
    )
    monkeypatch.setattr(
        cli,
        "run_workspace_reset",
        lambda: (_ for _ in ()).throw(AssertionError("workspace reset called")),
    )

    assert main(("settings", subcommand)) == 0
    assert observed == [subcommand]
