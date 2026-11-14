#!/usr/bin/env python3
"""Kokoro CPU speech and independent Rhubarb mouth timelines for Episode 03.

Rendering/speech generation belongs in GitHub Actions. --validate checks the
manifest without importing torch or Kokoro, loading weights, or producing speech.
The six distinct preset voices are provisional casting, not approved child/adult
performances. Timing estimates become measured speech intervals after synthesis.
"""
from __future__ import annotations

import argparse
from importlib import metadata
import hashlib
import json
import math
from pathlib import Path
import subprocess
import wave

import numpy as np

ACTORS = ('DAN', 'MAYA', 'NINA', 'LEO', 'ELLA', 'MAX')
DEFAULT_VOICES = dict(zip(ACTORS, ('am_michael', 'af_heart', 'af_bella', 'am_fenrir', 'af_nova', 'am_puck')))
SAMPLE_RATE = 24000
ENGINE_SCHEMA = 'ep03-kokoro-cpu-v1'


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def content_key(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def voices_for(manifest: dict) -> dict:
    return {actor: manifest['characters'][actor]['voice']['preset'] for actor in ACTORS}


def validate_manifest(manifest: dict) -> None:
    characters = manifest.get('characters', {})
    if set(characters) != set(ACTORS):
        raise ValueError('Manifest must define exactly the six permanent actors')
    presets = []
    for actor in ACTORS:
        voice = characters[actor].get('voice', {})
        if voice.get('engine') != 'kokoro' or not isinstance(voice.get('preset'), str):
            raise ValueError(f'{actor}: expected an explicit Kokoro voice preset')
        if not voice['preset'].replace('_', '').isalnum():
            raise ValueError(f'{actor}: invalid voice preset name')
        speed = voice.get('speed', .94)
        if not isinstance(speed, (int, float)) or not math.isfinite(speed) or not .5 <= speed <= 1.3:
            raise ValueError(f'{actor}: preferred speed must be between 0.5 and 1.3')
        presets.append(voice['preset'])
    if len(set(presets)) != 6:
        raise ValueError('All six actors must have distinct voice presets')
    identities = set()
    for shot in manifest.get('shots', []):
        shot_id = shot.get('id', '')
        if len(shot_id) != 8 or not shot_id.startswith('SHOT_') or not shot_id[5:].isdigit() or shot_id in identities:
            raise ValueError(f'Invalid or duplicate shot identity: {shot_id!r}')
        identities.add(shot_id)
        if shot.get('duration') != 15:
            raise ValueError(f'{shot_id}: expected a fifteen-second shot')
        if not isinstance(shot.get('dialogue'), list) or not shot['dialogue']:
            raise ValueError(f'{shot_id}: no dialogue turns')
        previous_end = 0
        for turn in shot['dialogue']:
            if turn.get('speaker') not in ACTORS or turn['speaker'] not in shot.get('cast', ACTORS):
                raise ValueError(f'{shot_id}: dialogue speaker absent from visible cast')
            if not isinstance(turn.get('text'), str) or not turn['text'].strip():
                raise ValueError(f'{shot_id}: empty dialogue')
            start, end = turn.get('start'), turn.get('end')
            if (not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or
                    not math.isfinite(start) or not math.isfinite(end) or
                    not 0 <= previous_end <= start < end <= shot['duration']):
                raise ValueError(f'{shot_id}: overlapping, unordered or out-of-shot dialogue windows')
            previous_end = end
    if not identities:
        raise ValueError('Manifest contains no shots')


def model_fingerprint(models: Path, presets: dict, versions: dict | None = None) -> str:
    files = [models / 'config.json', models / 'kokoro-v1_0.pth']
    files.extend(models / f'{preset}.pt' for preset in sorted(set(presets.values())))
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(f'Missing verified local Kokoro file: {path}')
    if versions is None:
        versions = {name: metadata.version(name) for name in ('kokoro', 'torch', 'misaki', 'numpy')}
    return content_key({'schema': ENGINE_SCHEMA, 'versions': versions,
                        'files': {path.name: digest_file(path) for path in files}})


class KokoroEngine:
    """One CPU model, distinct local voice tensors, no automatic model downloads."""
    def __init__(self, models: Path, presets: dict):
        models = models.resolve()
        self.voice_paths = {preset: models / f'{preset}.pt' for preset in set(presets.values())}
        self.fingerprint = model_fingerprint(models, presets)
        # Heavy imports occur only after --validate has completed and real synthesis is requested.
        import torch
        from kokoro import KModel, KPipeline
        torch.set_num_threads(2)
        model = KModel(repo_id='hexgrad/Kokoro-82M', config=str(models / 'config.json'),
                       model=str(models / 'kokoro-v1_0.pth')).eval()
        self.pipeline = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M', model=model, device='cpu')
        self.tensors = {voice: torch.load(path, map_location='cpu', weights_only=True)
                        for voice, path in self.voice_paths.items()}

    def synthesize(self, text: str, voice: str, speed: float) -> np.ndarray:
        pieces = list(self.pipeline(text, voice=self.tensors[voice], speed=speed, split_pattern=None))
        if not pieces:
            raise RuntimeError('Kokoro produced no speech')
        return np.concatenate([piece.audio.detach().cpu().numpy() for piece in pieces])


def write_wave(path: Path, samples: np.ndarray, stereo=False):
    # Preserve original synthesis level; reject clipping rather than normalizing silently.
    if not np.isfinite(samples).all() or np.max(np.abs(samples), initial=0) > 1:
        raise ValueError('Speech samples are non-finite or would clip PCM output')
    pcm = np.round(samples * 32767).astype('<i2')
    if stereo:
        pcm = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), 'wb') as output:
        output.setframerate(SAMPLE_RATE)
        output.setnchannels(2 if stereo else 1)
        output.setsampwidth(2)
        output.writeframes(pcm.tobytes())


