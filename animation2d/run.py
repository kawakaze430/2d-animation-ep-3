#!/usr/bin/env python3
"""Prepare and run the original articulated 2D animation in isolated build copies.

The included puppet demonstrates the rendering pipeline. It is not the six-person
Episode 03 cast, and its morning-routine smoke video must never be labeled EP3.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = HERE / "project"


def source_digest(episode='original') -> str:
    digest = hashlib.sha256()
    digest.update(b'animation2d-build-schema-v1')
    if episode == '02':
        # Episode 02's lesson and renderer patches are build inputs, not cacheable prose.
        digest.update((HERE / 'episode2' / 'prepare_episode.py').read_bytes())
    for path in sorted(SOURCE.rglob('*')):
        if path.is_file() and not set(path.relative_to(SOURCE).parts) & {'__pycache__', 'output', 'models', 'tools'}:
            digest.update(str(path.relative_to(SOURCE)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def project_path(episode: str) -> Path:
    return ROOT / "build" / ("original" if episode == "original" else "episode02") / "project"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(episode: str, refresh=False) -> Path:
    project = project_path(episode)
    marker = project.parent / "prepared.json"
    stamp = {"episode": episode, "source_sha256": source_digest(episode)}
    if project.exists():
        if not marker.is_file():
            raise RuntimeError(f"Refusing to replace unrecognized files at {project}")
        if not refresh:
            if json.loads(marker.read_text()) != stamp:
                raise RuntimeError("Source changed; use prepare --refresh to rebuild the disposable copy")
            print(f"Reusing {project}", flush=True)
            return project
    project.parent.mkdir(parents=True, exist_ok=True)
    if episode == '02':
        module = load_module(HERE / 'episode2' / 'prepare_episode.py', 'episode02_prepare')
        module.main(source=SOURCE, project=project, refresh=refresh)
        # Still previews work before speech generation. Rendering refuses absent narration.
        (project / 'audio' / 'mouth_cues.json').write_text('{"mouthCues": []}\n')
    else:
        if project.exists():
            shutil.rmtree(project)
        shutil.copytree(SOURCE, project, ignore=shutil.ignore_patterns('__pycache__', 'output', 'models', 'tools'))
    marker.write_text(json.dumps(stamp, indent=2) + '\n')
    print(f"Prepared {project}", flush=True)
    return project


def require_audio(project: Path) -> Path:
    audio = project / 'audio' / 'narration.wav'
    if not audio.is_file():
        audio = audio.with_suffix('.flac')
    for required in (audio, project / 'captions.srt', project / 'audio' / 'mouth_cues.json'):
        if not required.is_file():
            raise RuntimeError(f"Missing {required.name}; run voice for this episode before rendering")
    return audio


def clip_subtitles(source: Path, target: Path, seconds: int) -> Path:
    """Clip cue packets before muxing; FFmpeg -t does not shorten mov_text cues.

    A cue starting at 13.340 and ending at 15.239 otherwise makes a fifteen-second
    MP4 report 15.239 seconds even though its audio/video tracks end at 15.000.
    Preserve exact dialogue text while bounding every retained cue to this export.
    """
    def milliseconds(value):
        hour, minute, second, fraction = map(int, re.split('[:,]', value))
        if minute >= 60 or second >= 60:
            raise ValueError(f'Invalid subtitle timestamp: {value}')
        return ((hour * 60 + minute) * 60 + second) * 1000 + fraction

    def timestamp(value):
        second, fraction = divmod(value, 1000)
        minute, second = divmod(second, 60)
        hour, minute = divmod(minute, 60)
        return f'{hour:02}:{minute:02}:{second:02},{fraction:03}'

    limit = round(seconds * 1000)
    result = []
    text = source.read_text(encoding='utf-8-sig').replace('\r\n', '\n').strip()
    for block in re.split(r'\n\s*\n', text):
        lines = block.splitlines()
        timing = re.fullmatch(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})',
                              lines[1]) if len(lines) >= 3 and lines[0].isdigit() else None
        if not timing:
            raise ValueError('Malformed subtitle block; refusing to publish incomplete captions')
        begin, end = map(milliseconds, timing.groups())
        if begin >= end:
            raise ValueError('Subtitle cue has nonpositive duration')
        if begin < limit:
            result.append(f'{len(result)+1}\n{timestamp(begin)} --> {timestamp(min(end, limit))}\n' + '\n'.join(lines[2:]))
    if not result:
        raise ValueError('No subtitle cues fall inside the selected render duration')
    target.write_text('\n\n'.join(result) + '\n', encoding='utf-8')
    return target


def inspect_video(path: Path, seconds: int) -> dict:
    result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                             '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    video = next(stream for stream in data['streams'] if stream['codec_type'] == 'video')
    audio = next(stream for stream in data['streams'] if stream['codec_type'] == 'audio')
    if (video['width'], video['height'], video['codec_name'], int(video['nb_read_frames'])) != (1920, 1080, 'h264', 24*seconds):
        raise RuntimeError('Encoded video dimensions/codec/frame count do not match the selected render')
    if video['avg_frame_rate'] != '24/1' or abs(float(data['format']['duration']) - seconds) > .03:
        raise RuntimeError(f"Encoded video timing does not match the selected render: expected {seconds}s at 24fps; "
                           f"found {data['format']['duration']}s at {video['avg_frame_rate']}fps")
    if audio['codec_name'] != 'aac' or audio['channels'] != 2:
        raise RuntimeError('Encoded audio is not stereo AAC')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'], check=True)
    return {'duration': float(data['format']['duration']), 'width': video['width'],
            'height': video['height'], 'frames': int(video['nb_read_frames']), 'fps': 24,
            'video_codec': video['codec_name'], 'audio_codec': audio['codec_name'],
            'audio_channels': audio['channels'], 'full_decode': 'passed'}


def smoke(project: Path, episode: str, seconds: int) -> Path:
    audio = require_audio(project)
    sys.path.insert(0, str(project))
    renderer = load_module(project / 'action_render.py', 'isolated_action_render')
    output = project / 'output'
    output.mkdir(exist_ok=True)
    partial = output / f'pipeline_smoke_{seconds}s.partial.mp4'
    result = output / f'pipeline_smoke_{seconds}s.mp4'
    subtitles = clip_subtitles(project / 'captions.srt', output / f'pipeline_smoke_{seconds}s.srt', seconds)
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', '-s', '1920x1080', '-r', '24', '-i', 'pipe:0',
               '-i', str(audio), '-i', str(subtitles),
               '-map', '0:v:0', '-map', '1:a:0', '-map', '2:s:0', '-c:v', 'libx264',
               '-preset', 'veryfast', '-crf', '19', '-threads', '2', '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-ac', '2', '-b:a', '192k', '-c:s', 'mov_text', '-t', str(seconds),
               '-metadata', 'title=Original 2D morning-routine pipeline smoke; not Episode 03',
               '-movflags', '+faststart', str(partial)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    sampled = []
    try:
        for index in range(24 * seconds):
            frame = renderer.frame(index / 24)
            pixels = frame.tobytes()
            if index in (0, 12 * seconds, 24 * seconds - 1):
                # Exclude the caption strip/progress bar: UI motion alone must not pass.
                sampled.append(hashlib.sha256(frame.crop((0, 0, 1920, 930)).tobytes()).hexdigest())
            process.stdin.write(pixels)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError('FFmpeg rejected rendered frames')
    except BaseException:
        process.kill()
        process.wait()
        raise
    if len(set(sampled)) < 2:
        raise RuntimeError('Sampled source frames are static; renderer smoke failed')
    report = inspect_video(partial, seconds)
    partial.replace(result)
    report.update(episode=episode, status='existing 2D pipeline smoke, not Episode 03 production',
                  source_frame_sha256=sampled, output_sha256=hashlib.sha256(result.read_bytes()).hexdigest())
    result.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(result, flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'preview', 'render', 'smoke', 'voice'):
        command = sub.add_parser(name)
        command.add_argument('--episode', choices=['original', '02'], default='original')
        if name == 'prepare':
            command.add_argument('--refresh', action='store_true')
        if name in ('render', 'voice'):
            command.add_argument('--workers', type=int, choices=range(1, 5), default=2)
        if name == 'voice':
            command.add_argument('--model-dir', type=Path, required=True)
            command.add_argument('--rhubarb', type=Path, required=True)
            command.add_argument('--speed', type=float, default=.85)
        if name == 'smoke':
            command.add_argument('--seconds', type=int, choices=range(1, 121), default=15)
    args = parser.parse_args()
    project = prepare(args.episode, getattr(args, 'refresh', False))
    if args.command == 'prepare':
        return
    if args.command == 'smoke':
        smoke(project, args.episode, args.seconds)
        return
    if args.command == 'preview':
        command = ['action_render.py', '--preview']
    elif args.command == 'voice':
        command = ['make_voice.py', '--model-dir', str(args.model_dir.resolve()),
                   '--rhubarb', str(args.rhubarb.resolve()), '--workers', str(args.workers), '--speed', str(args.speed)]
    else:
        require_audio(project)
        command = ['render_all.py', '--workers', str(args.workers)]
    subprocess.run([sys.executable, *command], cwd=project, check=True)


if __name__ == '__main__':
    main()
