"""Loopback-only smoke test for the private ARIA staging services."""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request


def _loopback(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("private staging tests only permit loopback HTTP URLs")
    return url.rstrip("/")


def _json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"unexpected status {response.status}")
        return json.load(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:8080")
    args = parser.parse_args(argv)
    backend = _loopback(args.backend_url)
    frontend = _loopback(args.frontend_url)

    health = _json(f"{backend}/health")
    ready = _json(f"{backend}/ready")
    frontend_health = _json(f"{frontend}/frontend-health")
    with urllib.request.urlopen(frontend, timeout=10) as response:
        html = response.read(1_000_000).decode("utf-8", errors="replace")
    assert health["status"] == "ready"
    assert ready == {
        "status": "ready", "execution_mode": "offline_mock",
        "live_execution": False, "connector_mode": "fixtures",
        "persistence_writable": True, "stores_ready": True,
    }
    assert frontend_health == {"status": "ok"}
    assert '<div id="root"></div>' in html
    print("SMOKE_OK backend=ready frontend=ok mode=offline_mock live=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
