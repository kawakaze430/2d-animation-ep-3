"""Integration smoke for actual Pillow artwork, motion, narration and FFmpeg encoding."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'animation2d' / 'project'
sys.path.insert(0, str(PROJECT))
SPEC = importlib.util.spec_from_file_location('two_d_renderer', PROJECT / 'action_render.py')
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class RenderEncodingTests(unittest.TestCase):
    def test_real_animated_frames_encode_with_audio(self):
        """Catch missing assets, static output, broken rendering, or broken media tools."""
        with tempfile.TemporaryDirectory(prefix='animation2d-smoke-') as directory:
            output = Path(directory) / 'render.mp4'
            cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                   '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '640x360', '-r', '24',
                   '-i', 'pipe:0', '-i', str(PROJECT / 'audio/narration.flac'),
                   '-map', '0:v:0', '-map', '1:a:0', '-t', '1',
                   '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast',
                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(output)]
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            hashes = set()
            failure = None
            try:
                for frame in range(24):
                    # The sit-up/stretch shot has actual joint and face motion.
                    image = renderer.frame(13 + frame / 24)
                    self.assertEqual(image.size, (1920, 1080))
                    image = image.resize((640, 360), Image.Resampling.LANCZOS).convert('RGB')
                    pixels = np.asarray(image)
                    self.assertGreater(float(pixels.std()), 15, 'Rendered frame is blank')
                    raw = image.tobytes()
                    # Exclude captions and the timeline bar so UI progress alone
                    # cannot make a frozen character pass the motion check.
                    hashes.add(hashlib.sha256(image.crop((100, 10, 540, 295)).tobytes()).digest())
                    process.stdin.write(raw)
            except BaseException as error:
                failure = error
                process.kill()
            finally:
                process.stdin.close()
                stderr = process.stderr.read().decode(errors='replace')
                code = process.wait(timeout=60)
                process.stderr.close()
            if failure:
                raise failure
            self.assertEqual(code, 0, stderr)
            self.assertGreater(len(hashes), 12, 'Frame sequence lost its animation')
            probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames',
                                    '-show_entries', 'stream=codec_name,width,height,nb_read_frames',
                                    '-show_entries', 'format=duration', '-of', 'json', str(output)],
                                   check=True, capture_output=True, text=True)
            media = json.loads(probe.stdout)
            video = next(stream for stream in media['streams'] if stream['codec_name'] == 'h264')
            self.assertEqual((video['width'], video['height']), (640, 360))
            self.assertEqual(int(video['nb_read_frames']), 24)
            self.assertTrue(any(stream['codec_name'] == 'aac' for stream in media['streams']))
            self.assertAlmostEqual(float(media['format']['duration']), 1.0, delta=0.05)


if __name__ == '__main__':
    unittest.main()
