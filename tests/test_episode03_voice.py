"""Contract tests with injected synthesis/alignment doubles; no model downloads.

These verify speaker isolation, exact dialogue, bounded timing and cache input
identity. They do not claim actual Kokoro performance or Rhubarb accuracy.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import wave

import numpy as np

from animation2d.episode03 import voice


def manifest():
    return {'characters': {actor: {'voice': {'engine': 'kokoro', 'preset': preset, 'speed': .94}}
                           for actor, preset in voice.DEFAULT_VOICES.items()},
            'shots': [{'id': 'SHOT_001', 'duration': 15, 'cast': list(voice.ACTORS),
                       'dialogue': [{'speaker': actor, 'text': f'Exact dialogue for {actor}.',
                                     'start': .5 + 2*i, 'end': 2 + 2*i}
                                    for i, actor in enumerate(voice.ACTORS)]}]}


class FakeEngine:
    def __init__(self, duration=.75):
        self.fingerprint = 'model-config-voice-content-v1'
        self.duration = duration
        self.calls = []

    def synthesize(self, text, preset, speed):
        self.calls.append((text, preset, speed))
        t = np.arange(round(self.duration * voice.SAMPLE_RATE)) / voice.SAMPLE_RATE
        return (.2 * np.sin(t * 2 * np.pi * 180)).astype(np.float32)


class FakeAligner:
    def __init__(self):
        self.fingerprint = 'rhubarb-binary-and-resource-content-v1'
        self.calls = []

    def align(self, wav, dialogue, work):
        self.calls.append((wav.name, dialogue))
        # Intentionally overbroad recognizer output must be gated to this actor's speech.
        return [{'start': 0, 'end': 15, 'value': 'A'}]


class Episode03VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.manifest = manifest()
        self.engine = FakeEngine()
        self.aligner = FakeAligner()

    def tearDown(self):
        self.temp.cleanup()

    def produce(self):
        return voice.produce(self.manifest, ['SHOT_001'], self.output, self.engine, self.aligner)[0]

    def test_each_exact_turn_uses_its_own_voice_and_real_measured_time(self):
        report = self.produce()
        self.assertEqual([call[1] for call in self.engine.calls], list(voice.DEFAULT_VOICES.values()))
        self.assertEqual([call[0] for call in self.engine.calls],
                         [turn['text'] for turn in self.manifest['shots'][0]['dialogue']])
        folder = self.output / 'SHOT_001'
        with wave.open(str(folder / 'narration.wav'), 'rb') as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getnframes()), (24000, 2, 15*24000))
        for turn in report['dialogue']:
            self.assertGreater(turn['end'], turn['start'])
            self.assertLessEqual(turn['end'], turn['window_end'])
            self.assertIn(turn['text'], (folder / 'dialogue.srt').read_text())

    def test_each_actors_audio_and_active_mouth_cues_stay_inside_its_turns(self):
        report = self.produce()
        for actor in voice.ACTORS:
            turn = next(turn for turn in report['dialogue'] if turn['speaker'] == actor)
            folder = self.output / 'SHOT_001'
            with wave.open(str(folder / f'{actor}.wav'), 'rb') as wav:
                pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
            before, after = round(turn['start'] * 24000), round(turn['end'] * 24000)
            self.assertTrue(np.all(pcm[:before] == 0))
            self.assertTrue(np.all(pcm[after:] == 0))
            self.assertGreater(np.abs(pcm[before:after]).max(), 100)
            cues = json.loads((folder / f'{actor}.cues.json').read_text())['mouthCues']
            for cue in cues:
                if cue['value'] != 'X':
                    self.assertGreaterEqual(cue['start'], turn['start'] - .000001)
                    self.assertLessEqual(cue['end'], turn['end'] + .000001)
            self.assertEqual(cues[0]['start'], 0)
            self.assertEqual(cues[-1]['end'], 15)

    def test_unseen_or_silent_actors_receive_no_speech_or_active_cues(self):
        self.manifest['shots'][0]['dialogue'] = self.manifest['shots'][0]['dialogue'][:1]
        self.manifest['shots'][0]['cast'] = ['DAN']
        self.produce()
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual(len(self.aligner.calls), 1)
        for actor in voice.ACTORS[1:]:
            path = self.output / 'SHOT_001' / f'{actor}.cues.json'
            self.assertEqual(json.loads(path.read_text())['mouthCues'], [{'start': 0.0, 'end': 15, 'value': 'X'}])

    def test_rejects_overlap_cross_cast_speaker_and_duplicate_voice(self):
        bad = copy.deepcopy(self.manifest)
        bad['shots'][0]['dialogue'][1]['start'] = .7
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            voice.validate_manifest(bad)
        bad = copy.deepcopy(self.manifest)
        bad['shots'][0]['cast'] = ['DAN']
        with self.assertRaisesRegex(ValueError, 'visible cast'):
            voice.validate_manifest(bad)
        bad = copy.deepcopy(self.manifest)
        bad['characters']['MAYA']['voice']['preset'] = bad['characters']['DAN']['voice']['preset']
        with self.assertRaisesRegex(ValueError, 'distinct'):
            voice.validate_manifest(bad)

    def test_overflow_fails_without_truncating_words_or_publishing_success(self):
        self.engine.duration = 10
        with self.assertRaisesRegex(RuntimeError, 'cannot fit'):
            self.produce()
        self.assertFalse((self.output / 'SHOT_001' / 'timings.json').exists())
        self.assertLessEqual(len(self.engine.calls), 4)
        self.assertTrue(all(call[2] <= 1.3 for call in self.engine.calls))

    def test_cache_invalidation_covers_text_voice_model_and_rhubarb_content(self):
        self.produce()
        self.assertEqual((len(self.engine.calls), len(self.aligner.calls)), (6, 6))
        self.produce()
        self.assertEqual((len(self.engine.calls), len(self.aligner.calls)), (6, 6))
        self.manifest['shots'][0]['dialogue'][0]['text'] += ' Changed exact words.'
        self.produce()
        self.assertEqual((len(self.engine.calls), len(self.aligner.calls)), (7, 7))
        self.manifest['characters']['DAN']['voice']['preset'] = 'am_adam'
        self.produce()
        self.assertEqual(len(self.engine.calls), 8)
        self.engine.fingerprint = 'model-or-voice-weight-content-v2'
        self.produce()
        self.assertEqual(len(self.engine.calls), 14)
        previous_alignments = len(self.aligner.calls)
        self.aligner.fingerprint = 'rhubarb-binary-or-resources-content-v2'
        self.produce()
        self.assertEqual(len(self.engine.calls), 14)
        self.assertEqual(len(self.aligner.calls), previous_alignments + 6)

    def test_nonfinite_or_silent_synthesis_cannot_be_saved_as_success(self):
        for samples in (np.zeros(24000), np.full(24000, np.nan)):
            with self.subTest(silent=not np.isnan(samples).any()), self.assertRaises(ValueError):
                voice.prepared_samples(samples)

    def test_failed_alignment_cannot_pass_with_all_closed_mouths(self):
        self.aligner.align = lambda wav, text, work: [{'start': 0, 'end': 15, 'value': 'X'}]
        with self.assertRaisesRegex(RuntimeError, 'no active cues'):
            self.produce()
        self.assertFalse((self.output / 'SHOT_001' / 'timings.json').exists())

    def test_real_model_fingerprint_changes_when_voice_or_model_bytes_change(self):
        models = self.output / 'models'
        models.mkdir()
        for name in ('config.json', 'kokoro-v1_0.pth', *(f'{preset}.pt' for preset in voice.DEFAULT_VOICES.values())):
            (models / name).write_bytes(f'fixture bytes for {name}'.encode())
        first = voice.model_fingerprint(models, voice.DEFAULT_VOICES, versions={'kokoro': 'fixture-v1'})
        (models / 'af_heart.pt').write_bytes(b'changed voice tensor fixture')
        second = voice.model_fingerprint(models, voice.DEFAULT_VOICES, versions={'kokoro': 'fixture-v1'})
        self.assertNotEqual(first, second)
        (models / 'kokoro-v1_0.pth').write_bytes(b'changed model fixture')
        third = voice.model_fingerprint(models, voice.DEFAULT_VOICES, versions={'kokoro': 'fixture-v1'})
        self.assertNotEqual(second, third)
        self.assertNotEqual(third, voice.model_fingerprint(models, voice.DEFAULT_VOICES, versions={'kokoro': 'fixture-v2'}))


if __name__ == '__main__':
    unittest.main()
