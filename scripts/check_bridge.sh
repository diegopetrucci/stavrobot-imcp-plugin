#!/bin/sh
set -eu

exec python3 - <<'PY'
import json
import os
import sys
from http import HTTPStatus, client
from pathlib import Path


BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8766
BRIDGE_PATH = "/bridge"
CLIENT_SOCKET_TIMEOUT = 20
# Keep this synchronized with bridge.server.MAX_RESPONSE_BYTES.  Read one
# extra byte so an oversized response is rejected without an unbounded read.
MAX_RESPONSE_BYTES = 256 * 1024
TOKEN_NAME = "imcp-bridge.token"
REQUEST_BODY = json.dumps(
    {"operation": "list_tools"}, separators=(",", ":")
).encode("utf-8")


MANUAL_GUIDANCE = (
    "Watch iMCP while this request runs; if it shows a client approval prompt, "
    "approve it. This command sends one read-only list_tools request, never "
    "calls an iMCP tool, and does not retry automatically."
)
FAILURE_MESSAGE = (
    "bridge list_tools request failed; resolve approval/configuration, then "
    "retry only this read-only listing"
)
SUCCESS_MESSAGE = "bridge list_tools request completed successfully"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _read_token() -> str:
    home = os.environ.get("HOME")
    if not home:
        raise ValueError("HOME is unavailable")
    try:
        token = (Path(home) / ".config" / TOKEN_NAME).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError("bridge token is unavailable") from exc
    if not token or any(character.isspace() for character in token):
        raise ValueError("bridge token is invalid")
    return token


def _is_valid_list_tools_response(status: int, body: bytes) -> bool:
    if status != HTTPStatus.OK or len(body) > MAX_RESPONSE_BYTES:
        return False
    try:
        payload = json.loads(
            body.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is not True or payload.get("truncated") is not False:
        return False
    result = payload.get("result")
    return isinstance(result, dict) and isinstance(result.get("tools"), list)


def _failure() -> int:
    print(FAILURE_MESSAGE, file=sys.stderr)
    return 1


def main() -> int:
    # Print this before the network operation, which may wait for a human
    # approval prompt or the bounded client timeout.
    print(MANUAL_GUIDANCE, flush=True)
    connection = None
    try:
        token = _read_token()
        connection = client.HTTPConnection(
            BRIDGE_HOST,
            BRIDGE_PORT,
            timeout=CLIENT_SOCKET_TIMEOUT,
        )
        connection.request(
            "POST",
            BRIDGE_PATH,
            body=REQUEST_BODY,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        response_body = response.read(MAX_RESPONSE_BYTES + 1)
        if not isinstance(response_body, bytes):
            return _failure()
        if not _is_valid_list_tools_response(response.status, response_body):
            return _failure()
    except Exception:
        # Do not expose transport errors, token values, response bodies, or
        # metadata.  The operator can safely retry only this read-only listing.
        return _failure()
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    print(SUCCESS_MESSAGE)
    return 0


raise SystemExit(main())
PY
