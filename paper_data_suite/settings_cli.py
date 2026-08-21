"""Teacher-facing rendering and deterministic CLI actions for suite settings."""

from __future__ import annotations

import sys
from collections.abc import Callable

from paper_data_suite.application_launching import resolve_application_launchers
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationInventoryError,
    ApplicationLaunchStatus,
    collect_application_inventory,
)
from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    load_release_compatibility_manifest,
)
from paper_data_suite.settings import (
    SuiteSettings,
    SuiteSettingsError,
    clear_recent_components,
    load_suite_settings,
    reset_suite_settings,
)

InventoryProvider = Callable[[], ApplicationInventory]

_STATUS_LABELS = {
    ApplicationLaunchStatus.AVAILABLE: "available",
    ApplicationLaunchStatus.NOT_INSTALLED: "not installed",
    ApplicationLaunchStatus.INCOMPATIBLE: "incompatible",
    ApplicationLaunchStatus.UNAVAILABLE: "unavailable",
}


def current_application_inventory() -> ApplicationInventory:
    """Revalidate launchable component status against the current suite inventory."""
    manifest = load_release_compatibility_manifest()
    inventory = collect_application_inventory(manifest)
    return resolve_application_launchers(inventory)


def render_suite_settings(
    settings: SuiteSettings,
    inventory: ApplicationInventory,
) -> str:
    """Render bounded safe settings without dumping raw JSON or workspace paths."""
    lines = ["Paper Data Suite settings", "", "Recent components:"]
    if not settings.recent_components:
        lines.append("  None")
    else:
        for index, component_id in enumerate(settings.recent_components, start=1):
            application = inventory.for_component(component_id)
            if application is None:
                lines.append(f"  {index}. {component_id} (not in current inventory)")
                continue
            status = _STATUS_LABELS[application.status]
            lines.append(f"  {index}. {application.display_name} ({status})")
    lines.extend(
        (
            "",
            "Canonical workspace:",
            "  Managed by PDS Core; no workspace selection is stored here.",
        )
    )
    return "\n".join(lines) + "\n"


def _settings_read_failure(error: SuiteSettingsError) -> None:
    detail = str(error)[:300] or error.__class__.__name__
    print("Paper Data Suite settings could not be read.", file=sys.stderr)
    print(f"Detail: {detail}", file=sys.stderr)
    print(
        "Run `pds settings reset` to replace only the shell preference file.",
        file=sys.stderr,
    )


def _settings_write_failure(error: SuiteSettingsError) -> None:
    detail = str(error)[:300] or error.__class__.__name__
    print("Paper Data Suite settings could not be updated.", file=sys.stderr)
    print(f"Detail: {detail}", file=sys.stderr)
    print("No Core workspace or module state was changed.", file=sys.stderr)


def run_settings_show(
    *,
    inventory_provider: InventoryProvider = current_application_inventory,
) -> int:
    """Show bounded suite convenience state and current component availability."""
    try:
        settings = load_suite_settings()
    except SuiteSettingsError as error:
        _settings_read_failure(error)
        return 1

    try:
        inventory = inventory_provider()
    except (ApplicationInventoryError, CompatibilityManifestError, OSError) as error:
        message = str(error)[:300] or error.__class__.__name__
        print(
            "Paper Data Suite settings loaded, but current application status "
            f"could not be resolved: {message}",
            file=sys.stderr,
        )
        return 1

    print(render_suite_settings(settings, inventory), end="")
    return 0


def run_settings_clear_recent() -> int:
    """Clear only the suite-owned bounded recent-component list."""
    try:
        clear_recent_components()
    except SuiteSettingsError as error:
        _settings_write_failure(error)
        return 1
    print("Cleared Paper Data Suite recent component context.")
    print("Core workspace selection and module-owned context were not changed.")
    return 0


def run_settings_reset() -> int:
    """Replace only suite-owned settings with disposable schema-v1 defaults."""
    try:
        reset_suite_settings()
    except SuiteSettingsError as error:
        _settings_write_failure(error)
        return 1
    print("Reset Paper Data Suite shell settings to defaults.")
    print("Core workspace selection and module-owned state were not changed.")
    return 0


__all__ = (
    "InventoryProvider",
    "current_application_inventory",
    "render_suite_settings",
    "run_settings_clear_recent",
    "run_settings_reset",
    "run_settings_show",
)
