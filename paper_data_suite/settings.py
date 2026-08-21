"""Privacy-minimized suite-owned settings and recent component context."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, cast

from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    load_release_compatibility_manifest,
)

_SETTINGS_RECORD_TYPE: Final = "paper_data_suite_settings"
_SETTINGS_SCHEMA_VERSION: Final = "1"
_SETTINGS_FILENAME: Final = "settings.json"
_MAX_RECENT_COMPONENTS: Final = 5
_MAX_SETTINGS_BYTES: Final = 16 * 1024
_REQUIRED_FIELDS: Final = frozenset(
    {"record_type", "schema_version", "recent_components"}
)


class SuiteSettingsError(RuntimeError):
    """Base class for bounded suite-settings failures."""


class SuiteSettingsSchemaError(SuiteSettingsError):
    """Raised when persisted settings violate the strict v1 schema."""


class SuiteSettingsPathError(SuiteSettingsError):
    """Raised when the settings path is unsafe or unsupported."""


class SuiteSettingsReadError(SuiteSettingsError):
    """Raised when an existing settings document cannot be read safely."""


class SuiteSettingsWriteError(SuiteSettingsError):
    """Raised when settings cannot be persisted atomically."""


@dataclass(frozen=True, slots=True)
class SuiteSettings:
    """Immutable schema-v1 shell preferences owned by the suite."""

    record_type: str = _SETTINGS_RECORD_TYPE
    schema_version: str = _SETTINGS_SCHEMA_VERSION
    recent_components: tuple[str, ...] = ()


def default_suite_settings() -> SuiteSettings:
    """Return the disposable first-run/default suite settings state."""
    return SuiteSettings()


def suite_settings_path(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve one deterministic per-user settings path outside PDS workspaces."""
    active_platform = (platform or sys.platform).lower()
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home

    if active_platform.startswith(("win32", "cygwin", "msys")):
        configured = environment.get("LOCALAPPDATA", "").strip()
        configured_path = Path(configured) if configured else None
        root = (
            configured_path
            if configured_path is not None and configured_path.is_absolute()
            else user_home / "AppData" / "Local"
        )
        return root / "Paper Data Suite" / _SETTINGS_FILENAME

    if active_platform == "darwin":
        return (
            user_home
            / "Library"
            / "Application Support"
            / "Paper Data Suite"
            / _SETTINGS_FILENAME
        )

    configured = environment.get("XDG_CONFIG_HOME", "").strip()
    configured_path = Path(configured) if configured else None
    root = (
        configured_path
        if configured_path is not None and configured_path.is_absolute()
        else user_home / ".config"
    )
    return root / "paper-data-suite" / _SETTINGS_FILENAME


def _duplicate_rejecting_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SuiteSettingsSchemaError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _qualified_launchable_component_ids() -> frozenset[str]:
    try:
        manifest = load_release_compatibility_manifest()
    except (CompatibilityManifestError, OSError) as error:
        raise SuiteSettingsSchemaError(
            "suite compatibility data is unavailable for component validation"
        ) from error
    return frozenset(
        component.component_id
        for component in manifest.components
        if "launchable_application" in component.capabilities
    )


def _allowed_ids(
    allowed_component_ids: Collection[str] | None,
) -> frozenset[str]:
    if allowed_component_ids is None:
        return _qualified_launchable_component_ids()
    return frozenset(allowed_component_ids)


