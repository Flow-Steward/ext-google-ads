#!/usr/bin/env python3
"""Bounded JSON subprocess entrypoint; no tokens or tracebacks on stderr."""

from __future__ import annotations
import json
import sys
from google_ads.context import WRITES
from google_ads.errors import AdsError
from google_ads.runtime import dispatch

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 9 * 512 * 1024


def bounded_response(
    response: dict, *, write: bool = False, limit: int = MAX_OUTPUT_BYTES
) -> bytes:
    try:
        encoded = json.dumps(
            response, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) + 1 <= limit:
            return encoded + b"\n"
    except (ValueError, TypeError, UnicodeError):
        pass
    error = AdsError(
        "outcome_unknown" if write else "validation_failed",
        "The write result requires reconciliation; do not retry."
        if write
        else "The result is too large; narrow the request.",
        unknown=write,
    ).envelope()
    return json.dumps(error, separators=(",", ":")).encode() + b"\n"


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    payload = {}
    if len(raw) > MAX_INPUT_BYTES:
        response = AdsError(
            "invalid_payload", "The request exceeds the safe input limit."
        ).envelope()
    else:
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
        except (UnicodeError, ValueError):
            payload = {}
            response = AdsError(
                "invalid_payload", "The request must be a UTF-8 JSON object."
            ).envelope()
        else:
            response = dispatch(payload)
    action = payload.get("action", {})
    operation = action.get("action_id") if isinstance(action, dict) else None
    write = isinstance(operation, str) and operation in WRITES and response.get("ok") is True
    encoded = bounded_response(response, write=write)
    sys.stdout.buffer.write(encoded)
    return 0 if json.loads(encoded).get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
