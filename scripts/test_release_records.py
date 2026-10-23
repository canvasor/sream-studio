"""Archive integrity checks using temporary fixtures, never the actual library."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import make_evidence_pack as evidence
import make_generation_record as generation
import recover_generation_record as recovery
from _release_common import check_song, write_record


class ReleaseRecordTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / 'library'
        self.out = self.root / 'evidence'
        self.song = {'name': '示例歌曲', 'lib_dir': '01_示例歌曲', 'wav': '母版.wav', 'dur': '00:01', 'album': '示例专辑'}
        self.directory = self.library / self.song['lib_dir']
        for folder in ['01_音频母版', '04_歌词', '05_生成记录', '06_文档/a', '06_文档/b']:
            (self.directory / folder).mkdir(parents=True, exist_ok=True)
        (self.directory / '01_音频母版/母版.wav').write_bytes(b'fixture-audio')
        (self.directory / '06_文档/a/参数.txt').write_text('A')
        (self.directory / '06_文档/b/参数.txt').write_text('B')
        self.record = self.directory / '05_生成记录/示例歌曲.md'
        for module in [evidence, generation, recovery]:
            patcher = patch.object(module, 'LIB', self.library)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(evidence, 'OUT', self.out)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(evidence, 'probe', return_value={'duration_s': 1})
        patcher.start()
        self.addCleanup(patcher.stop)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_package_preserves_same_names_and_checksums_refer_to_package(self):
        for folder, content in [('03_封面', 'short'), ('03_封面全曲', 'full')]:
            (self.directory / folder).mkdir()
            (self.directory / folder / '封面.jpg').write_text(content)
        pack = evidence.build(self.song, '20000101')
        self.assertEqual((pack / '04_生成配置/a/参数.txt').read_text(), 'A')
        self.assertEqual((pack / '04_生成配置/b/参数.txt').read_text(), 'B')
        self.assertEqual((pack / '06_封面/封面.jpg').read_text(), 'short')
        self.assertEqual((pack / '06_封面/03_封面全曲/封面.jpg').read_text(), 'full')
        checksum = pack / '01_清单_SHA256.txt'
        listed = set()
        for line in checksum.read_text().splitlines():
            digest, relative = line.split('  ', 1)
            self.assertEqual(evidence.sha256(pack / relative), digest)
            listed.add(relative)
        actual = {p.relative_to(pack).as_posix() for p in pack.rglob('*') if p.is_file() and p != checksum}
        self.assertEqual(listed, actual)
        manifest = json.loads((pack / '02_manifest.json').read_text())
        self.assertEqual(manifest['album'], '示例专辑')
        for entry in manifest['files']:
            if 'pack_path' in entry:
                self.assertEqual(evidence.sha256(pack / entry['pack_path']), entry['sha256'])
        with zipfile.ZipFile(self.out / f'{pack.name}.zip') as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn(f'{pack.name}/04_生成配置/b/参数.txt', archive.namelist())

    def test_same_day_rebuild_preserves_existing_directory_and_zip(self):
        pack = evidence.build(self.song, '20000101')
        before = {p: p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
        with self.assertRaises(FileExistsError):
            evidence.build(self.song, '20000101')
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertTrue(pack.is_dir())

    def test_dry_runs_create_no_outputs(self):
        evidence.build(self.song, '20000101', dry_run=True)
        generation.build(self.song, dry_run=True)
        self.assertFalse(self.out.exists())
        self.assertFalse(self.record.exists())

    def test_interrupted_copy_does_not_publish_zip(self):
        with patch.object(evidence.shutil, 'copy2', side_effect=OSError('copy interrupted')):
            with self.assertRaises(OSError):
                evidence.build(self.song, '20000101')
        self.assertFalse(any(self.out.glob('*.zip')))
        self.assertEqual((self.directory / '06_文档/a/参数.txt').read_text(), 'A')

    def test_corrupted_copy_does_not_publish_zip(self):
        def damaged(source, target):
            target.write_bytes(b'damaged')
        with patch.object(evidence.shutil, 'copy2', side_effect=damaged):
            with self.assertRaises(OSError):
                evidence.build(self.song, '20000101')
        self.assertFalse(any(self.out.glob('*.zip')))

    def test_generation_and_recovery_preserve_handwritten_record_by_default(self):
        self.record.write_text('handwritten record')
        generation.build(self.song)
        with patch.object(recovery, 'pdf_text') as pdf:
            self.assertFalse(recovery.recover(self.song))
            pdf.assert_not_called()
        self.assertEqual(self.record.read_text(), 'handwritten record')

    def test_explicit_generation_replacement_retains_backup(self):
        self.record.write_text('handwritten record')
        generation.build(self.song, force=True)
        backups = list(self.record.parent.glob('*.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), 'handwritten record')
        self.assertIn('待核实', self.record.read_text())
        self.assertNotIn('本人独立创作', self.record.read_text())

    def test_failed_replacement_leaves_original_and_backup(self):
        self.record.write_text('handwritten record')
        with patch.object(Path, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                write_record(self.record, 'new record', force=True)
        self.assertEqual(self.record.read_text(), 'handwritten record')
        self.assertEqual(next(self.record.parent.glob('*.backup-*')).read_text(), 'handwritten record')
        self.assertFalse(list(self.record.parent.glob('.record-*')))

    def test_missing_full_source_prevents_pdf_recovery_replacement(self):
        self.record.write_text('handwritten record')
        (self.record.with_suffix('.pdf')).write_bytes(b'fixture-pdf')
        text = '标题\n歌曲信息\n项目  内容\nAI 工具使用记录\n工具  配置\n' + 'extra line\n' * 40
        with patch.object(recovery, 'pdf_text', return_value=text):
            self.assertFalse(recovery.recover(self.song, force=True))
        self.assertEqual(self.record.read_text(), 'handwritten record')
        self.assertFalse(list(self.record.parent.glob('*.backup-*')))

    def test_successful_recovery_uses_full_source_and_retains_original(self):
        self.record.write_text('handwritten record')
        self.record.with_suffix('.pdf').write_bytes(b'fixture-pdf')
        (self.directory / '04_歌词/歌词_Suno原文.md').write_text('### Styles\n```\nfull styles\n```\n### Lyrics\n```\n完整唱词\n```\n')
        text = '标题\n歌曲信息\n项目  内容\nAI 工具使用记录\n工具  配置\n' + 'extra line\n' * 40
        with patch.object(recovery, 'pdf_text', return_value=text):
            self.assertTrue(recovery.recover(self.song, force=True, dry_run=True))
            self.assertEqual(self.record.read_text(), 'handwritten record')
            self.assertTrue(recovery.recover(self.song, force=True))
        self.assertIn('完整唱词', self.record.read_text())
        self.assertEqual(next(self.record.parent.glob('*.backup-*')).read_text(), 'handwritten record')

    def test_catalog_cannot_escape_library(self):
        for key in ['name', 'lib_dir', 'wav']:
            with self.assertRaises(ValueError):
                check_song({**self.song, key: '../outside'}, self.library)

    def test_help_does_not_require_external_catalog(self):
        import os
        import sys
        for script in ['make_evidence_pack.py', 'make_generation_record.py', 'recover_generation_record.py']:
            result = subprocess.run([sys.executable, str(Path(__file__).parent / script), '--help'],
                                    env={**os.environ, 'TOOLS_DIR': str(self.root / 'missing')},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
