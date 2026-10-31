"""Slice 102: the real Suite launch CLI delegates only opt-in disposable lab.

All fake signers / observations are process-free. Actual signed-wheel execution
was validated separately in Slice 101 and is exercised by Windows acceptance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import paper_data_suite.cli as cli
from paper_data_suite.evergreen_signed_lab_cli import dispatch_launch

FIELDS = (
    "--lab-venv",
    "X:/Labs/historical_suite_010_quillan_0106_FULL_DEPS_LAB",
    "--wheel",
    "X:/Artifacts/quillan-0.10.6-py3-none-any.whl",
    "--trust-policy",
    "X:/Evidence/trust-policy.json",
    "--trust-sha256",
    "a" * 64,
    "--registry",
    "X:/Evidence/registry-envelope.json",
    "--module",
    "X:/Evidence/quillan-envelope.json",
)


def test_parser_keeps_legacy_default_without_laboratory_flags() -> None:
    namespace = cli.build_parser().parse_args(["launch", "quillan"])
    assert namespace.component_id == "quillan"
    assert not namespace.signed_lab_help
    assert not namespace.signed_lab_check
    assert namespace.lab_venv is None


def test_normal_launch_still_uses_historical_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def original(component_id: str) -> int:
        seen.append(component_id)
        return 47

    monkeypatch.setattr(cli, "_run_launch", original)
    assert cli.main(("launch", "quillan")) == 47
    assert seen == ["quillan"]


@pytest.mark.parametrize("mode", ("--signed-lab-check", "--signed-lab-help"))
def test_explicit_mode_delegates_exact_arguments_without_legacy(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import paper_data_suite.evergreen_signed_lab_launch as lab

    seen: list[list[str]] = []
    monkeypatch.setattr(lab, "main", lambda args: seen.append(args) or 0)
    monkeypatch.setattr(
        cli, "_run_launch", lambda _: pytest.fail("historical path invoked")
    )
    assert cli.main(("launch", "quillan", mode, *FIELDS)) == 0
    assert len(seen) == 1
    expected = list(FIELDS)
    for index in (1, 3, 5, 9, 11):
        expected[index] = str(Path(expected[index]))
    assert seen[0][: len(FIELDS)] == expected
    assert seen[0][len(FIELDS) :] == (["--execute-help"] if "help" in mode else [])


@pytest.mark.parametrize(
    "suffix",
    (
        ("--wheel", "X:/fake.whl"),
        ("--signed-lab-help",),
        ("--signed-lab-check",),
        ("--signed-lab-help", *FIELDS[:-2]),
        ("--signed-lab-check", *FIELDS[:-2]),
        ("--signed-lab-check", *FIELDS, "--trust-sha256", ""),
    ),
)
def test_missing_or_partial_evidence_does_not_fall_back(
    suffix: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    import paper_data_suite.evergreen_signed_lab_launch as lab

    monkeypatch.setattr(
        lab, "main", lambda _: pytest.fail("lab executed with incomplete evidence")
    )
    monkeypatch.setattr(
        cli, "_run_launch", lambda _: pytest.fail("historical path invoked")
    )
    assert cli.main(("launch", "quillan", *suffix)) == 2


def test_other_components_cannot_take_signed_lab_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.evergreen_signed_lab_launch as lab

    monkeypatch.setattr(lab, "main", lambda _: pytest.fail("wrong component"))
    monkeypatch.setattr(cli, "_run_launch", lambda _: pytest.fail("wrong fallback"))
    assert cli.main(("launch", "scoreform", "--signed-lab-help", *FIELDS)) == 2


def test_conflicting_modes_refused_by_argparse() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(("launch", "quillan", "--signed-lab-check", "--signed-lab-help"))
    assert exc.value.code == 2


def test_arbitrary_child_arguments_are_not_accepted() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(("launch", "quillan", "--signed-lab-help", *FIELDS, "--menu"))
    assert exc.value.code == 2


def test_explicit_lab_inspection_return_code_propagated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.evergreen_signed_lab_launch as lab

    monkeypatch.setattr(lab, "main", lambda _: 1)
    monkeypatch.setattr(cli, "_run_launch", lambda _: pytest.fail("fallback"))
    assert cli.main(("launch", "quillan", "--signed-lab-check", *FIELDS)) == 1


def test_lab_evidence_is_typed_as_paths_in_parser() -> None:
    namespace = cli.build_parser().parse_args(
        ["launch", "quillan", "--signed-lab-check", *FIELDS]
    )
    assert isinstance(namespace.lab_venv, Path)
    assert isinstance(namespace.registry, Path)
    assert namespace.trust_sha256 == "a" * 64


def test_helper_no_optin_cannot_elevate_anything() -> None:
    arguments = cli.build_parser().parse_args(["launch", "quillan"])
    assert dispatch_launch(arguments, historical_launch=lambda _: 17) == 17