class RhubarbAligner:
    def __init__(self, executable: Path):
        self.executable = executable.resolve()
        if not self.executable.is_file():
            raise FileNotFoundError(self.executable)
        # Companion phonetic/dictionary resources also affect alignment output.
        files = [self.executable]
        resource = self.executable.parent / 'res'
        if resource.is_dir():
            files.extend(path for path in sorted(resource.rglob('*')) if path.is_file())
        self.fingerprint = content_key({str(path.relative_to(self.executable.parent)): digest_file(path) for path in files})

    def align(self, wav: Path, dialogue: str, work: Path) -> list:
        text = work.with_suffix('.txt')
        text.write_text(dialogue)
        subprocess.run([str(self.executable), '-r', 'pocketSphinx', '-f', 'json', '--threads', '1',
                        '-q', '-d', str(text), '-o', str(work), str(wav)], check=True)
        return json.loads(work.read_text())['mouthCues']


def prepared_samples(samples: np.ndarray) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ValueError('Synthesis must produce a finite, nonempty mono waveform at 24 kHz')
    active = np.flatnonzero(np.abs(samples) > .003)
    if not len(active):
        raise ValueError('Synthesis returned silence')
    # Only trim engine silence outside the utterance, never crop spoken words to fit.
    margin = round(.04 * SAMPLE_RATE)
    samples = samples[max(0, active[0] - margin):min(len(samples), active[-1] + margin + 1)].copy()
    fade = min(round(.006 * SAMPLE_RATE), len(samples) // 3)
    samples[:fade] *= np.linspace(0, 1, fade)
    samples[-fade:] *= np.linspace(1, 0, fade)
    if np.max(np.abs(samples)) > 1:
        raise ValueError('Kokoro output exceeds PCM full scale')
    return samples


def cached_speech(engine, cache: Path, text: str, voice: str, speed: float) -> tuple[np.ndarray, str]:
    key = content_key({'engine': engine.fingerprint, 'text': text, 'voice': voice,
                       'speed': speed, 'schema': ENGINE_SCHEMA})
    path, stamp = cache / f'{key}.npy', cache / f'{key}.json'
    if path.is_file() and stamp.is_file():
        record = json.loads(stamp.read_text())
        if record.get('sha256') == digest_file(path):
            return np.load(path, allow_pickle=False), key
    samples = prepared_samples(engine.synthesize(text, voice, speed))
    np.save(path, samples, allow_pickle=False)
    stamp.write_text(json.dumps({'sha256': digest_file(path)}) + '\n')
    return samples, key


def fit_turn(engine, cache: Path, turn: dict, voice: str, preferred_speed: float) -> tuple[np.ndarray, float, str]:
    window = turn['end'] - turn['start']
    speed = preferred_speed
    for _attempt in range(4):
        samples, key = cached_speech(engine, cache, turn['text'], voice, speed)
        duration = len(samples) / SAMPLE_RATE
        if duration <= window:
            return samples, speed, key
        next_speed = min(1.3, round(speed * duration / window * 1.015, 5))
        if next_speed <= speed:
            break
        speed = next_speed
    raise RuntimeError(f"{turn['speaker']} speech cannot fit {window:.3f}s at bounded speed <=1.3; revise the shot timing/performance")


def gated_cues(raw: list, intervals: list[tuple[float, float]], duration: float) -> list:
    active = []
    for cue in raw:
        value, start, end = cue.get('value'), cue.get('start'), cue.get('end')
        if not isinstance(value, str) or value not in tuple('ABCDEFGHX') or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError('Rhubarb returned malformed mouth cues')
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= duration + .05:
            raise ValueError('Rhubarb returned out-of-shot mouth cues')
        if value == 'X':
            continue
        for begin, finish in intervals:
            a, b = max(start, begin), min(end, finish)
            if b > a:
                active.append({'start': round(a, 6), 'end': round(b, 6), 'value': value})
    active.sort(key=lambda cue: (cue['start'], cue['end']))
    result, cursor = [], 0.0
    for cue in active:
        if cue['start'] < cursor - .000001:
            raise ValueError('Rhubarb returned overlapping active mouth cues')
        if cue['start'] > cursor:
            result.append({'start': cursor, 'end': cue['start'], 'value': 'X'})
        result.append(cue)
        cursor = cue['end']
    if cursor < duration:
        result.append({'start': cursor, 'end': duration, 'value': 'X'})
    return result


def timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def produce(manifest: dict, shot_ids: list[str], output: Path, engine, aligner) -> list[dict]:
    validate_manifest(manifest)
    selected = [shot for shot in manifest['shots'] if shot['id'] in shot_ids]
    if set(shot_ids) != {shot['id'] for shot in selected}:
        raise ValueError('One or more requested shots are absent from the manifest')
    cache = output / '.speech_cache'
    cache.mkdir(parents=True, exist_ok=True)
    voices, reports = voices_for(manifest), []
    for shot in selected:
        folder = output / shot['id']
        folder.mkdir(parents=True, exist_ok=True)
        # A failed rerun must not leave an old success record beside partial new output.
        (folder / 'timings.json').unlink(missing_ok=True)
        tracks = {actor: np.zeros(round(shot['duration'] * SAMPLE_RATE), dtype=np.float32) for actor in ACTORS}
        timings = []
        for turn in shot['dialogue']:
            actor = turn['speaker']
            speed = manifest['characters'][actor]['voice'].get('speed', .94)
            samples, actual_speed, key = fit_turn(engine, cache, turn, voices[actor], speed)
            offset = round(turn['start'] * SAMPLE_RATE)
            tracks[actor][offset:offset + len(samples)] += samples
            timings.append({'speaker': actor, 'text': turn['text'], 'voice': voices[actor],
                            'start': offset / SAMPLE_RATE, 'end': (offset + len(samples)) / SAMPLE_RATE,
                            'window_start': turn['start'], 'window_end': turn['end'],
                            'speed': actual_speed, 'synthesis_cache_key': key})
        mix = np.sum(list(tracks.values()), axis=0)
        write_wave(folder / 'narration.wav', mix, stereo=True)
        for actor, track in tracks.items():
            wav = folder / f'{actor}.wav'
            write_wave(wav, track)
            turns = [turn for turn in timings if turn['speaker'] == actor]
            intervals = [(turn['start'], turn['end']) for turn in turns]
            text = '\n'.join(turn['text'] for turn in turns)
            cue_key = content_key({'audio': digest_file(wav), 'rhubarb': aligner.fingerprint,
                                   'text': text, 'intervals': intervals, 'schema': ENGINE_SCHEMA})
            cue_cache = cache / f'{cue_key}.cues.json'
            if cue_cache.is_file():
                cached = json.loads(cue_cache.read_text())
                if cached.get('cues_sha256') != content_key(cached.get('raw_cues')):
                    raise ValueError('Rhubarb cue cache integrity mismatch')
                raw = cached['raw_cues']
            else:
                raw = aligner.align(wav, text, folder / f'{actor}.rhubarb.raw.json') if turns else []
                cue_cache.write_text(json.dumps({'raw_cues': raw, 'cues_sha256': content_key(raw)}))
            cues = gated_cues(raw, intervals, shot['duration'])
            if turns and not any(cue['value'] != 'X' for cue in cues):
                raise RuntimeError(f'{actor}: Rhubarb produced no active cues for the measured speech')
            (folder / f'{actor}.cues.json').write_text(json.dumps({'actor': actor, 'shot': shot['id'],
                'timebase': 'shot-local seconds', 'active': bool(turns), 'voice': voices[actor],
                'cache_key': cue_key, 'mouthCues': cues}, indent=2) + '\n')
        subtitles = []
        for index, turn in enumerate(timings, 1):
            subtitles.extend([str(index), f"{timestamp(turn['start'])} --> {timestamp(turn['end'])}", turn['text'], ''])
        (folder / 'dialogue.srt').write_text('\n'.join(subtitles) + '\n')
        report = {'shot': shot['id'], 'duration': shot['duration'], 'sample_rate': SAMPLE_RATE,
                  'timebase': 'shot-local seconds', 'status': 'synthesized provisional six-voice casting; creator review pending',
                  'engine_fingerprint': engine.fingerprint, 'rhubarb_fingerprint': aligner.fingerprint,
                  'voices': voices, 'dialogue': timings, 'narration_sha256': digest_file(folder / 'narration.wav')}
        (folder / 'timings.json').write_text(json.dumps(report, indent=2) + '\n')
        reports.append(report)
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--shot', default='SHOT_001', help='SHOT_001 through SHOT_080, or all')
    parser.add_argument('--models', type=Path)
    parser.add_argument('--rhubarb', type=Path)
    parser.add_argument('--output', type=Path, default=Path('build/episode03/audio'))
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    validate_manifest(manifest)
    shots = [shot['id'] for shot in manifest['shots']] if args.shot == 'all' else [args.shot]
    if not set(shots) <= {shot['id'] for shot in manifest['shots']}:
        parser.error('Requested shot does not exist in the manifest')
    if args.validate:
        print(json.dumps({'status': 'manifest validated; synthesis unrun', 'shots': shots,
                          'voices': voices_for(manifest)}, indent=2))
        return
    if args.models is None or args.rhubarb is None:
        parser.error('--models and --rhubarb are required for synthesis')
    engine = KokoroEngine(args.models, voices_for(manifest))
    aligner = RhubarbAligner(args.rhubarb)
    reports = produce(manifest, shots, args.output, engine, aligner)
    print(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
