#!/usr/bin/env python3
"""flowsteward.google-ads extension health check."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module_loadable(path: Path, module_name: str) -> tuple[bool, str]:
    if not path.exists():
        return False, f"{path.name} not found"
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            return False, f"{path.name} is not loadable"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        return False, str(exc)[:200]
    return True, ""


def main() -> int:
    root = Path(__file__).parent
    main_ok, main_detail = _module_loadable(root / "main.py", "flowsteward.google_ads_main")
    checks = [
        {
            "name": "entrypoint",
            "status": "healthy" if main_ok else "failed",
            "detail": main_detail or "main.py is importable",
        }
    ]
    all_healthy = all(item["status"] == "healthy" for item in checks)
    payload = {
        "ok": all_healthy,
        "status": "healthy" if all_healthy else "failed",
        "provider": "flowsteward.google-ads",
        "checks": checks,
    }
    print(json.dumps(payload))
    return 0 if all_healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
