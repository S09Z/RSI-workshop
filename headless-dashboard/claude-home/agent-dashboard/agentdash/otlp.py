"""Minimal OTLP/HTTP receiver: JSON encoding only, 127.0.0.1 only, append-only file output.

    orch-dashboard --otlp            # listens on 127.0.0.1:4318
    export OTEL_EXPORTER_OTLP_PROTOCOL=http/json
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318

POST /v1/traces | /v1/metrics | /v1/logs with Content-Type application/json (gzip allowed).
Each request body is written as one line {"signal","received","body"} to otel.jsonl; the
ingester parses it later, so the receiver does no database work and cannot slow Claude Code.
Content attributes (prompts, tool input, responses, ...) are removed before writing unless
privacy.store_result_text is enabled. Protobuf requests get 415, which Claude Code treats as an
export failure; export failures do not affect the session.
"""
import gzip
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .ingest import CONTENT_ATTRS

MAX_BODY = 16 * 1024 * 1024
SIGNALS = {"/v1/traces": "traces", "/v1/metrics": "metrics", "/v1/logs": "logs"}


def scrub(obj):
    """Drop content-bearing attributes anywhere in an OTLP JSON document."""
    if isinstance(obj, dict):
        if "attributes" in obj and isinstance(obj["attributes"], list):
            obj["attributes"] = [kv for kv in obj["attributes"]
                                 if not (isinstance(kv, dict) and kv.get("key") in CONTENT_ATTRS)]
        if "events" in obj and isinstance(obj["events"], list):  # span events such as tool.output
            obj["events"] = [e for e in obj["events"] if not (isinstance(e, dict) and str(e.get("name", "")).startswith("tool.output"))]
        for v in obj.values():
            scrub(v)
    elif isinstance(obj, list):
        for v in obj:
            scrub(v)
    return obj


class _Writer:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def write(self, line):
        with self.lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def make_handler(writer, keep_content=False):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, code, body=b"{}", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            sig = SIGNALS.get(self.path.split("?")[0])
            n = int(self.headers.get("Content-Length") or 0)
            if sig is None:
                self.rfile.read(n)
                return self._reply(404, b'{"error":"unknown path"}')
            if n > MAX_BODY:
                self.rfile.read(n)
                return self._reply(413, b'{"error":"too large"}')
            raw = self.rfile.read(n)
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self._reply(415, b'{"error":"only http/json is supported; set OTEL_EXPORTER_OTLP_PROTOCOL=http/json"}')
            try:
                if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                body = json.loads(raw)
            except Exception:
                return self._reply(400, b'{"error":"bad json"}')
            if not keep_content:
                scrub(body)
            try:
                writer.write(json.dumps({"signal": sig, "received": time.time(), "body": body}, separators=(",", ":")))
            except OSError:
                return self._reply(503, b'{"error":"write failed"}')
            self._reply(200, b"{}")

        def do_GET(self):
            if self.path == "/health":
                return self._reply(200, b'{"ok":true}')
            self._reply(404, b"{}")

        def log_message(self, *a):
            pass

    return H


def serve(path, host="127.0.0.1", port=4318, keep_content=False, ready=None):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("refusing to listen on a non-loopback address")
    srv = ThreadingHTTPServer((host, port), make_handler(_Writer(path), keep_content))
    if ready:
        ready(srv)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
