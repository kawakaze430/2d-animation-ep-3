"""Local, zero-provider, browser-accessible animation timeline studio (MVP).

This is not a publicly hosted multi-user server. Only loopback is accepted:
remote deployments require a real authenticated proxy/service and CSRF review.
No arbitrary filesystem reads or arbitrary Python execution endpoints.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

from .rigging import (decode_layers, import_layers, rig_info, commit_rig_edit,
                      restore_rig_version, original_rig_preview, sprite_bytes)

from .editing import EditSession
from .schema import stable_bytes

WEB = Path(__file__).resolve().parent / "web"
MAX_BODY = 65536
MAX_LAYER_BODY = 64 * 1024 * 1024


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
            if route in ("/api/rig", "/api/rig-image", "/api/rig-preview"):
                try:
                    params = parse_qs(url.query)
                    allowed = ({"character","bone"} if route == "/api/rig-image"
                               else {"character","movement"} if route == "/api/rig-preview"
                               else {"character"})
                    if set(params) - allowed or any(len(value) != 1 for value in params.values()):
                        raise ValueError("Unknown rig preview query")
                    character = params.get("character", [""])[0]
                    if not character:
                        raise ValueError("Choose a registered character")
                    with lock:
                        if route == "/api/rig":
                            self.json(200, {"rig": rig_info(project, character),
                                            "revision": revision(project)})
                        elif route == "/api/rig-image":
                            bone = params.get("bone", [""])[0]
                            self.reply(200, sprite_bytes(project, character, bone), "image/png")
                        else:
                            flag = params.get("movement", ["0"])[0]
                            if flag not in ("0", "1"):
                                raise ValueError("movement must be 0 or 1")
                            img = original_rig_preview(project, character, movement=flag=="1")
                            buffer = BytesIO()
                            img.save(buffer, format="PNG")
                            self.reply(200, buffer.getvalue(), "image/png")
                except (ValueError, TypeError, KeyError, FileNotFoundError) as error:
                    self.error(400, error)
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
            if url.path not in ("/api/edit", "/api/undo", "/api/redo",
                                 "/api/rig/import", "/api/rig/edit", "/api/rig/restore"):
                self.error(404, "Unknown route")
                return
            # A cross-origin form cannot send application/json without CORS
            # preflight, and the server never grants cross-origin permissions.
            # Also refuse unexpected origins rather than accepting an opaque one.
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            url_host = urlsplit("http://" + host)
            if (url_host.hostname not in ("localhost", "127.0.0.1", "::1") or
                    url_host.port != self.server.server_port):
                self.error(403, "Invalid local Host header")
                return
            if origin and origin != "http://" + host:
                self.error(403, "Cross-origin rig editing is prohibited")
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self.error(415, "Use Content-Type: application/json")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = MAX_LAYER_BODY if url.path == "/api/rig/import" else MAX_BODY
                if length < 2 or length > limit:
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
                    elif url.path == "/api/redo":
                        session.redo(save=True)
                    elif url.path == "/api/rig/import":
                        # No external path, provider or arbitrary filename is
                        # accepted. The exact 15 semantic roles are required.
                        if set(data) != {"revision", "character", "layers", "source", "license"}:
                            raise ValueError("Rig import needs revision, character, layers, source and license")
                        if not isinstance(data["source"], str) or not isinstance(data["license"], str):
                            raise ValueError("Artwork provenance must be strings")
                        raw = decode_layers(data["layers"])
                        import_layers(project, data["character"], raw,
                                      source=data["source"], license=data["license"])
                        session.reset()  # immutable artwork imports aren't undoable
                    elif url.path == "/api/rig/edit":
                        if set(data) != {"revision", "character", "edit"}:
                            raise ValueError("Rig edit needs character and edit operation")
                        before = deepcopy(project.doc)
                        commit_rig_edit(project, data["character"], data["edit"])
                        session.record_external(before)
                    elif url.path == "/api/rig/restore":
                        if set(data) != {"revision", "character", "version"}:
                            raise ValueError("Rig restore needs character and saved version")
                        before = deepcopy(project.doc)
                        restore_rig_version(project, data["character"], data["version"])
                        session.record_external(before)
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
