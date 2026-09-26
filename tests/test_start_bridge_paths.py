from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/start-stavrobot-imcp-bridge"


def test_tmux_helper_uses_canonical_plugin_checkout():
    source = HELPER.read_text(encoding="utf-8")
    match = re.search(r'^repo_root="([^"]+)"$', source, flags=re.MULTILINE)

    assert match is not None
    assert match.group(1) == "$HOME/Developer/stavrobot-imcp-plugin"
    assert 'bridge="$repo_root/bridge/server.py"' in source
    assert 'python_bin="$repo_root/.venv/bin/python"' in source
