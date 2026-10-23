"""Offline checks: no uploads, model calls, or credentials required."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import wan_client as wan


class WanClientTests(unittest.TestCase):
    def test_generation_preview_makes_no_calls_and_creates_no_files(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'out.mp4'
            commands = [
                ['face-detect', '--image', 'person.jpg'],
                ['s2v', '--image', 'person.jpg', '--audio', 'vocal.wav', '--out', str(out)],
                ['video', '--prompt', 'example scene', '--out', str(out)],
            ]
            with patch.object(wan, 'load_conf') as config, patch.object(wan, '_post') as post, patch.object(wan, 'upload_temp') as upload, contextlib.redirect_stdout(io.StringIO()):
                for args in commands:
                    self.assertEqual(wan.main([*args, '--dry-run']), 0)
                config.assert_not_called()
                post.assert_not_called()
                upload.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_environment_config_works_without_secret_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ASR_MODEL_API_KEY': 'fake-key', 'ASR_MODEL_BASE_URL': 'https://example.invalid/api/v1/'}, clear=True):
            config = wan.load_conf(Path(directory) / 'missing.env')
            self.assertEqual(config['BASE'], 'https://example.invalid/api/v1')
            self.assertEqual(config['ASR_MODEL_API_KEY'], 'fake-key')

    def test_interrupted_download_never_publishes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'out.mp4'
            response = MagicMock()
            response.__enter__.return_value.read.side_effect = [b'partial', OSError('connection lost')]
            with patch.object(wan.urllib.request, 'urlopen', return_value=response):
                with self.assertRaises(OSError):
                    wan.download('https://example.invalid/video', out)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_existing_download_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'out.mp4'
            out.write_bytes(b'accepted film')
            with patch.object(wan.urllib.request, 'urlopen') as request:
                with self.assertRaises(FileExistsError):
                    wan.download('https://example.invalid/video', out)
                request.assert_not_called()
            self.assertEqual(out.read_bytes(), b'accepted film')

    def test_complete_download_publishes_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'out.mp4'
            response = MagicMock()
            response.__enter__.return_value.read.side_effect = [b'complete payload', b'']
            with patch.object(wan.urllib.request, 'urlopen', return_value=response), contextlib.redirect_stdout(io.StringIO()):
                wan.download('https://example.invalid/video', out)
            self.assertEqual(out.read_bytes(), b'complete payload')
            self.assertEqual(list(Path(directory).iterdir()), [out])


if __name__ == '__main__':
    unittest.main()
