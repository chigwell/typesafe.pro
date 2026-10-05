"""Local, synthetic API for refactor screenshots; never forwards to upstream."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[3]
PAGE = json.loads((ROOT / "apps/api/tests/fixtures/use_case_page.json").read_text())
CATEGORY = {"slug": "tone-sentiment", "name": "Tone & sentiment"}
TAGS = [{"slug": "music", "name": "music"}, {"slug": "colour", "name": "colour"}]
CARD = {
    "slug": PAGE["slug"],
    "title": PAGE["seo"]["title"],
    "summary": PAGE["summary"],
    "industry": PAGE["industry"],
    "audience": PAGE["audience"],
    "task_type": PAGE["task_type"],
    "question_types": ["choice"],
    "has_demo": True,
    "category": CATEGORY,
    "tags": TAGS,
    "published_at": PAGE["created_at"],
    "updated_at": PAGE["updated_at"],
}
SAMPLE = {
    "at": 1700000000,
    "cpu_percent": 42,
    "memory": {"percent": 60, "used_bytes": 600000000, "total_bytes": 1000000000},
    "disk": {"percent": 35, "used_bytes": 3500000000, "total_bytes": 10000000000},
    "load": [0.5, 0.4, 0.3],
}
SYSTEM = {
    "status": "ok",
    "release": "parity-fixture",
    "current": SAMPLE,
    "history": [SAMPLE],
    "redis": {"ok": True, "latency_ms": 2},
    "postgres": {"ok": True, "latency_ms": 3},
    "queue": {
        "inflight": 1,
        "max_inflight": 32,
        "pending": {"anonymous": 2},
        "body_bytes": 0,
    },
    "telemetry": {
        "dropped_errors": 0,
        "dropped_activity": 0,
        "last_flush_at": 1700000000,
    },
}
SUMMARY = {
    "window": "24h",
    "from": 0,
    "to": 1700000000,
    "totals": {
        "requests": 120,
        "unique_ips": 26,
        "errors": 4,
        "rate_limited": 2,
        "usage_tokens": 500,
        "estimated_tokens": 700,
        "usage_reported_requests": 100,
        "upstream_requests": 118,
        "avg_duration_ms": 10,
        "avg_upstream_ms": 8,
    },
    "tiers": [{"name": "anonymous", "requests": 120}],
    "masters": [{"name": "1", "requests": 118, "avg_upstream_ms": 8}],
    "paths": [{"name": "/v1/systemone", "requests": 120}],
    "status_codes": {"200": 116, "502": 4},
    "status_classes": {"2xx": 116},
    "upstream_statuses": {"200": 114},
    "telemetry": {"dropped": 0, "last_flush_at": 1700000000},
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, value=None, status=200):
        body = json.dumps(value).encode() if value is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost:3084")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.reply(status=204)

    def do_POST(self):
        if self.path == "/v1/analytics/page-view":
            self.reply(status=204)
        else:
            self.reply({"error": "parity_fixture_no_live_requests"}, 503)

    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        path = url.path
        if path == "/v1/use-cases":
            self.reply({"items": [CARD], "total": 1, "page": 1, "page_size": 24})
        elif path == "/v1/use-case-facets":
            self.reply(
                {
                    "total": 1,
                    "categories": [{**CATEGORY, "description": "", "count": 1}],
                    "tags": [{**tag, "count": 1} for tag in TAGS],
                }
            )
        elif path == "/v1/use-cases-sitemap":
            self.reply(
                {
                    "items": [{"slug": PAGE["slug"], "updated_at": PAGE["updated_at"]}],
                    "total": 1,
                    "chunk": 0,
                    "chunk_size": 10000,
                }
            )
        elif path == "/v1/use-cases/" + PAGE["slug"]:
            self.reply({**CARD, "status": "published", "page": PAGE, "related": []})
        elif path == "/admin/api/auth/session":
            self.reply({"authenticated": True})
        elif path == "/admin/api/system":
            self.reply(SYSTEM)
        elif path == "/admin/api/summary":
            self.reply({**SUMMARY, "window": query.get("window", ["24h"])[0]})
        elif path == "/admin/api/seo/summary":
            self.reply(
                {
                    "total_pages": 1,
                    "added_last_deploy": 1,
                    "latest_publication": None,
                    "latest_attempt": None,
                    "totals": {
                        "runs": 0,
                        "api_calls": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                    },
                }
            )
        elif path.startswith("/admin/api/"):
            self.reply(
                {
                    "items": [],
                    "total": 0,
                    "page": int(query.get("page", ["1"])[0]),
                    "page_size": 25,
                }
            )
        else:
            self.reply({"detail": "Fixture route not found"}, 404)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4310)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
