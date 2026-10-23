#!/usr/bin/env python3
"""Observable delivery invariants; all writes stay in disposable temporary directories."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sync_delivery as sync


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / '工作区' / '新歌试听'
        self.parent = self.root / '共享区'
        self.source.mkdir(parents=True)
        self.parent.mkdir()
        (self.source / '音频').mkdir()
        (self.source / '音频' / 'A.wav').write_bytes(bytes(range(256)) * 3)
        (self.source / '试听.html').write_text('<audio src="音频/A.wav"></audio>')
        self.target = self.parent / self.source.name

    def run_sync(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return sync.main(['--source', str(self.source), '--dest-parent', str(self.parent), *extra])

    def test_dry_run_creates_nothing(self):
        self.assertEqual(self.run_sync('--dry-run'), 0)
        self.assertEqual(list(self.parent.iterdir()), [])
        self.assertFalse((self.source / sync.RECEIPT).exists())

    def test_copy_preserves_payload_and_relative_player_links(self):
        (self.source / '__pycache__').mkdir()
        (self.source / '__pycache__' / 'cache.pyc').write_bytes(b'cache')
        (self.source / sync.RECEIPT).write_text('old receipt')
        self.assertEqual(self.run_sync('--unc-root', r'\\server\share\songs'), 0)
        self.assertEqual((self.target / '音频/A.wav').read_bytes(), (self.source / '音频/A.wav').read_bytes())
        self.assertEqual((self.target / '试听.html').read_text(), (self.source / '试听.html').read_text())
        self.assertFalse((self.target / '__pycache__').exists())
        receipt = json.loads((self.target / sync.RECEIPT).read_text())
        self.assertEqual(receipt['files'], 2)
        self.assertEqual(receipt['windows_visibility'], 'not_confirmed')
        self.assertEqual((self.source / sync.RECEIPT).read_text(), 'old receipt')

    def test_repeated_sync_and_read_only_check_preserve_delivery(self):
        self.assertEqual(self.run_sync(), 0)
        before = {p: p.stat().st_mtime_ns for p in self.target.rglob('*') if p.is_file()}
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.run_sync('--check-only'), 0)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})

    def test_corrupted_or_extra_destination_files_are_not_overwritten(self):
        self.assertEqual(self.run_sync(), 0)
        audio = self.target / '音频/A.wav'
        original = audio.read_bytes()
        audio.write_bytes(b'damaged')
        self.assertEqual(self.run_sync('--check-only'), 1)
        self.assertEqual(self.run_sync(), 1)
        self.assertEqual(audio.read_bytes(), b'damaged')
        audio.write_bytes(original)
        (self.target / 'extra.txt').write_text('client addition')
        self.assertEqual(self.run_sync('--check-only'), 1)

    def test_changed_source_cannot_overwrite_existing_batch(self):
        self.assertEqual(self.run_sync(), 0)
        before = (self.target / '试听.html').read_bytes()
        (self.source / '试听.html').write_text('revised')
        self.assertEqual(self.run_sync(), 1)
        self.assertEqual((self.target / '试听.html').read_bytes(), before)

    def interrupt_copy(self, change_source=False):
        real_copy = sync.shutil.copyfile
        calls = []

        def copy(original, copied):
            calls.append(original)
            if change_source:
                result = real_copy(original, copied)
                (self.source / '试听.html').write_text('changed while copying')
                return result
            if len(calls) == 2:
                Path(copied).write_bytes(b'partial transfer')
                raise OSError('simulated connection loss')
            return real_copy(original, copied)

        with patch.object(sync.shutil, 'copyfile', side_effect=copy):
            self.assertEqual(self.run_sync(), 1)
        self.assertFalse(self.target.exists())

    def test_interrupted_copy_resumes_and_repairs_only_staging(self):
        self.interrupt_copy()
        self.assertEqual(self.run_sync(), 1)
        self.assertEqual(self.run_sync('--resume'), 0)
        self.assertEqual(self.run_sync('--check-only'), 0)
        self.assertEqual((self.target / '音频/A.wav').read_bytes(), (self.source / '音频/A.wav').read_bytes())

    def test_changed_source_during_copy_prevents_publication_and_resume(self):
        self.interrupt_copy(change_source=True)
        self.assertEqual(self.run_sync('--resume'), 1)
        self.assertFalse(self.target.exists())

    def test_symlink_payload_and_symlink_destination_are_rejected(self):
        link = self.source / '外部链接'
        link.symlink_to(self.root)
        self.assertEqual(self.run_sync(), 1)
        link.unlink()
        other = self.root / '其他交付'
        other.mkdir()
        self.target.symlink_to(other)
        self.assertEqual(self.run_sync(), 1)
        self.assertEqual(list(other.iterdir()), [])

    def test_missing_destination_and_nested_destination_fail_without_writes(self):
        self.assertEqual(self.run_sync('--check-only'), 1)
        self.assertEqual(list(self.parent.iterdir()), [])
        self.parent = self.source
        self.assertEqual(self.run_sync('--dry-run'), 1)
        self.assertFalse((self.source / self.source.name).exists())

    def test_old_sha256_receipt_can_be_checked_without_rewriting(self):
        self.assertEqual(self.run_sync(), 0)
        receipt_path = self.target / sync.RECEIPT
        receipt = json.loads(receipt_path.read_text())
        receipt.pop('version')
        receipt.pop('windows_visibility')
        receipt_path.write_text(json.dumps(receipt))
        before = receipt_path.read_bytes()
        self.assertEqual(self.run_sync('--check-only'), 0)
        self.assertEqual(receipt_path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
