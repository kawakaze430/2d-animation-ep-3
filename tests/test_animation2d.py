"""Isolation and failure checks for the 2D build wrapper."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('animation2d_run', ROOT / 'animation2d' / 'run.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class BuildIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'animation2d' / 'project'
        self.source.mkdir(parents=True)
        (self.source / 'lesson.json').write_text('{"title":"Original reference"}')
        (self.source / 'audio').mkdir()
        (self.source / 'audio' / 'narration.flac').write_bytes(b'reference-recording')
        (self.source / 'output').mkdir()
        (self.source / 'output' / 'stale.mp4').write_bytes(b'stale')
        self.root_patch = patch.object(runner, 'ROOT', self.root)
        self.source_patch = patch.object(runner, 'SOURCE', self.source)
        self.root_patch.start()
        self.source_patch.start()

    def tearDown(self):
        self.source_patch.stop()
        self.root_patch.stop()
        self.temp.cleanup()

    def test_copies_reference_audio_without_source_mutation_or_stale_output(self):
        project = runner.prepare('original')
        self.assertEqual((project / 'audio' / 'narration.flac').read_bytes(), b'reference-recording')
        self.assertFalse((project / 'output').exists())
        (project / 'lesson.json').write_text('edited build')
        self.assertEqual(json.loads((self.source / 'lesson.json').read_text())['title'], 'Original reference')

    def test_refuses_to_delete_unknown_existing_build(self):
        project = runner.project_path('original')
        project.mkdir(parents=True)
        sentinel = project / 'user-work.txt'
        sentinel.write_text('preserve me')
        with self.assertRaisesRegex(RuntimeError, 'unrecognized'):
            runner.prepare('original', refresh=True)
        self.assertEqual(sentinel.read_text(), 'preserve me')

    def test_repeated_prepare_preserves_work_and_source_change_requires_explicit_refresh(self):
        project = runner.prepare('original')
        (project / 'custom.txt').write_text('local generation')
        self.assertEqual(runner.prepare('original'), project)
        self.assertTrue((project / 'custom.txt').exists())
        (self.source / 'lesson.json').write_text('{"title":"Updated reference"}')
        with self.assertRaisesRegex(RuntimeError, 'Source changed'):
            runner.prepare('original')
        self.assertTrue((project / 'custom.txt').exists())
        runner.prepare('original', refresh=True)
        self.assertFalse((project / 'custom.txt').exists())
        self.assertEqual(json.loads((project / 'lesson.json').read_text())['title'], 'Updated reference')

    def test_missing_episode_audio_cannot_fall_back_to_original_recording(self):
        project = runner.prepare('original')
        (project / 'audio' / 'narration.flac').unlink()
        with self.assertRaisesRegex(RuntimeError, 'run voice'):
            runner.require_audio(project)

    def test_episode02_preparation_changes_invalidate_only_its_build_signature(self):
        episode2 = self.source.parent / 'episode2'
        episode2.mkdir()
        script = episode2 / 'prepare_episode.py'
        script.write_text('SHOTS = ["old dialogue"]\n')
        with patch.object(runner, 'HERE', self.source.parent):
            original = runner.source_digest('original')
            continuation = runner.source_digest('02')
            script.write_text('SHOTS = ["new dialogue"]\n')
            self.assertEqual(runner.source_digest('original'), original)
            self.assertNotEqual(runner.source_digest('02'), continuation)


class SubtitleExportTests(unittest.TestCase):
    def test_clips_boundary_cue_preserving_words_and_drops_later_cues(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'clipped.srt'
            runner.clip_subtitles(ROOT / 'animation2d' / 'project' / 'captions.srt', output, 15)
            text = output.read_text()
            self.assertIn('00:00:13,340 --> 00:00:15,000\nI stretch my arms.', text)
            self.assertNotIn('I am ready to get up.', text)
            self.assertNotIn('00:00:15,239', text)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
    def test_crossing_subtitle_does_not_extend_fifteen_second_mp4(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            subtitles = runner.clip_subtitles(ROOT / 'animation2d' / 'project' / 'captions.srt', folder / 'clipped.srt', 15)
            output = folder / 'synthetic-timing-regression.mp4'
            # This is a timing/mux regression fixture, not a rendered animation claim.
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                            '-i', 'color=c=blue:s=1920x1080:r=24:d=15',
                            '-i', str(ROOT / 'animation2d' / 'project' / 'audio' / 'narration.flac'),
                            '-i', str(subtitles), '-map', '0:v:0', '-map', '1:a:0', '-map', '2:s:0',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30', '-threads', '2',
                            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ac', '2', '-c:s', 'mov_text',
                            '-t', '15', str(output)], check=True)
            report = runner.inspect_video(output, 15)
            self.assertEqual((report['frames'], report['duration']), (360, 15.0))

    def test_malformed_subtitles_fail_instead_of_silently_dropping_dialogue(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / 'malformed.srt'
            source.write_text('1\n00:00:00,500 --> WRONG\nExact words.\n')
            with self.assertRaisesRegex(ValueError, 'Malformed'):
                runner.clip_subtitles(source, folder / 'result.srt', 15)


if __name__ == '__main__':
    unittest.main()
