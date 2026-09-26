#!/bin/sh
set -eu

exec python3 - <<'PY'
import os
import secrets
import stat
import sys
import tempfile
from pathlib import Path

TOKEN_MODE = 0o600
CONFIG_MODE = 0o700
TOKEN_NAME = "imcp-bridge.token"
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def fail_if_unsafe_token(path: Path) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise OSError("unsafe token path")


def validate_existing_token(path: Path) -> None:
    fail_if_unsafe_token(path)
    fd = os.open(path, os.O_RDONLY | NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("unsafe token path")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            value = stream.read().decode("utf-8")
        token = value.strip()
        if not token or any(character.isspace() for character in token):
            raise ValueError("invalid token")
        os.fchmod(fd, TOKEN_MODE)
    finally:
        os.close(fd)


def ensure_config(home: Path) -> Path:
    if not home.is_absolute():
        raise OSError("unsafe home path")
    config = home / ".config"
    try:
        info = os.lstat(config)
    except FileNotFoundError:
        try:
            os.mkdir(config, CONFIG_MODE)
        except FileExistsError:
            pass
        info = os.lstat(config)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise OSError("unsafe config path")
    return config


def create_token(config: Path, path: Path) -> None:
    temp_fd, temp_name = tempfile.mkstemp(prefix=f".{TOKEN_NAME}.", dir=config)
    try:
        os.fchmod(temp_fd, TOKEN_MODE)
        token = secrets.token_urlsafe(32).encode("ascii")
        view = memoryview(token)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("token write failed")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1
        try:
            os.link(temp_name, path)
        except FileExistsError:
            validate_existing_token(path)
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def main() -> int:
    home_value = os.environ.get("HOME")
    if not home_value:
        raise OSError("HOME is unavailable")
    config = ensure_config(Path(home_value))
    token_path = config / TOKEN_NAME
    fail_if_unsafe_token(token_path)
    try:
        validate_existing_token(token_path)
    except FileNotFoundError:
        create_token(config, token_path)
    print("bridge token is ready")
    return 0


try:
    status = main()
except BaseException:
    print("could not create protected bridge token", file=sys.stderr)
    status = 1
raise SystemExit(status)
PY
