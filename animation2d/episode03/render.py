"""Export a selected manifest-driven Episode 03 shot through FFmpeg.

Production requires real character part rigs and generated shot audio. Blocking
exports remain visibly labelled; they never stand in for approved performances.
Full movie rendering belongs on the GitHub runner, not the review server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import wave

from .engine import render_frame

ROOT = Path(__file__).resolve().parents[2]


def timestamp(seconds):
    value = round(seconds * 1000)
    return f'{value//3600000:02}:{value//60000%60:02}:{value//1000%60:02},{value%1000:03}'


def planned_subtitles(shot):
    return '\n\n'.join(
        f'{i}\n{timestamp(turn["start"])} --> {timestamp(turn["end"])}\n'
        f'{turn["speaker"]}: {turn["text"]}'
        for i, turn in enumerate(shot['dialogue'], 1)
    ) + '\n'


def inspect(path, duration, fps, size):
    response = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                               '-show_format', '-of', 'json', str(path)],
                              capture_output=True, text=True, check=True)
    media = json.loads(response.stdout)
    video = next(stream for stream in media['streams'] if stream['codec_type'] == 'video')
    audio = next(stream for stream in media['streams'] if stream['codec_type'] == 'audio')
    if (video['width'], video['height']) != size or video['codec_name'] != 'h264':
        raise ValueError('Video size or codec mismatch')
    if int(video['nb_read_frames']) != round(duration * fps) or video['avg_frame_rate'] != f'{fps}/1':
        raise ValueError('Video frame count or frame rate mismatch')
    if abs(float(media['format']['duration']) - duration) > .04:
        raise ValueError('Video duration mismatch')
    if audio['codec_name'] != 'aac' or audio['channels'] != 2:
        raise ValueError('Video must include stereo AAC audio')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'], check=True)
    return {'duration': duration, 'fps': fps, 'frames': round(duration * fps),
            'width': size[0], 'height': size[1], 'video': 'h264', 'audio': 'aac stereo',
            'full_decode': 'passed'}


def render(manifest_path, shot_id, output, mode='blocking', audio_dir=None, size=(1280,720)):
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    manifest = json.loads(manifest_path.read_text())
    manifest['__base_dir__'] = str(ROOT)
    shot = next((shot for shot in manifest['shots'] if shot['id'] == shot_id), None)
    if shot is None:
        raise ValueError(f'Unknown shot: {shot_id}')
    fps, duration = manifest.get('fps', 24), shot['duration']
    if fps != 24 or duration != 15 or mode not in ('blocking','production'):
        raise ValueError('Episode 03 exports require a supported mode, 24 fps and 15-second shots')
    # Resolve assets before starting a potentially expensive encode.
    first = render_frame(manifest, shot_id, 0, mode=mode, size=size, audio_dir=audio_dir)
    audio_path = Path(audio_dir) / shot_id / 'narration.wav' if audio_dir else None
    if mode == 'production' and (audio_path is None or not audio_path.is_file()):
        raise ValueError('Production needs generated, shot-specific narration.wav; use the Kokoro Actions option')
    if audio_path and audio_path.exists():
        with wave.open(str(audio_path), 'rb') as source:
            if abs(source.getnframes() / source.getframerate() - duration) > .02:
                raise ValueError('Shot-specific narration duration mismatch')
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f'{shot_id}_{mode}.mp4'
    partial = output / f'{shot_id}_{mode}.partial.mp4'
    subtitle = output / f'{shot_id}.srt'
    performed = Path(audio_dir) / shot_id / 'dialogue.srt' if audio_dir else None
    subtitle.write_text(performed.read_text() if performed and performed.exists() else planned_subtitles(shot))
    command = ['ffmpeg','-hide_banner','-loglevel','error','-y', '-f','rawvideo','-pix_fmt','rgb24',
               '-s',f'{size[0]}x{size[1]}','-r',str(fps),'-i','pipe:0']
    if audio_path and audio_path.exists():
        command += ['-i', str(audio_path)]
    else:
        command += ['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
    command += ['-i',str(subtitle),'-map','0:v:0','-map','1:a:0','-map','2:s:0',
                '-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-pix_fmt','yuv420p',
                '-c:a','aac','-ac','2','-ar','48000','-c:s','mov_text','-t',str(duration),
                '-frames:v',str(round(duration*fps)),'-movflags','+faststart',
                '-metadata',f'title=Episode 03 {shot_id} {mode}; creative review pending',str(partial)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    samples = []
    try:
        for index in range(round(duration*fps)):
            frame = first if index == 0 else render_frame(manifest,shot_id,index/fps,mode=mode,size=size,audio_dir=audio_dir)
            pixels = frame.convert('RGB').tobytes()
            if index in (0,180,359):
                samples.append(hashlib.sha256(pixels).hexdigest())
            process.stdin.write(pixels)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError('FFmpeg failed while encoding Episode 03')
    except BaseException:
        process.kill()
        process.wait()
        partial.unlink(missing_ok=True)
        raise
    report = inspect(partial,duration,fps,size)
    partial.replace(destination)
    report.update(shot=shot_id, mode=mode, creative_review_pending=True,
                  audio='Kokoro shot track' if audio_path and audio_path.exists() else 'silent blocking',
                  manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                  video_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                  sampled_frame_sha256=samples)
    destination.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print(destination,flush=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=Path('animation2d/episode03/shots.json'))
    parser.add_argument('--shot',default='SHOT_001')
    parser.add_argument('--mode',choices=['blocking','production'],default='blocking')
    parser.add_argument('--audio-dir',type=Path)
    parser.add_argument('--output',type=Path,default=Path('build/episode03/video'))
    args = parser.parse_args()
    render(args.manifest,args.shot,args.output,args.mode,args.audio_dir)


if __name__ == '__main__':
    main()
