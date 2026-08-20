from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

TRACKED_MODULES = (
    "pds_core",
    "scoreform",
    "quillan",
    "concord",
    "meridian",
    "vitrine",
)


@pytest.mark.parametrize(
    "module_name",
    [
        "paper_data_suite.classroom_setup",
        "paper_data_suite.classroom_planning",
        "paper_data_suite.classroom_apply",
        "paper_data_suite.classroom_setup_cli",
    ],
)
def test_classroom_setup_imports_are_side_effect_free(
    tmp_path: Path,
    module_name: str,
) -> None:
    code = f"""
import importlib
import json
import sys

importlib.import_module({module_name!r})
tracked = {TRACKED_MODULES!r}
print(json.dumps({{name: name in sys.modules for name in tracked}}))
""".strip()

    before = tuple(tmp_path.iterdir())
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert tuple(tmp_path.iterdir()) == before

    loaded = cast(dict[str, bool], json.loads(result.stdout))
    assert loaded == {name: False for name in TRACKED_MODULES}
