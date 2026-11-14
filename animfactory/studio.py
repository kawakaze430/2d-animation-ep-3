"""Local, zero-provider, browser-accessible animation timeline studio (MVP).

This is not a publicly hosted multi-user server. Only loopback is accepted:
remote deployments require a real authenticated proxy/service and CSRF review.
No arbitrary filesystem reads or arbitrary Python execution endpoints.
"""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

from .editing import EditSession
from .schema import stable_bytes

WEB = Path(__file__).resolve().parent / "web"
MAX_BODY = 65536


def revision(project):
    return hashlib.sha256(stable_bytes(project.doc)).hexdigest()


def handler_for(project):
    session = EditSession(project)
    lock = threading.RLock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body, content_type="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; "
                             "script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def json(self, code, payload):
            self.reply(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        def error(self, code, error):
            self.json(code, {"error": str(error)})

        def do_GET(self):
            url = urlsplit(self.path)
            route = url.path
            if route in ("/", "/index.html", "/app.js", "/style.css"):
                name = "index.html" if route == "/" else route[1:]
                target = WEB / name
                mime = {"index.html": "text/html; charset=utf-8",
                        "app.js": "text/javascript; charset=utf-8",
                        "style.css": "text/css; charset=utf-8"}
                self.reply(200, target.read_bytes(), mime[name])
                return
            if route == "/api/project":
                with lock:
                    self.json(200, {"project": project.doc, "revision": revision(project),
                                    "undo": session.can_undo, "redo": session.can_redo})
                return
            if route == "/api/motions":
                params = parse_qs(url.query)
                with lock:
                    self.json(200, {"motions": project.motion_registry(
                        params.get("q", [""])[0][:120])})
                return
            if route == "/api/frame":
                try:
                    params = parse_qs(url.query)
                    if set(params) - {"scene", "index", "mode"}:
                        raise ValueError("Unknown preview query")
                    scene = params.get("scene", [""])[0]
                    frame = int(params.get("index", ["0"])[0])
                    mode = params.get("mode", ["blocking"])[0]
                    if mode not in ("blocking", "production"):
                        raise ValueError("Unsupported renderer mode")
                    with lock:
                        canvas = project.doc["canvas"]
                        scale = min(1., 960/max(canvas))
                        size = [max(16, round(x*scale)) for x in canvas]
                        image = project.render_frame(scene, frame, size=size, mode=mode)
                        buffer = BytesIO()
                        image.save(buffer, format="PNG")
                    self.reply(200, buffer.getvalue(), "image/png")
                except (TypeError, ValueError, IndexError, KeyError) as error:
                    self.error(400, error)
                except Exception as error:
                    self.error(409, error)  # no unlabeled schematic fallback
                return
            self.error(404, "Unknown route")

        def do_POST(self):
            url = urlsplit(self.path)
            if url.path not in ("/api/edit", "/api/undo", "/api/redo"):
                self.error(404, "Unknown route")
                return
            # A cross-origin form cannot send application/json without CORS
            # preflight, and the server never grants cross-origin permissions.
            # Also refuse unexpected origins rather than accepting an opaque one.
            origin = self.headers.get("Origin")
            if origin:
                valid = ("http://localhost:", "http://127.0.0.1:", "http://[::1]:")
                if not origin.startswith(valid):
                    self.error(403, "Local editor only")
                    return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self.error(415, "Use Content-Type: application/json")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 2 or length > MAX_BODY:
                    raise ValueError("Invalid JSON request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or not isinstance(data.get("revision"), str):
                    raise ValueError("Expected revision and JSON body")
                with lock:
                    if data["revision"] != revision(project):
                        self.error(409, "Project changed; reload before editing")
                        return
                    if url.path == "/api/edit":
                        session.apply(data.get("command"), save=True)
                    elif url.path == "/api/undo":
                        session.undo(save=True)
                    else:
                        session.redo(save=True)
                    self.json(200, {"project": project.doc, "revision": revision(project),
                                    "undo": session.can_undo, "redo": session.can_redo})
            except (ValueError, TypeError, KeyError, IndexError, PermissionError,
                    FileNotFoundError) as error:
                self.error(400, error)

    return Handler


def serve(project, host="127.0.0.1", port=8190):
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Studio must bind to loopback; public hosting needs authentication")
    if not 1 <= port <= 65535:
        raise ValueError("Invalid studio port")
    with ThreadingHTTPServer((host, port), handler_for(project)) as server:
        print(f"Animation Factory Studio: http://{host}:{port}", flush=True)
        server.serve_forever()
