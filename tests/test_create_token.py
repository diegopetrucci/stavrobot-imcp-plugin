from __future__ import annotations

import os
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create_token.sh"
TOKEN_NAME = "imcp-bridge.token"


def run_helper(home: Path) -> subprocess.CompletedProcess[str]:
    environment = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
    }
    return subprocess.run(
        [str(SCRIPT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def token_path(home: Path) -> Path:
    return home / ".config" / TOKEN_NAME


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def test_creation_uses_private_config_and_token_modes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = run_helper(home)

    assert result.returncode == 0
    config = home / ".config"
    token = token_path(home)
    assert config.is_dir() and not config.is_symlink()
    assert stat.S_IMODE(config.stat().st_mode) == 0o700
    assert token.is_file() and not token.is_symlink()
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    value = token.read_text(encoding="utf-8")
    assert value and not any(character.isspace() for character in value)
    assert value not in combined_output(result)


def test_rerun_preserves_token_and_repairs_mode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    first = run_helper(home)
    token = token_path(home)
    original = token.read_bytes()
    token.chmod(0o644)

    second = run_helper(home)

    assert first.returncode == 0
    assert second.returncode == 0
    assert token.read_bytes() == original
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert original.decode("utf-8") not in combined_output(second)


@pytest.mark.parametrize("kind", ["symlink", "directory", "empty", "whitespace"])
def test_rejects_unsafe_or_invalid_existing_token(kind: str, tmp_path: Path) -> None:
    home = tmp_path / "home"
    config = home / ".config"
    home.mkdir()
    config.mkdir(mode=0o700)
    token = config / TOKEN_NAME
    marker = "existing-token-for-test"

    if kind == "symlink":
        replacement = tmp_path / "replacement-token"
        replacement.write_text(marker, encoding="utf-8")
        token.symlink_to(replacement)
        before = replacement.read_bytes()
    elif kind == "directory":
        token.mkdir()
        before = None
    elif kind == "empty":
        token.write_bytes(b"")
        token.chmod(0o644)
        before = token.read_bytes()
    else:
        token.write_bytes(b"invalid token")
        token.chmod(0o644)
        before = token.read_bytes()

    result = run_helper(home)

    assert result.returncode != 0
    assert "could not create protected bridge token" in result.stderr
    assert marker not in combined_output(result)
    if kind == "symlink":
        assert token.is_symlink()
        assert replacement.read_bytes() == before
    elif kind == "directory":
        assert token.is_dir()
    else:
        assert token.read_bytes() == before
        assert stat.S_IMODE(token.stat().st_mode) == 0o644


def test_rejects_symlink_config_without_touching_target(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    real_config = tmp_path / "real-config"
    real_config.mkdir(mode=0o700)
    replacement = real_config / TOKEN_NAME
    marker = b"existing-token-for-test"
    replacement.write_bytes(marker)
    replacement.chmod(0o644)
    (home / ".config").symlink_to(real_config, target_is_directory=True)

    result = run_helper(home)

    assert result.returncode != 0
    assert replacement.read_bytes() == marker
    assert stat.S_IMODE(replacement.stat().st_mode) == 0o644
    assert marker.decode("ascii") not in combined_output(result)


def test_concurrent_creation_keeps_one_token(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(run_helper, [home] * 4))

    assert all(result.returncode == 0 for result in results)
    token = token_path(home)
    value = token.read_text(encoding="utf-8")
    assert value and not any(character.isspace() for character in value)
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert all(value not in combined_output(result) for result in results)
