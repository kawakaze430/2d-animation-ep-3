#!/usr/bin/env python3
"""Fetch official Kokoro files and the pinned Rhubarb Linux release for CPU speech.

TLS verification stays enabled. Model files (including cache hits) are checked
against metadata at a fixed upstream commit; Rhubarb is pinned to bytes obtained
from its official HTTPS release. This script does not claim publisher signatures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import zipfile

MODEL_REPO = 'hexgrad/Kokoro-82M'
MODEL_FILES = ('config.json', 'kokoro-v1_0.pth', 'voices/af_heart.pt')
VOICE_PRESETS = ('af_heart', 'af_bella', 'af_nova', 'am_michael', 'am_fenrir', 'am_puck')
RHUBARB_NAME = 'Rhubarb-Lip-Sync-1.14.0-Linux.zip'
RHUBARB_URL = f'https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/{RHUBARB_NAME}'
# Baseline from the official HTTPS release, independently rechecked on downloads.
RHUBARB_SHA256 = 'a9a9074862cff47b2d59b8bf399a678a3b0b74f9452ad6ad94cb292913dd8667'


def digest_file(path: Path, algorithm='sha256', git_blob=False) -> str:
    digest = hashlib.new(algorithm)
    if git_blob:
        digest.update(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected: str, algorithm='sha256', git_blob=False):
    actual = digest_file(path, algorithm, git_blob)
    if actual != expected:
        raise ValueError(f'{path.name}: {algorithm} integrity mismatch (expected {expected}, got {actual})')


def safe_zip_members(archive: zipfile.ZipFile):
    """Reject absolute paths, traversal, symlinks and unbounded archive contents."""
    if sum(info.file_size for info in archive.infolist()) > 1024 * 1024 * 1024:
        raise ValueError('Rhubarb archive expands beyond the 1 GiB limit')
    for info in archive.infolist():
        name = info.filename
        path = PurePosixPath(name)
        mode = info.external_attr >> 16
        if ('\\' in name or path.is_absolute() or '..' in path.parts or
                not path.parts or ':' in path.parts[0] or stat.S_ISLNK(mode)):
            raise ValueError(f'Unsafe archive member: {name!r}')
        yield info


def install_rhubarb(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rhubarb-download-') as temp:
        archive_path = Path(temp) / RHUBARB_NAME
        request = urllib.request.Request(RHUBARB_URL, headers={'User-Agent': 'animation2d-setup/1.0'})
        with urllib.request.urlopen(request, timeout=120) as source, archive_path.open('wb') as target:
            size = 0
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > 256 * 1024 * 1024:
                    raise ValueError('Rhubarb download exceeds the 256 MiB limit')
                target.write(chunk)
        verify_file(archive_path, RHUBARB_SHA256)
        staging = Path(temp) / 'extracted'
        staging.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            members = list(safe_zip_members(archive))
            for member in members:
                target = staging.joinpath(*PurePosixPath(member.filename).parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open('wb') as dest:
                        shutil.copyfileobj(source, dest)
        executables = [path for path in staging.rglob('rhubarb') if path.is_file()]
        if len(executables) != 1:
            raise ValueError('Expected exactly one Rhubarb executable in the official archive')
        relative = executables[0].relative_to(staging)
        destination = output / 'rhubarb'
        if destination.exists():
            # This is a generated tool installation, never a source checkout.
            shutil.rmtree(destination)
        shutil.copytree(staging, destination)
        executable = destination / relative
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        return executable.resolve()


def model_files(voices=('af_heart',)):
    if not voices or any(voice not in VOICE_PRESETS for voice in voices):
        raise ValueError('Select supported Kokoro voice presets')
    return ('config.json', 'kokoro-v1_0.pth', *(f'voices/{voice}.pt' for voice in dict.fromkeys(voices)))


def install_models(output: Path, voices=('af_heart',)) -> dict:
    files = model_files(voices)
    from huggingface_hub import HfApi, hf_hub_download

    info = HfApi().model_info(MODEL_REPO, files_metadata=True, token=False)
    revision = info.sha
    if not revision or len(revision) != 40:
        raise ValueError('Upstream model commit is missing or malformed')
    # Resolve the listing at the same commit to avoid a moving-main race.
    info = HfApi().model_info(MODEL_REPO, revision=revision, files_metadata=True, token=False)
    siblings = {item.rfilename: item for item in info.siblings}
    output.mkdir(parents=True, exist_ok=True)
    report = {'repository': MODEL_REPO, 'revision': revision, 'files': {}}
    for name in files:
        item = siblings[name]
        cached = Path(hf_hub_download(MODEL_REPO, name, revision=revision, token=False))
        lfs = getattr(item, 'lfs', None)
        if lfs:
            expected = lfs['sha256'] if isinstance(lfs, dict) else lfs.sha256
            verify_file(cached, expected)
            algorithm = 'sha256'
        else:
            expected = item.blob_id
            verify_file(cached, expected, 'sha1', git_blob=True)
            algorithm = 'git-blob-sha1'
        destination = output / Path(name).name
        shutil.copyfile(cached, destination)
        report['files'][destination.name] = {'upstream_digest': expected, 'upstream_algorithm': algorithm,
                                            'sha256': digest_file(destination)}
        print(f'Verified model {name} at commit {revision}', flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('build/voice'))
    parser.add_argument('--github-output', type=Path)
    parser.add_argument('--voices', nargs='+', choices=VOICE_PRESETS, default=['af_heart'])
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    models = output / 'models'
    report = install_models(models, args.voices)
    executable = install_rhubarb(output)
    report['rhubarb'] = {'url': RHUBARB_URL, 'sha256': RHUBARB_SHA256,
                         'checksum_provenance': 'baseline of official HTTPS release bytes'}
    (output / 'verified_downloads.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Verified voice tools: {models}, {executable}', flush=True)
    if args.github_output:
        with args.github_output.open('a') as stream:
            stream.write(f'model_dir={models}\nrhubarb={executable}\n')


if __name__ == '__main__':
    main()
