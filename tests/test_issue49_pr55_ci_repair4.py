"""PR #55 CI Repair 4: optional module inventory and Win32 import safety."""

from __future__ import annotations

import os

import pytest

from paper_data_suite.evergreen_windows_installer_held_checkpoint_read import (
    HeldCheckpointReadError,
    _windows_api,
)
from scripts import smoke_test_combined_suite_wheels as combined


def _missing_optional_inventory() -> str:
    return (
        "Paper Data Suite applications\n\n"
        "Meridian\n"
        "  Status: not installed\n"
        "  Component ID: meridian\n\n"
        "Portia\n"
        "  Status: not installed\n"
        "  Component ID: portia\n"
    )


def test_uninstalled_new_optional_components_are_valid_inventory() -> None:
    combined._assert_module_inventory(_missing_optional_inventory(), ())


@pytest.mark.parametrize(
    "invalid",
    [
        _missing_optional_inventory().replace(
            "  Component ID: meridian", "  Component ID: unknown"
        ),
        _missing_optional_inventory().replace(
            "  Status: not installed", "  Status: available", 1
        ),
        _missing_optional_inventory() + "  Launch: pds launch portia\n",
        _missing_optional_inventory() + "\nPDS Core\n",
        _missing_optional_inventory() + "\nforeign.cli:main\n",
    ],
)
def test_uninstalled_optional_inventory_does_not_grant_launch(invalid: str) -> None:
    with pytest.raises(combined.CombinedSuiteSmokeError):
        combined._assert_module_inventory(invalid, ())


def test_win32_loader_refuses_non_windows_without_import_side_effects() -> None:
    if os.name == "nt":
        pytest.skip("Win32 loader is a runtime-only Windows check")
    with pytest.raises(HeldCheckpointReadError, match="Windows is required"):
        _windows_api()
