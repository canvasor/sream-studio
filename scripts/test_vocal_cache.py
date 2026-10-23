"""Source identity and preservation tests; no live audio service."""
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from vocal_cache import separate_one


class FakeAPI:
    def __init__(self):
        self.calls = []

    def separate(self, source, out):
        self.calls.append(Path(source).parent)
        out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out/'vocals.wav')


def resample(command, **kwargs):
    shutil.copyfile(command[command.index('-i')+1], command[-1])


class VocalCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'song.wav'
        self.target = self.root/'out/song_清唱.wav'
        self.api = FakeAPI()
        self.write_source(100)

    def write_source(self, sample):
        with wave.open(str(self.source), 'wb') as stream:
            stream.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
            stream.writeframes(struct.pack('<h', sample)*8820)

    def split(self, target=None, version='model-v1'):
        with patch('vocal_cache.subprocess.run', side_effect=resample):
            return separate_one(self.api, self.source, target or self.target,
                                self.root/'cache', version)

    def test_same_source_reuses_verified_target(self):
        first = self.split()
        self.assertEqual(first, self.split())
        self.assertEqual(len(self.api.calls), 1)

    def test_same_filename_changed_source_gets_distinct_cache(self):
        self.split()
        self.write_source(200)
        self.split(self.root/'new/song_清唱.wav')
        self.assertEqual(len(set(self.api.calls)), 2)

    def test_changed_source_preserves_existing_vocal(self):
        self.split()
        before = self.target.read_bytes()
        self.write_source(200)
        with self.assertRaisesRegex(ValueError, '新输出目录'):
            self.split()
        self.assertEqual(before, self.target.read_bytes())

    def test_tampered_target_rejected(self):
        self.split()
        self.target.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.split()

    def test_changed_service_rejected(self):
        self.split()
        with self.assertRaises(ValueError):
            self.split(version='model-v2')

    def test_missing_receipt_rejected(self):
        self.split()
        self.target.with_suffix('.json').unlink()
        with self.assertRaisesRegex(ValueError, '来源记录'):
            self.split()


if __name__ == '__main__':
    unittest.main()
