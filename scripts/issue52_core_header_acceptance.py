"""Issue #52: isolated Core source-header and published-v0.6.6 fallback witness.

This script never installs a wheel, changes the Core checkout or writes teacher
settings. A pinned *archive* of Core source is built into a disposable developer
wheel; the independently supplied official wheel is verified before use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any

CORE_SOURCE_SHA = "a0d5e1a50580bbe025f0cad23c7e8524203a52ec"
OFFICIAL_VERSION = "0.6.6"
OFFICIAL_SHA256 = (
    "d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301"
)


class CoreAcceptanceError(RuntimeError):
    """Bounded, non-sensitive qualification failure."""


def sha256_file(path: Path) -> str:
    """Hash the actual on-disk artifact, never a version string."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_wheel(path: Path, *, required_sha256: str | None = None) -> str:
    """Check wheel archive identity and, for official Core, exact SHA-256."""
    if not path.is_file() or path.suffix != ".whl":
        raise CoreAcceptanceError("Core wheel file is missing or invalid")
    digest = sha256_file(path)
    if required_sha256 is not None and digest != required_sha256:
        raise CoreAcceptanceError("Official Core wheel SHA-256 does not match")
    try:
        with zipfile.ZipFile(path) as archive:
            metadata = [
                name for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata) != 1:
                raise CoreAcceptanceError("Core wheel metadata is ambiguous")
            message = Parser().parsestr(
                archive.read(metadata[0]).decode("utf-8")
            )
            if (
                (message.get("Name") or "").lower().replace("_", "-")
                != "pds-core"
                or message.get("Version") != OFFICIAL_VERSION
                or "pds_core/__init__.py" not in archive.namelist()
            ):
                raise CoreAcceptanceError("Unexpected Core wheel identity")
    except (OSError, zipfile.BadZipFile, UnicodeError) as error:
        raise CoreAcceptanceError("Core wheel cannot be inspected") from error
    return digest


def _safe_error_summary(*streams: str) -> str:
    """Retain actionable failure categories, but never echo local paths/logs.

    A witness failure is not useful if it only names ``python.exe``. Select a
    bounded set of recognized diagnostic lines, excluding traceback frames and
    paths. Do not expose arbitrary pip output in stored evidence or stdout.
    """
    markers = (
        "modulenotfounderror:", "backendunavailable", "cannot import",
        "metadata-generation-failed", "invalid command", "multiple top-level",
        "package discovery", "permission denied", "failed building wheel",
        "error:", "importerror:", "attributeerror:", "typeerror:",
        "coreacceptanceerror:", "subprocess-exited-with-error",
    )
    selected: list[str] = []
    for stream in streams:
        for raw in stream.splitlines():
            line = raw.strip()
            if not line or len(line) > 240 or not any(
                marker in line.casefold() for marker in markers
            ):
                continue
            # Do not include absolute paths, hyperlinks, or traceback locations.
            if (
                "\\" in line or "http:" in line or "https:" in line
                or re.search(r"(?i)(?:[a-z]:[/\\]|/(?:home|users|tmp|mnt|var)/)", line)
            ):
                continue
            if line not in selected:
                selected.append(line)
    return " | ".join(selected[-3:])[:450]


def _execute(
    command: list[str], *, cwd: Path | None = None, phase: str = "external"
) -> str:
    """Run a bounded command and report the *phase*, not its private paths."""
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        hint = _safe_error_summary(result.stderr, result.stdout)
        suffix = f"; diagnostic: {hint}" if hint else ""
        raise CoreAcceptanceError(
            f"{phase} failed (status {result.returncode}){suffix}"
        )
    return result.stdout



