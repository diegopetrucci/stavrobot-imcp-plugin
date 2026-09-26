from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "DEPLOY.md"


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is not installed")
def test_documented_rsync_preserves_plugin_tool_directories(tmp_path: Path) -> None:
    """Exercise the documented copy in isolation so tool dirs cannot flatten."""

    source_home = tmp_path / "home"
    source = source_home / "Developer" / "stavrobot-imcp-plugin"
    destination_root = tmp_path / "stavrobot"
    destination = destination_root / "data" / "plugins" / "imcp"

    files = {
        "manifest.json": "manifest",
        "_bridge.py": "bridge",
        "config.json.example": "example",
        "imcp_call/manifest.json": "call manifest",
        "imcp_call/run.py": "call runner",
        "imcp_call/config.json": "ignored config",
        "imcp_list_tools/manifest.json": "list manifest",
        "imcp_list_tools/run.py": "list runner",
        "imcp_call/__pycache__/ignored.pyc": "ignored cache",
        "imcp_list_tools/ignored.pyc": "ignored bytecode",
        ".DS_Store": "ignored metadata",
    }
    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    destination.mkdir(parents=True)
    (destination / "config.json").write_text("existing config", encoding="utf-8")

    document = DEPLOY.read_text(encoding="utf-8")
    start = document.index('STAVROBOT_ROOT="/path/to/stavrobot"')
    end = document.index("\n```", start)
    command = document[start:end]
    command = command.replace(
        'STAVROBOT_ROOT="/path/to/stavrobot"',
        f"STAVROBOT_ROOT={shlex.quote(str(destination_root))}",
        1,
    )

    environment = os.environ.copy()
    environment["HOME"] = str(source_home)
    subprocess.run(
        ["sh", "-c", command],
        check=True,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert (destination / "manifest.json").is_file()
    assert (destination / "_bridge.py").is_file()
    assert (destination / "config.json.example").is_file()
    assert (destination / "imcp_call" / "manifest.json").is_file()
    assert (destination / "imcp_call" / "run.py").is_file()
    assert (destination / "imcp_list_tools" / "manifest.json").is_file()
    assert (destination / "imcp_list_tools" / "run.py").is_file()
    assert not (destination / "run.py").exists()
    assert (destination / "manifest.json").read_text(encoding="utf-8") == "manifest"
    assert (destination / "config.json").stat().st_size == len("existing config")
    assert not (destination / "imcp_call" / "config.json").exists()
    assert not (destination / "imcp_call" / "__pycache__").exists()
    assert not (destination / "imcp_list_tools" / "ignored.pyc").exists()
    assert not (destination / ".DS_Store").exists()
