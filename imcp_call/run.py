#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///

from __future__ import annotations

import json
import sys
from pathlib import Path

# The plugin runner starts tools from their own directory.  Keep the shared
# client at the bundle root without relying on PYTHONPATH being set.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _bridge


def _local_error(code: str, message: str) -> int:
    try:
        _bridge.write_json(_bridge.error_payload(code, message))
    except Exception:
        # Never print an exception: diagnostics could include configuration.
        return 1
    return 1


def main() -> int:
    try:
        params = json.load(sys.stdin)
    except Exception:
        return _local_error("invalid_input", "tool input must be a JSON object")

    if not isinstance(params, dict):
        return _local_error("invalid_input", "tool input must be a JSON object")
    if any(key not in {"name", "arguments"} for key in params):
        return _local_error("invalid_input", "unknown parameter")
    if "name" not in params:
        return _local_error("invalid_input", "name is required")

    name = params["name"]
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not name:
        return _local_error("invalid_input", "name must be a non-empty string")
    if not isinstance(arguments, dict):
        return _local_error("invalid_input", "arguments must be a JSON object")

    try:
        _bridge.write_json(
            _bridge.request_bridge(
                {
                    "operation": "call_tool",
                    "name": name,
                    "arguments": arguments,
                }
            )
        )
    except Exception:
        return _local_error("bridge_unavailable", "bridge request failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
