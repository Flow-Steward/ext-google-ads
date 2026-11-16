"""The subprocess always emits a bounded JSON error instead of a traceback."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def invoke(data):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "main.py")],
        input=data,
        capture_output=True,
        timeout=10,
        cwd=ROOT,
    )
    assert completed.stderr == b""
    return completed, json.loads(completed.stdout)


def test_invalid_utf8_has_structured_error():
    process, response = invoke(b"\xff")
    assert process.returncode == 2
    assert response["error_code"] == "invalid_payload"


def test_oversized_json_refused_before_host_context():
    process, response = invoke(json.dumps({"padding": "x" * (2 * 1024 * 1024)}).encode())
    assert process.returncode == 2
    assert response["error_code"] == "invalid_payload"


def test_output_overflow_never_claims_no_write_effect():
    from main import bounded_response

    response = {"ok": True, "result": {"payload": "x" * 1000}}
    encoded = bounded_response(response, write=True, limit=512)
    assert len(encoded) <= 512
    value = json.loads(encoded)
    assert value["error_code"] == "outcome_unknown"
    assert value["definitely_no_external_effect"] is False
    assert value["retryable"] is False
