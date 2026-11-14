"""Integrity and extraction boundaries for optional official voice-tool downloads."""
import hashlib
import importlib.util
import io
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location('voice_setup', Path(__file__).resolve().parents[1] / 'tools/setup_voice.py')
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class VoiceDownloadTests(unittest.TestCase):
    def test_mismatched_cached_or_downloaded_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'weights.pth'
            file.write_bytes(b'actual downloaded bytes')
            setup.verify_file(file, hashlib.sha256(file.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                setup.verify_file(file, '0' * 64)

    def test_small_model_config_uses_git_blob_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'config.json'
            data = b'{"version":1}'
            file.write_bytes(data)
            expected = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
            setup.verify_file(file, expected, 'sha1', git_blob=True)

    def test_zip_rejects_absolute_traversal_backslash_and_symlink_paths(self):
        for filename, mode in (('../escape', 0), ('/absolute', 0), ('dir/../../escape', 0),
                               ('C:/windows', 0), ('..\\escape', 0),
                               ('link', stat.S_IFLNK | 0o777)):
            with self.subTest(filename=filename):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w') as archive:
                    info = zipfile.ZipInfo(filename)
                    info.external_attr = mode << 16
                    archive.writestr(info, b'payload')
                stream.seek(0)
                with zipfile.ZipFile(stream) as archive, self.assertRaisesRegex(ValueError, 'Unsafe archive member'):
                    list(setup.safe_zip_members(archive))

    def test_zip_allows_expected_nested_release_files(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('Rhubarb-Lip-Sync-1.14.0-Linux/rhubarb', b'binary')
            archive.writestr('Rhubarb-Lip-Sync-1.14.0-Linux/res/readme.txt', b'resources')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            self.assertEqual(len(list(setup.safe_zip_members(archive))), 2)


if __name__ == '__main__':
    unittest.main()