def require_local_build_backend() -> str:
    """Ensure offline, no-build-isolation pip has a usable local backend.

    ``venv`` on Python 3.12+ need not contain setuptools. Merely having pip
    and Ruff installed is no guarantee. A missing backend must be reported
    before exporting or attempting to modify any source/repository.
    """
    from importlib import import_module
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("setuptools")
    except PackageNotFoundError as error:
        raise CoreAcceptanceError(
            "Offline developer-wheel build requires setuptools>=77 in the "
            "invoking development interpreter; setuptools is not installed. "
            "No package was installed by this witness."
        ) from error
    try:
        major = int(installed.split(".", maxsplit=1)[0])
    except ValueError as error:
        raise CoreAcceptanceError(
            "Unable to interpret local setuptools version for offline build"
        ) from error
    if major < 77:
        raise CoreAcceptanceError(
            "Offline developer-wheel build requires setuptools>=77 in the "
            f"invoking development interpreter; installed major is {major}. "
            "No package was installed by this witness."
        )
    try:
        import_module("setuptools.build_meta")
    except (ImportError, AttributeError) as error:
        raise CoreAcceptanceError(
            "Offline developer-wheel build backend setuptools.build_meta "
            "is unavailable in the invoking development interpreter. "
            "No package was installed by this witness."
        ) from error
    return installed

def pinned_core_archive(core_repo: Path, destination: Path) -> None:
    """Export exactly the public source commit, independent of working tree."""
    if not (core_repo / ".git").exists():
        # Worktrees may use a .git file; both are valid.
        raise CoreAcceptanceError("Core source must be a local Git checkout")
    commit = _execute(
        ["git", "-C", str(core_repo), "rev-parse", f"{CORE_SOURCE_SHA}^{{commit}}"]
    ).strip()
    if commit != CORE_SOURCE_SHA:
        raise CoreAcceptanceError("Pinned Core source commit is not available")
    # Explicitly disable checkout-style CRLF conversion for the archive.
    # With core.autocrlf=true, Git otherwise exports CRLF even when the
    # committed blob is LF, making the pinned artifact host-dependent.
    _execute(
        [
            "git", "-c", "core.autocrlf=false", "-C", str(core_repo),
            "archive", "--format=zip", "--output", str(destination),
            CORE_SOURCE_SHA,
        ], phase="pinned-git-archive"
    )
    if not destination.is_file():
        raise CoreAcceptanceError("Pinned Core archive was not created")