def _parse_recent_components(
    value: object,
    *,
    allowed_component_ids: frozenset[str],
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SuiteSettingsSchemaError("recent_components must be an array")
    if len(value) > _MAX_RECENT_COMPONENTS:
        raise SuiteSettingsSchemaError(
            "recent_components cannot contain more than "
            f"{_MAX_RECENT_COMPONENTS} entries"
        )

    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise SuiteSettingsSchemaError(
                f"recent_components[{index}] must be a non-empty component ID"
            )
        if item not in allowed_component_ids:
            raise SuiteSettingsSchemaError(
                f"recent_components[{index}] is not a suite-qualified application ID"
            )
        if item in result:
            raise SuiteSettingsSchemaError(
                "recent_components cannot contain duplicates"
            )
        result.append(item)
    return tuple(result)


def parse_suite_settings(
    text: str,
    *,
    allowed_component_ids: Collection[str] | None = None,
) -> SuiteSettings:
    """Parse one strict schema-v1 settings document into an immutable model."""
    try:
        raw = json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except SuiteSettingsSchemaError:
        raise
    except json.JSONDecodeError as error:
        raise SuiteSettingsSchemaError(
            f"invalid settings JSON: {error.msg}"
        ) from error

    if not isinstance(raw, dict):
        raise SuiteSettingsSchemaError("settings document must be a JSON object")
    data = cast(dict[str, object], raw)
    keys = frozenset(data)
    missing = sorted(_REQUIRED_FIELDS - keys)
    unknown = sorted(keys - _REQUIRED_FIELDS)
    if missing:
        raise SuiteSettingsSchemaError(
            f"settings document is missing fields: {', '.join(missing)}"
        )
    if unknown:
        raise SuiteSettingsSchemaError(
            f"settings document has unknown fields: {', '.join(unknown)}"
        )

    record_type = data["record_type"]
    if record_type != _SETTINGS_RECORD_TYPE:
        raise SuiteSettingsSchemaError(
            f"record_type must be {_SETTINGS_RECORD_TYPE!r}"
        )
    schema_version = data["schema_version"]
    if not isinstance(schema_version, str):
        raise SuiteSettingsSchemaError("schema_version must be a string")
    if schema_version != _SETTINGS_SCHEMA_VERSION:
        raise SuiteSettingsSchemaError(
            f"unsupported suite settings schema version: {schema_version!r}"
        )

    recent_components = _parse_recent_components(
        data["recent_components"],
        allowed_component_ids=_allowed_ids(allowed_component_ids),
    )
    return SuiteSettings(
        record_type=_SETTINGS_RECORD_TYPE,
        schema_version=_SETTINGS_SCHEMA_VERSION,
        recent_components=recent_components,
    )


def _validated_model(
    settings: SuiteSettings,
    *,
    allowed_component_ids: Collection[str] | None = None,
) -> SuiteSettings:
    if settings.record_type != _SETTINGS_RECORD_TYPE:
        raise SuiteSettingsSchemaError(
            f"record_type must be {_SETTINGS_RECORD_TYPE!r}"
        )
    if settings.schema_version != _SETTINGS_SCHEMA_VERSION:
        raise SuiteSettingsSchemaError(
            f"unsupported suite settings schema version: {settings.schema_version!r}"
        )
    if not isinstance(settings.recent_components, tuple):
        raise SuiteSettingsSchemaError("recent_components must be an immutable tuple")
    recent_components = _parse_recent_components(
        list(settings.recent_components),
        allowed_component_ids=_allowed_ids(allowed_component_ids),
    )
    return SuiteSettings(recent_components=recent_components)


def serialize_suite_settings(
    settings: SuiteSettings,
    *,
    allowed_component_ids: Collection[str] | None = None,
) -> str:
    """Serialize validated settings as deterministic UTF-8 JSON text."""
    validated = _validated_model(
        settings,
        allowed_component_ids=allowed_component_ids,
    )
    payload = {
        "record_type": validated.record_type,
        "schema_version": validated.schema_version,
        "recent_components": list(validated.recent_components),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    ) + "\n"


def _is_redirect_entry(path: Path) -> bool:
    """Return whether one existing entry is a link/reparse redirection."""
    try:
        observation = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise SuiteSettingsPathError(
            "suite settings filesystem entry could not be inspected safely"
        ) from error
    attributes = int(getattr(observation, "st_file_attributes", 0))
    return stat.S_ISLNK(observation.st_mode) or bool(
        attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _checked_existing_settings_path(path: Path) -> None:
    parent = path.parent
    if _is_redirect_entry(parent):
        raise SuiteSettingsPathError(
            "suite settings directory cannot be a symbolic link or reparse point"
        )
    if parent.exists() and not parent.is_dir():
        raise SuiteSettingsPathError("suite settings directory is not a safe directory")
    if _is_redirect_entry(path):
        raise SuiteSettingsPathError(
            "suite settings file cannot be a symbolic link or reparse point"
        )
    if not path.exists():
        return
    if not path.is_file():
        raise SuiteSettingsPathError("suite settings target must be an ordinary file")


def load_suite_settings(
    path: Path | None = None,
    *,
    allowed_component_ids: Collection[str] | None = None,
) -> SuiteSettings:
    """Load settings without creating files; missing is the normal default state."""
    target = suite_settings_path() if path is None else Path(path)
    _checked_existing_settings_path(target)
    if not target.exists():
        return default_suite_settings()

    try:
        size = target.stat().st_size
    except OSError as error:
        raise SuiteSettingsReadError(
            "suite settings metadata could not be read"
        ) from error
    if size > _MAX_SETTINGS_BYTES:
        raise SuiteSettingsReadError(
            "suite settings document exceeds the supported size"
        )

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise SuiteSettingsReadError("suite settings must be valid UTF-8") from error
    except OSError as error:
        raise SuiteSettingsReadError(
            "suite settings document could not be read"
        ) from error

    try:
        return parse_suite_settings(
            text,
            allowed_component_ids=allowed_component_ids,
        )
    except SuiteSettingsSchemaError as error:
        raise SuiteSettingsReadError(str(error)) from error


def _ensure_writable_settings_directory(path: Path) -> None:
    parent = path.parent
    if _is_redirect_entry(parent):
        raise SuiteSettingsPathError(
            "suite settings directory cannot be a symbolic link or reparse point"
        )
    if parent.exists():
        if not parent.is_dir():
            raise SuiteSettingsPathError(
                "suite settings directory is not a safe directory"
            )
        return
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise SuiteSettingsWriteError(
            "suite settings directory could not be created"
        ) from error
    if _is_redirect_entry(parent) or not parent.is_dir():
        raise SuiteSettingsPathError("suite settings directory is not a safe directory")


def save_suite_settings(
    settings: SuiteSettings,
    path: Path | None = None,
    *,
    allowed_component_ids: Collection[str] | None = None,
) -> None:
    """Persist one complete validated settings document with atomic replacement."""
    target = suite_settings_path() if path is None else Path(path)
    try:
        text = serialize_suite_settings(
            settings,
            allowed_component_ids=allowed_component_ids,
        )
    except SuiteSettingsSchemaError:
        raise

    _ensure_writable_settings_directory(target)
    _checked_existing_settings_path(target)

    temporary_path: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary_path = Path(raw_temporary)
        if temporary_path.parent != target.parent:
            raise SuiteSettingsPathError(
                "suite settings temporary file escaped the settings directory"
            )
        if os.name != "nt":
            temporary_path.chmod(0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    except SuiteSettingsError:
        raise
    except OSError as error:
        raise SuiteSettingsWriteError(
            "suite settings could not be written atomically"
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def record_recent_component(
    component_id: str,
    path: Path | None = None,
    *,
    allowed_component_ids: Collection[str] | None = None,
) -> SuiteSettings:
    """Move one qualified top-level application ID to the front of the MRU list."""
    allowed = _allowed_ids(allowed_component_ids)
    if component_id not in allowed:
        raise SuiteSettingsSchemaError(
            "recent component must be a suite-qualified launchable application ID"
        )
    current = load_suite_settings(path, allowed_component_ids=allowed)
    recent = (component_id,) + tuple(
        item for item in current.recent_components if item != component_id
    )
    updated = replace(current, recent_components=recent[:_MAX_RECENT_COMPONENTS])
    save_suite_settings(updated, path, allowed_component_ids=allowed)
    return updated


def clear_recent_components(
    path: Path | None = None,
    *,
    allowed_component_ids: Collection[str] | None = None,
) -> SuiteSettings:
    """Clear only suite-owned recent component convenience state."""
    allowed = _allowed_ids(allowed_component_ids)
    current = load_suite_settings(path, allowed_component_ids=allowed)
    updated = replace(current, recent_components=())
    save_suite_settings(updated, path, allowed_component_ids=allowed)
    return updated


def reset_suite_settings(
    path: Path | None = None,
    *,
    allowed_component_ids: Collection[str] | None = None,
) -> SuiteSettings:
    """Atomically replace only suite settings with the schema-v1 defaults."""
    settings = default_suite_settings()
    save_suite_settings(
        settings,
        path,
        allowed_component_ids=allowed_component_ids,
    )
    return settings


MAX_RECENT_COMPONENTS: Final = _MAX_RECENT_COMPONENTS
SETTINGS_RECORD_TYPE: Final = _SETTINGS_RECORD_TYPE
SETTINGS_SCHEMA_VERSION: Final = _SETTINGS_SCHEMA_VERSION

__all__ = (
    "MAX_RECENT_COMPONENTS",
    "SETTINGS_RECORD_TYPE",
    "SETTINGS_SCHEMA_VERSION",
    "SuiteSettings",
    "SuiteSettingsError",
    "SuiteSettingsPathError",
    "SuiteSettingsReadError",
    "SuiteSettingsSchemaError",
    "SuiteSettingsWriteError",
    "clear_recent_components",
    "default_suite_settings",
    "load_suite_settings",
    "parse_suite_settings",
    "record_recent_component",
    "reset_suite_settings",
    "save_suite_settings",
    "serialize_suite_settings",
    "suite_settings_path",
)
