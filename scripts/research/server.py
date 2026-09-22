"""Loopback-only research HTTP API with bounded concurrency and same-origin writes.

This development service intentionally has no arbitrary file, download, shell,
model-training, or candidate-confirmation endpoint. Pipeline workers use Store.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
from pathlib import Path
import re
import secrets
import socket
from socketserver import ThreadingMixIn
import sqlite3
import threading
from urllib.parse import parse_qs, urlsplit

from .artifacts import render_plot
from .protocol import ConflictError, NotFoundError, ValidationError, canonical_json
from .reports import dossier, markdown_report

STATIC_ROOT = Path(__file__).parent / "static"
LOG = logging.getLogger(__name__)
MAX_BODY = 64 * 1024


class ResearchServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 8

    def __init__(self, address, store, artifacts, protocol_id):
        if address[0] != "127.0.0.1":
            raise ValidationError("The research service must bind to 127.0.0.1")
        self.store = store
        self.artifacts = artifacts
        self.protocol_id = protocol_id
        self.csrf_token = secrets.token_urlsafe(32)
        self._slots = threading.BoundedSemaphore(4)
        super().__init__(address, ResearchHandler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(10)
        return request, address

    def process_request(self, request, client_address):
        # Browsers request several dossier plots together. Briefly queue the
        # accepted connection while retaining at most four handler threads;
        # immediate rejection made ordinary six-connection browser bursts lose
        # plots. The OS backlog and wait remain bounded under real overload.
        if not self._slots.acquire(timeout=2):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class ResearchHandler(BaseHTTPRequestHandler):
    server_version = "ResearchPilot/0.1"
    sys_version = ""

    def log_message(self, format, *args):
        # Do not log request bodies, CSRF tokens or user-written review notes.
        LOG.info("%s %s", self.client_address[0], (format % args).replace("\n", " "))

    def _send(self, status, payload, media_type="application/json", filename=None):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                         "frame-ancestors 'none'; form-action 'self'")
        if filename:
            # Always a generated ASCII name, never raw upstream filename text.
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status, value):
        self._send(status, canonical_json(value).encode())

    def _boundary(self, mutation=False):
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host")
        if len(self.headers.get_all("Host", [])) != 1 or host not in hosts:
            self._json(403, {"error": "Unrecognized Host; use the loopback research URL"})
            return False
        if mutation:
            if (self.headers.get("Origin") != "http://" + host
                    or self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none")
                    or not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), self.server.csrf_token)):
                self._json(403, {"error": "Mutation requires same-origin Origin and X-CSRF-Token"})
                return False
        return True

    def _body(self, required):
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise ValidationError("A single Content-Length is required; chunked requests are unsupported")
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            raise ValidationError("Content-Type must be application/json")
        try:
            length = int(self.headers["Content-Length"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("Invalid Content-Length") from exc
        if not 1 <= length <= MAX_BODY:
            raise ValidationError("Request body must be 1–65536 bytes")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValidationError("Incomplete request body")
        def pairs(items):
            result = {}
            for k, v in items:
                if k in result:
                    raise ValidationError("Duplicate JSON object keys")
                result[k] = v
            return result
        def invalid_constant(_):
            raise ValidationError("JSON must contain finite values")
        try:
            data = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise ValidationError("Malformed JSON request") from exc
        if not isinstance(data, dict) or set(data) != set(required):
            raise ValidationError("Required fields: " + ", ".join(required))
        return data

    def do_GET(self):
        self._dispatch(False)

    def do_POST(self):
        self._dispatch(True)

    def _dispatch(self, mutation):
        try:
            if not self._boundary(mutation):
                return
            if len(self.path) > 2048:
                raise ValidationError("Request URL is too long")
            parts = urlsplit(self.path)
            if parts.scheme or parts.netloc or parts.fragment:
                raise ValidationError("Only local relative paths are supported")
            if mutation:
                if parts.query:
                    raise ValidationError("Mutation endpoints do not accept query strings")
                self._post(parts.path)
            else:
                self._get(parts.path, parts.query)
        except ValidationError as exc:
            self._json(400, {"error": str(exc)})
        except NotFoundError as exc:
            self._json(404, {"error": str(exc)})
        except ConflictError as exc:
            self._json(409, {"error": str(exc)})
        except sqlite3.OperationalError:
            LOG.exception("Database operation unavailable")
            self._json(503, {"error": "Database unavailable; retry after checking the local server log"})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception:
            LOG.exception("Request failed")
            self._json(500, {"error": "Internal failure; details are in the local server log"})

    def _get(self, path, query):
        store = self.server.store
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if path in static:
            filename, media_type = static[path]
            self._send(200, (STATIC_ROOT / filename).read_bytes(), media_type)
            return
        if path == "/api/health":
            from .watcher_store import status
            watcher = status(store)
            self._json(200, {"status": "ok", "schema_version": store.summary()["schema_version"],
                            "watcher": [{"id": c["id"], "health": c["health"], "last_success_at": c["last_success_at"]} for c in watcher["configs"]]})
            return
        if path == "/api/watcher":
            from .watcher_store import status
            self._json(200, status(store))
            return
        if path == "/api/experiments":
            from .experiments import list_experiments
            if query:
                raise ValidationError("Experiment lists do not accept query arguments")
            self._json(200, list_experiments(store.path.parent / "model_experiments"))
            return
        experiment_match = re.fullmatch(r"/api/experiments/([A-Za-z0-9][A-Za-z0-9_-]{0,79})/(report\.json|report\.md|comparison\.png)", path)
        if experiment_match:
            from .experiments import read_export
            if query:
                raise ValidationError("Experiment exports do not accept query arguments")
            payload, media_type = read_export(store.path.parent / "model_experiments", *experiment_match.groups())
            self._send(200, payload, media_type,
                       None if experiment_match[2] == "comparison.png" else experiment_match[1] + "-" + experiment_match[2])
            return
        if path == "/api/session":
            self._json(200, {"csrf_token": self.server.csrf_token})
            return
        if path == "/api/overview":
            self._json(200, {**store.summary(), "protocol": store.get_protocol(self.server.protocol_id)})
            return
        if path == "/api/protocol":
            self._json(200, store.get_protocol(self.server.protocol_id))
            return
        if path in ("/api/jobs", "/api/candidates", "/api/releases", "/api/products"):
            try:
                params = parse_qs(query, keep_blank_values=True, max_num_fields=10)
                if set(params) - {"limit", "offset", "cohort", "review_status"} or any(len(v) != 1 for v in params.values()):
                    raise ValueError()
                options = {k: v[0] for k, v in params.items()}
                options.update(limit=int(options.get("limit", 100)), offset=int(options.get("offset", 0)))
            except ValueError as exc:
                raise ValidationError("Invalid list query") from exc
            self._json(200, {"items": store.list_records(path.rsplit("/", 1)[1], **options),
                             "limit": options["limit"], "offset": options["offset"]})
            return
        match = re.fullmatch(r"/api/(jobs|candidates|provenance)/([a-f0-9]{32}|[a-f0-9]{64})", path)
        if match:
            function = {"jobs": store.get_job, "candidates": store.get_candidate, "provenance": store.get_provenance}[match[1]]
            self._json(200, function(match[2]))
            return
        match = re.fullmatch(r"/api/candidates/([a-f0-9]{32})/report\.(json|md)", path)
        if match:
            document = dossier(store, match[1])
            payload = (canonical_json(document) if match[2] == "json" else markdown_report(document)).encode()
            self._send(200, payload, "application/json" if match[2] == "json" else "text/markdown; charset=utf-8",
                       filename=f"candidate-{match[1]}.{match[2]}")
            return
        match = re.fullmatch(r"/api/artifacts/([a-f0-9]{32})(/plot.svg)?", path)
        if match:
            record, payload = self.server.artifacts.read(match[1])
            if match[2]:
                if record["kind"] != "plot" or record["media_type"] != "application/json":
                    raise ValidationError("Artifact is not a plot")
                self._send(200, render_plot(json.loads(payload)), "image/svg+xml")
            else:
                suffix = {"application/json": "json", "text/markdown": "md", "text/csv": "csv",
                          "text/plain": "txt", "image/png": "png", "image/jpeg": "jpg"}.get(record["media_type"], "bin")
                self._send(200, payload, record["media_type"], filename=f"artifact-{record['id']}.{suffix}")
            return
        raise NotFoundError("Endpoint not found")

    def _post(self, path):
        match = re.fullmatch(r"/api/candidates/([a-f0-9]{32})/review", path)
        if match:
            data = self._body(("status", "reviewer", "note", "expected_revision"))
            self._json(200, self.server.store.review_candidate(match[1], **data))
            return
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/retry", path)
        if match:
            data = self._body(("stage", "actor", "reason"))
            self.server.store.retry_stage(match[1], data["stage"], actor=data["actor"], reason=data["reason"])
            self._json(200, self.server.store.get_job(match[1]))
            return
        raise NotFoundError("Mutation endpoint not found")