def build_developer_wheel(core_repo: Path, target: Path) -> Path:
    """Build a disposable wheel without installing it into either environment."""
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pds52_core_source_") as directory:
        workspace = Path(directory)
        archive_path = workspace / "core-pinned.zip"
        source = workspace / "source"
        source.mkdir()
        pinned_core_archive(core_repo, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                parts = Path(name.replace("\\", "/")).parts
                if (
                    not parts or ".." in parts or name.startswith(("/", "\\"))
                    or ":" in parts[0]
                ):
                    raise CoreAcceptanceError("Core archive contains an unsafe path")
            archive.extractall(source)
        _execute(
            [
                sys.executable, "-m", "pip", "wheel", "--no-deps",
                "--no-build-isolation", "--no-index", "--wheel-dir",
                str(target), str(source),
            ], phase="developer-wheel-build"
        )
    wheels = tuple(target.glob("pds_core-*.whl"))
    if len(wheels) != 1:
        raise CoreAcceptanceError("Expected exactly one Core developer wheel")
    verify_wheel(wheels[0])
    return wheels[0]


def isolated_probe(wheel: Path, *, kind: str, suite_root: Path) -> dict[str, Any]:
    """Exercise the real Suite consumer using a selected Core wheel."""
    result = subprocess.run(
        [
            sys.executable, "-I", "-B", str(Path(__file__).resolve()),
            "--isolated-probe", str(wheel.resolve()), kind,
            str(suite_root.resolve()),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        hint = _safe_error_summary(result.stderr, result.stdout)
        suffix = f"; diagnostic: {hint}" if hint else ""
        raise CoreAcceptanceError(
            f"Isolated {kind} Core consumer probe failed "
            f"(status {result.returncode}){suffix}"
        )
    try:
        parsed = json.loads(result.stdout)
    except (ValueError, TypeError) as error:
        raise CoreAcceptanceError("Isolated probe did not return JSON") from error
    if not isinstance(parsed, dict) or parsed.get("kind") != kind:
        raise CoreAcceptanceError("Isolated probe returned unexpected evidence")
    return parsed


def _child_probe(wheel: Path, kind: str, suite_root: Path) -> int:
    """The only mode allowed to import either Core wheel into this interpreter."""
    if kind not in ("developer", "official"):
        raise CoreAcceptanceError("Unknown isolated probe kind")
    sys.path.insert(0, str(suite_root))
    sys.path.insert(0, str(wheel))

    from importlib import import_module
    from io import StringIO

    import pds_core

    from paper_data_suite.applications import ApplicationInventory
    from paper_data_suite.teacher_experience_contracts import (
        observe_core_teacher_contract,
    )
    from paper_data_suite.teacher_home import run_teacher_home

    origin = str(pds_core.__file__ or "")
    if not os.path.normcase(origin).startswith(
        os.path.normcase(str(wheel) + os.sep)
    ):
        raise CoreAcceptanceError("Probe imported Core outside selected wheel")

    observed = observe_core_teacher_contract()
    required = kind == "developer"
    if observed.contract_present != required or observed.header_available != required:
        raise CoreAcceptanceError("Core header capability did not match artifact")
    if observed.notes_recognizer_available != required:
        raise CoreAcceptanceError("Core shared-command capability did not match")
    calls: list[str] = []
    if required:
        ui = import_module("pds_core.teacher_ui")
        header = ui.TeacherScreenHeader("Paper Data Suite", "Teacher Home")
        if ui.render_teacher_header(header) != "Paper Data Suite\nTeacher Home":
            raise CoreAcceptanceError("Core pure header vector failed")
        if ui.render_teacher_header(header, ansi=True) != (
            "\x1b[32mPaper Data Suite\x1b[0m\nTeacher Home"
        ):
            raise CoreAcceptanceError("Core explicit green render vector failed")
        try:
            ui.TeacherScreenHeader("Paper Data Suite\x1b[0m", "Teacher Home")
        except ValueError:
            pass
        else:
            raise CoreAcceptanceError("Core header accepted terminal control input")
        original = ui.print_teacher_header

        def instrumented(header: Any, *, output: Any, color: str = "auto") -> None:
            calls.append(color)
            original(header, output=output, color=color)

        # Dynamic instrumentation only: the released Core stub lacks this attribute.
        setattr(ui, "print_teacher_header", instrumented)
        commands = import_module("pds_core.teacher_commands")
        parse = commands.parse_shared_teacher_command
        kind_type = commands.PromptKind
        if parse(
            " :NoTeS ", prompt_kind=kind_type.MENU_CHOICE,
            interactive=True, allow_notes=True,
        ) is not commands.SharedTeacherCommand.NOTES:
            raise CoreAcceptanceError("Core shared parser positive vector failed")
        for invalid in ("N", "W", "B", "M", "Q", ":notes more"):
            if parse(
                invalid, prompt_kind=kind_type.MENU_CHOICE,
                interactive=True, allow_notes=True,
            ) is not None:
                raise CoreAcceptanceError("Core parser intercepted local command")
    else:
        # A published 0.6.6 wheel must not be mislabeled as having v1 APIs.
        from importlib.util import find_spec

        if find_spec("pds_core.teacher_experience") is not None:
            raise CoreAcceptanceError("Published legacy Core unexpectedly has v1 API")

    previous_no_color = os.environ.get("NO_COLOR")
    os.environ["NO_COLOR"] = "1"
    try:
        output = StringIO()
        result = run_teacher_home(
            input_stream=StringIO("q\n"),
            output=output,
            collect_inventory=lambda: ApplicationInventory(()),
            launch=lambda _id: (_ for _ in ()).throw(
                AssertionError("home unexpectedly launched application")
            ),
            doctor=lambda: (_ for _ in ()).throw(
                AssertionError("home unexpectedly ran doctor")
            ),
            show_help=lambda: (_ for _ in ()).throw(
                AssertionError("home unexpectedly displayed help")
            ),
            recent=lambda: (),
        )
        actual = output.getvalue()
    finally:
        if previous_no_color is None:
            os.environ.pop("NO_COLOR", None)
        else:
            os.environ["NO_COLOR"] = previous_no_color
    if result != 0 or not actual.startswith("Paper Data Suite\nTeacher Home\n"):
        raise CoreAcceptanceError("Suite teacher home did not render expected header")
    if "\x1b" in actual or "Leaving Paper Data Suite." not in actual:
        raise CoreAcceptanceError("Suite teacher home ANSI/exit fallback invalid")
    if required and calls != ["auto"]:
        raise CoreAcceptanceError("Suite did not call Core's v1 header printer")
    if not required and calls:
        raise CoreAcceptanceError("Suite used an unavailable Core header")
    if "teacher-header interface is incompatible" in actual:
        raise CoreAcceptanceError("Core contract was unexpectedly incompatible")
    print(json.dumps({
        "kind": kind, "header_available": observed.header_available,
        "notes_recognizer_available": observed.notes_recognizer_available,
        "suite_header_printer_called": bool(calls),
        "plain_text_terminal_fallback": True,
        "teacher_home_exit": result,
    }, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--isolated-probe"]:
        if len(arguments) != 4:
            raise CoreAcceptanceError("Isolated probe argument count invalid")
        return _child_probe(Path(arguments[1]), arguments[2], Path(arguments[3]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-repo", type=Path, required=True)
    parser.add_argument("--official-core-wheel", type=Path, required=True)
    parser.add_argument("--suite-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(arguments)

    verify_wheel(args.official_core_wheel, required_sha256=OFFICIAL_SHA256)
    if not (args.suite_root / "paper_data_suite" / "teacher_home.py").is_file():
        raise CoreAcceptanceError("Suite source root is not available")
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="issue52_core_", dir=output_root
    ) as scratch:
        work = Path(scratch)
        build_backend = require_local_build_backend()
        developer_wheel = build_developer_wheel(args.core_repo, work / "dev")
        developer_sha = verify_wheel(developer_wheel)
        developer = isolated_probe(
            developer_wheel, kind="developer", suite_root=args.suite_root,
        )
        official = isolated_probe(
            args.official_core_wheel, kind="official", suite_root=args.suite_root,
        )
        # Durable evidence; no developer wheel placed alongside released wheels.
        dev_destination = (
            output_root / "developer_only_DO_NOT_INSTALL" / developer_sha[:12]
        )
        dev_destination.mkdir(parents=True, exist_ok=True)
        dev_copy = dev_destination / developer_wheel.name
        if dev_copy.exists() and sha256_file(dev_copy) != developer_sha:
            raise CoreAcceptanceError("Developer wheel destination already differs")
        if not dev_copy.exists():
            dev_copy.write_bytes(developer_wheel.read_bytes())
        record = {
            "issue": 52,
            "track_A": "developer source integration; NOT official release",
            "core_source_sha": CORE_SOURCE_SHA,
            "core_dev_wheel_sha256": developer_sha,
            "core_dev_wheel_name": developer_wheel.name,
            "developer_probe": developer,
            "track_B_legacy": "published v0.6.6 fallback accepted; NOT v1 release",
            "official_core_version": OFFICIAL_VERSION,
            "official_core_wheel_sha256": OFFICIAL_SHA256,
            "official_probe": official,
            "official_v1_header_qualification": "PENDING newer published wheel",
            "python_version": sys.version,
            "platform": platform.platform(),
            "developer_build_backend": f"setuptools {build_backend}",
        }
        # Do not include private filesystem paths or student records in evidence.
        (output_root / "issue52_core_header_evidence.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"SUITE52_S3_CORE_SOURCE_SHA: {CORE_SOURCE_SHA}")
    print(f"SUITE52_S3_DEVELOPER_WHEEL_SHA256: {developer_sha}")
    print(f"SUITE52_S3_OFFICIAL_0_6_6_SHA256: {OFFICIAL_SHA256}")
    print("SUITE52_S3_DEV_HEADER_AND_PARSER_ACCEPTED")
    print("SUITE52_S3_OFFICIAL_LEGACY_FALLBACK_ACCEPTED")
    print("SUITE52_S3_OFFICIAL_V1_HEADER_RELEASE_PENDING")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CoreAcceptanceError, OSError, zipfile.BadZipFile) as error:
        print(f"SUITE52_S3_ACCEPTANCE_FAILED: {error}", file=sys.stderr)
        sys.exit(1)
