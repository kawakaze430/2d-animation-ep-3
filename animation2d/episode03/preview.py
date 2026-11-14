"""Review Episode 03 shots in a browser or export a portable, static review pack.

The static pack contains three real renderer samples per shot. Its slider selects
those samples; it does not pretend to contain a continuous animation or a movie.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from functools import lru_cache
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import threading
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
WEB = Path(__file__).resolve().parent / 'web'
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}


def render_frame(*args, **kwargs):
    # The live server starts even before importing optional rendering dependencies.
    from .engine import render_frame as engine_frame
    return engine_frame(*args, **kwargs)


class PreviewProject:
    def __init__(self, manifest: Path, mode='blocking', *, root=ROOT, renderer=None):
        self.path = Path(manifest).resolve()
        self.root = Path(root).resolve()
        self.mode = mode
        self.renderer = renderer or render_frame
        if mode not in ('blocking', 'production'):
            raise ValueError('Preview mode must be blocking or production')
        self.manifest = json.loads(self.path.read_text())
        shots = self.manifest.get('shots')
        if not isinstance(shots, list) or not shots:
            raise ValueError('The manifest needs a nonempty shots list')
        self.shots = {}
        for shot in shots:
            key = shot.get('id')
            if not isinstance(key, str) or not key or key in self.shots:
                raise ValueError('Shot IDs must be nonempty and unique')
            duration = float(shot.get('duration', 15))
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(f'{key}: invalid duration')
            self.shots[key] = shot
        self.manifest['__base_dir__'] = str(self.root)
        self.assets = {}
        self.asset_urls = {}
        self.lock = threading.Lock()
        self._collect_assets(self.manifest)

    def _collect_assets(self, value):
        if isinstance(value, dict):
            for item in value.values():
                self._collect_assets(item)
        elif isinstance(value, list):
            for item in value:
                self._collect_assets(item)
        elif isinstance(value, str) and Path(value).suffix.lower() in IMAGE_SUFFIXES:
            candidate = (self.root / value).resolve()
            # Only images explicitly declared in the manifest and contained in the
            # checkout are reachable. No raw path is ever accepted by the server.
            if not candidate.is_relative_to(self.root) or not candidate.is_file():
                return
            relative = candidate.relative_to(self.root).as_posix()
            key = hashlib.sha256(relative.encode()).hexdigest()[:24] + candidate.suffix.lower()
            self.assets[key] = candidate
            self.asset_urls[value] = 'assets/' + key

    def time(self, shot_id, value):
        if shot_id not in self.shots:
            raise ValueError('Unknown shot ID')
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Time must be a finite number')
        duration = float(self.shots[shot_id].get('duration', 15))
        fps = float(self.manifest.get('fps', 24))
        return min(max(number, 0), max(0, duration - 1 / max(fps, 1)))

    @lru_cache(maxsize=24)
    def frame(self, shot_id, time):
        time = self.time(shot_id, time)
        with self.lock:
            image = self.renderer(self.manifest, shot_id, time, mode=self.mode, size=(960, 540))
            output = BytesIO()
            image.convert('RGB').save(output, format='JPEG', quality=87)
            return output.getvalue()

    def browser_manifest(self, *, static=False):
        result = deepcopy(self.manifest)
        result.pop('__base_dir__', None)
        result['_preview'] = {
            'mode': self.mode,
            'static': static,
            'sample_times': [0, 7.5, 15 - 1 / 24],
            'asset_urls': self.asset_urls,
            'notice': ('Three sampled frames per shot; this is not a continuous animation.'
                       if static else 'Live renderer review. Full movie rendering runs in GitHub Actions.'),
        }
        return result


def handler_for(project):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            return

        def respond(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def error_json(self, status, message):
            self.respond(status, json.dumps({'error': message}).encode(), 'application/json')

        def do_GET(self):
            url = urlsplit(self.path)
            path = unquote(url.path)
            if path in ('/', '/index.html', '/app.js', '/style.css'):
                name = 'index.html' if path == '/' else path[1:]
                kind = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8',
                        'style.css': 'text/css; charset=utf-8'}[name]
                self.respond(200, (WEB / name).read_bytes(), kind)
            elif path == '/manifest.js':
                content = 'window.EPISODE_PREVIEW = ' + json.dumps(project.browser_manifest()) + ';\n'
                self.respond(200, content.encode(), 'text/javascript; charset=utf-8')
            elif path == '/api/manifest':
                self.respond(200, json.dumps(project.browser_manifest()).encode(), 'application/json')
            elif path.startswith('/assets/'):
                key = path[len('/assets/'):]
                if key not in project.assets:
                    self.error_json(404, 'Unknown review asset')
                    return
                image = project.assets[key]
                mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}[image.suffix.lower()]
                self.respond(200, image.read_bytes(), mime)
            elif path == '/api/frame':
                try:
                    params = parse_qs(url.query, keep_blank_values=True)
                    if set(params) - {'shot', 't'} or any(len(value) != 1 for value in params.values()):
                        raise ValueError('Use one shot and one time parameter')
                    shot = params.get('shot', [''])[0]
                    time = project.time(shot, params.get('t', ['0'])[0])
                    self.respond(200, project.frame(shot, time), 'image/jpeg')
                except (ValueError, TypeError, KeyError) as error:
                    self.error_json(400, str(error))
                except Exception as error:
                    # Asset gating failures remain visible; never replace a failed
                    # production render with an unlabeled blocking picture.
                    self.error_json(409, str(error))
            else:
                self.error_json(404, 'Unknown review route')
    return Handler


def export_review(project, destination):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError('Export directory must be new or empty; preserve existing review work')
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('index.html', 'app.js', 'style.css'):
        shutil.copy2(WEB / name, destination / name)
    (destination / 'assets').mkdir()
    for key, path in project.assets.items():
        shutil.copy2(path, destination / 'assets' / key)
    browser = project.browser_manifest(static=True)
    for index, shot in enumerate(browser['shots']):
        # Export paths are generated indexes, never untrusted manifest IDs.
        folder = destination / 'frames' / f'{index + 1:03}'
        folder.mkdir(parents=True)
        duration = float(shot.get('duration', 15))
        times = [0, duration / 2, project.time(shot['id'], duration)]
        shot['_preview_frames'] = []
        for sample, time in enumerate(times):
            path = folder / f'{sample}.jpg'
            path.write_bytes(project.frame(shot['id'], time))
            shot['_preview_frames'].append({'time': time, 'url': path.relative_to(destination).as_posix()})
    (destination / 'manifest.json').write_text(json.dumps(browser, indent=2) + '\n')
    (destination / 'manifest.js').write_text('window.EPISODE_PREVIEW = ' + json.dumps(browser) + ';\n')
    (destination / 'README.txt').write_text(
        'Open index.html in a browser. No server or internet connection is needed.\n'
        'This pack contains three renderer samples per shot, not a continuous animation.\n'
        f'Render mode: {project.mode}. Blocking schematics do not certify approved character likeness.\n')
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--mode', choices=('blocking', 'production'), default='blocking')
    parser.add_argument('--export', type=Path)
    args = parser.parse_args()
    project = PreviewProject(args.manifest, args.mode)
    if args.export:
        print(export_review(project, args.export))
        return
    with ThreadingHTTPServer((args.host, args.port), handler_for(project)) as server:
        print(f'Episode 03 review server listening on {args.host}:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
