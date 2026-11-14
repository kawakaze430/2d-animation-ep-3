"""Regression and deliberate-corruption checks for the standalone Episode 03 handoff."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('episode03_check', ROOT / 'Episode_03/check.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class Episode03ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.episode = self.root / 'Episode_03'
        shutil.copytree(ROOT / 'Episode_03', self.episode, ignore=shutil.ignore_patterns('__pycache__'))
        # The episode's production handoff links to the real shared pipeline guide.
        for guide in (ROOT / 'animation2d').rglob('*.md'):
            target = self.root / guide.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(guide, target)

    def mutate_text(self, relative, old, new):
        path = self.episode / relative
        content = path.read_text(encoding='utf-8')
        self.assertIn(old, content, f'fixture target changed: {relative}')
        path.write_text(content.replace(old, new, 1), encoding='utf-8')

    def test_full_standalone_handoff_passes(self):
        self.assertIn('240 dialogue/SRT cues match', CHECK.validate(self.root))

    def test_changed_character_preview_is_rejected(self):
        path = self.episode / 'assets/characters/DAN_portrait.jpg'
        data = bytearray(path.read_bytes())
        data[30] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'differs from committed reference baseline'):
            CHECK.validate(self.root)

    def test_missing_checksum_entry_is_rejected(self):
        path = self.episode / 'assets/reference_checksums.json'
        manifest = json.loads(path.read_text())
        del manifest['sha256']['assets/characters/DAN_portrait.jpg']
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'expected all 16'):
            CHECK.validate(self.root)

    def test_available_episode01_originals_are_still_compared(self):
        original = self.root / 'Episode_01/assets/environments/HOME_KITCHEN.jpg'
        original.parent.mkdir(parents=True)
        original.write_bytes(b'different original')
        with self.assertRaisesRegex(ValueError, 'differs from available Episode 01'):
            CHECK.validate(self.root)

    def test_corrupted_storyboard_crc_is_rejected(self):
        path = self.episode / 'assets/storyboards/BOARD_01.png'
        data = bytearray(path.read_bytes())
        data[20] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'invalid PNG chunk checksum'):
            CHECK.validate(self.root)

    def test_missing_storyboard_is_rejected(self):
        (self.episode / 'assets/storyboards/BOARD_01.png').unlink()
        with self.assertRaisesRegex(ValueError, 'expected exactly BOARD_01'):
            CHECK.validate(self.root)

    def test_prompt_dialogue_drift_is_rejected(self):
        path = self.episode / 'VIDEO_PROMPTS.md'
        text = path.read_text(encoding='utf-8')
        line = CHECK.shots(text, '##', 'prompts')[0]['dialogue'][0][1]
        self.mutate_text('VIDEO_PROMPTS.md', line, 'Changed contribution dialogue.')
        with self.assertRaisesRegex(ValueError, 'prompt dialogue differs from story'):
            CHECK.validate(self.root)

    def test_subtitle_outside_shot_is_rejected(self):
        self.mutate_text('SUBTITLES.srt', '00:00:00,500', '00:00:16,500')
        with self.assertRaisesRegex(ValueError, 'outside SHOT_001'):
            CHECK.validate(self.root)

    def test_changed_recipe_is_rejected(self):
        self.mutate_text('assets/overlays/PANCAKE_RECIPE.svg',
                         '2 cups all-purpose flour', '9 cups all-purpose flour')
        with self.assertRaisesRegex(ValueError, 'missing or changed recipe line'):
            CHECK.validate(self.root)

    def test_broken_document_link_is_rejected(self):
        path = self.episode / 'README.md'
        path.write_text(path.read_text(encoding='utf-8') + '\n[missing](missing.png)\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'broken relative link'):
            CHECK.validate(self.root)

    def test_external_svg_asset_is_rejected(self):
        path = self.episode / 'assets/overlays/TITLE_overlay.svg'
        text = path.read_text(encoding='utf-8').replace('</svg>', '<image href="https://example.com/asset.png"/></svg>')
        path.write_text(text, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'external asset reference'):
            CHECK.validate(self.root)

    def test_sync_check_rejects_stale_derived_document_without_rewriting(self):
        path = self.episode / 'VIDEO_PROMPTS.md'
        path.write_text('stale output\n', encoding='utf-8')
        result = subprocess.run([sys.executable, str(self.episode / 'sync.py'), '--check'],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('Stale derived documents: VIDEO_PROMPTS.md', result.stderr)
        self.assertEqual(path.read_text(encoding='utf-8'), 'stale output\n')


if __name__ == '__main__':
    unittest.main()
