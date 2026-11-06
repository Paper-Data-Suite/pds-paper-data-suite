"""Slice 103: native-evidence mode is explicit and cannot fall back to launch."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import Mock

import pytest

from paper_data_suite.evergreen_signed_lab_cli import (
    add_signed_lab_arguments,
    dispatch_launch,
)


def _parse(*args: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("component_id")
    add_signed_lab_arguments(parser)
    return parser.parse_args(args)


def _evidence() -> tuple[str, ...]:
    return (
        "--lab-venv",
        "C:/lab",
        "--wheel",
        "C:/wheel.whl",
        "--trust-policy",
        "C:/trust.json",
        "--trust-sha256",
        "a" * 64,
        "--registry",
        "C:/registry.json",
        "--module",
        "C:/module.json",
    )


def test_original_launch_unchanged_without_flags() -> None:
    historical = Mock(return_value=39)
    assert dispatch_launch(_parse("quillan"), historical_launch=historical) == 39
    historical.assert_called_once_with("quillan")


def test_reject_native_file_without_mode() -> None:
    historical = Mock(return_value=0)
    args = _parse("quillan", "--native-envelope", "C:/native.json")
    assert dispatch_launch(args, historical_launch=historical) == 2
    historical.assert_not_called()


def test_reject_native_mode_without_envelope() -> None:
    historical = Mock(return_value=0)
    args = _parse("quillan", "--signed-lab-native-help", *_evidence())
    assert dispatch_launch(args, historical_launch=historical) == 2
    historical.assert_not_called()


def test_reject_other_component_for_native_mode() -> None:
    historical = Mock(return_value=0)
    args = _parse(
        "scoreform",
        "--signed-lab-native-help",
        *_evidence(),
        "--native-envelope",
        "C:/native.json",
    )
    assert dispatch_launch(args, historical_launch=historical) == 2
    historical.assert_not_called()


def test_reject_native_envelope_in_old_lab_mode() -> None:
    historical = Mock(return_value=0)
    args = _parse(
        "quillan",
        "--signed-lab-help",
        *_evidence(),
        "--native-envelope",
        "C:/native.json",
    )
    assert dispatch_launch(args, historical_launch=historical) == 2
    historical.assert_not_called()


def test_new_mode_propagates_envelope_and_no_arbitrary_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import evergreen_signed_lab_launch

    calls: list[list[str]] = []

    def fake_main(argv: list[str]) -> int:
        calls.append(argv)
        return 17

    monkeypatch.setattr(evergreen_signed_lab_launch, "main", fake_main)
    historical = Mock(return_value=0)
    args = _parse(
        "quillan",
        "--signed-lab-native-help",
        *_evidence(),
        "--native-envelope",
        "C:/native.json",
    )
    assert dispatch_launch(args, historical_launch=historical) == 17
    historical.assert_not_called()
    assert calls[0][-3:] == [
        "--native-envelope",
        str(Path("C:/native.json")),
        "--native-execute-help",
    ]
    assert "menu" not in calls[0]


def test_native_and_legacy_help_options_conflict() -> None:
    with pytest.raises(SystemExit) as error:
        _parse(
            "quillan",
            "--signed-lab-native-help",
            "--signed-lab-help",
            *_evidence(),
            "--native-envelope",
            "C:/native.json",
        )
    assert error.value.code == 2
