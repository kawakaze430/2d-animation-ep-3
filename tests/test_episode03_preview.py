"""Browser review exposes only declared assets and actual sampled render frames."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from PIL import Image, ImageDraw

from animation2d.episode03.preview import PreviewProject, export_review, handler_for, ThreadingHTTPServer


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'refs').mkdir()
        Image.new('RGB', (64, 96), '#a07050').save(self.root / 'refs' / 'MAYA.jpg')
        self.path = self.root / 'manifest.json'
        self.data = {
            'fps': 24,
            'characters': {'MAYA': {'reference': 'refs/MAYA.jpg'}},
            'shots': [{'id': 'SHOT_001', 'title': 'One', 'duration': 15, 'cast': ['MAYA']},
                      {'id': 'SHOT_002', 'title': 'Two', 'duration': 15, 'cast': ['MAYA']}],
        }
        self.path.write_text(json.dumps(self.data))
        self.calls = []

        def renderer(manifest, shot, time, **kwargs):
            self.calls.append((shot, time, kwargs['mode']))
            image = Image.new('RGB', kwargs['size'], '#e5d7b7')
            draw = ImageDraw.Draw(image)
            x = 50 + int(time * 30)
            draw.rectangle((x, 70, x + 60, 180), fill='#4f7885')
            return image

        self.project = PreviewProject(self.path, root=self.root, renderer=renderer)

    def tearDown(self):
        self.temp.cleanup()

    def server(self, project=None):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(project or self.project))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}'

    def get(self, server, path):
        with urlopen(server + path, timeout=10) as response:
            return response.status, response.headers, response.read()

    def test_server_serves_manifest_live_frame_and_only_declared_assets(self):
        server = self.server()
        status, _, body = self.get(server, '/api/manifest')
        manifest = json.loads(body)
        self.assertEqual(status, 200)
        self.assertNotIn('__base_dir__', manifest)
        self.assertFalse(manifest['_preview']['static'])
        asset = manifest['_preview']['asset_urls']['refs/MAYA.jpg']
        self.assertEqual(self.get(server, '/' + asset)[0], 200)
        status, headers, image = self.get(server, '/api/frame?shot=SHOT_001&t=7.5')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/jpeg')
        self.assertTrue(image.startswith(b'\xff\xd8'))
        self.assertEqual(self.calls[-1], ('SHOT_001', 7.5, 'blocking'))
        for path in ('/manifest.json', '/refs/MAYA.jpg', '/assets/../manifest.json', '/%2e%2e/manifest.json'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                self.get(server, path)
            self.assertEqual(caught.exception.code, 404)

    def test_invalid_shots_and_nonfinite_times_are_rejected_while_bounds_are_clamped(self):
        server = self.server()
        for query in ('shot=MISSING&t=0', 'shot=SHOT_001&t=nan', 'shot=SHOT_001&t=inf',
                      'shot=SHOT_001&t=wrong', 'shot=SHOT_001&shot=SHOT_002',
                      'shot=SHOT_001&path=/etc/passwd'):
            with self.subTest(query=query), self.assertRaises(HTTPError) as caught:
                self.get(server, '/api/frame?' + query)
            self.assertEqual(caught.exception.code, 400)
        self.get(server, '/api/frame?shot=SHOT_001&t=999')
        self.assertAlmostEqual(self.calls[-1][1], 15 - 1 / 24)
        self.get(server, '/api/frame?shot=SHOT_001&t=-8')
        self.assertEqual(self.calls[-1][1], 0)

    def test_asset_symlink_cannot_escape_checkout(self):
        with tempfile.TemporaryDirectory() as outside:
            secret_image = Path(outside) / 'outside.jpg'
            Image.new('RGB', (1, 1)).save(secret_image)
            (self.root / 'refs' / 'escaped.jpg').symlink_to(secret_image)
            self.data['characters']['MAYA']['other'] = 'refs/escaped.jpg'
            self.path.write_text(json.dumps(self.data))
            project = PreviewProject(self.path, root=self.root)
            self.assertNotIn('refs/escaped.jpg', project.asset_urls)

    def test_static_pack_has_three_true_samples_per_shot_and_bundled_references(self):
        output = export_review(self.project, self.root / 'review')
        manifest = json.loads((output / 'manifest.json').read_text())
        self.assertTrue(manifest['_preview']['static'])
        self.assertIn('three', (output / 'README.txt').read_text().lower())
        self.assertTrue((output / manifest['_preview']['asset_urls']['refs/MAYA.jpg']).is_file())
        self.assertEqual(len(self.calls), 6)
        for shot in manifest['shots']:
            frames = shot['_preview_frames']
            self.assertEqual(len(frames), 3)
            self.assertEqual(frames[0]['time'], 0)
            self.assertEqual(frames[1]['time'], 7.5)
            self.assertAlmostEqual(frames[2]['time'], 15 - 1 / 24)
            self.assertEqual(len({(output / frame['url']).read_bytes() for frame in frames}), 3)
        for name in ('index.html', 'app.js', 'style.css', 'manifest.js'):
            self.assertTrue((output / name).is_file())
        with self.assertRaises(FileExistsError):
            export_review(self.project, output)
        self.assertEqual(len(list((output / 'frames').rglob('*.jpg'))), 6)

    def test_failed_production_frame_is_reported_without_blocking_fallback(self):
        def reject(*args, **kwargs):
            raise RuntimeError('MAYA production rig is missing')
        project = PreviewProject(self.path, mode='production', root=self.root, renderer=reject)
        server = self.server(project)
        with self.assertRaises(HTTPError) as caught:
            self.get(server, '/api/frame?shot=SHOT_001&t=0')
        self.assertEqual(caught.exception.code, 409)
        self.assertIn('production rig is missing', caught.exception.read().decode())

    def test_duplicate_shots_do_not_silently_replace_another_scene(self):
        self.data['shots'][1]['id'] = 'SHOT_001'
        self.path.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError, 'unique'):
            PreviewProject(self.path, root=self.root)


if __name__ == '__main__':
    unittest.main()
