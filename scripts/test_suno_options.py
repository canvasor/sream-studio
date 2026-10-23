"""Test versioned UI settings and their separation from generated song inputs."""
import json
import tempfile
import unittest
from pathlib import Path

from suno_options import prepare, prepare_upload, update_package


class SunoOptionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.config = dict(title='测试歌曲', styles='Open female lead',
                           lyrics='[Chorus]\n风吹过山岗', exclude='rap, EDM drop, whispered lead')
        self.source = self.out / 'suno_config.json'
        self.source.write_text(json.dumps(self.config, ensure_ascii=False), encoding='utf-8')

    def test_export_keeps_song_input_unchanged_and_handles_gender(self):
        original = self.source.read_bytes()
        update_package(self.out)
        update_package(self.out, check=True)
        self.assertEqual(self.source.read_bytes(), original)
        data = json.loads((self.out / 'More_Options.json').read_text())
        self.assertEqual(data['requested']['exclude_styles'], self.config['exclude'])
        self.assertEqual(data['conditional']['vocal_gender'], 'Female')
        self.assertIsNone(data['conditional']['audio_influence'])
        duet = prepare({**self.config, 'styles': 'Female and male duet'})
        data = json.loads(duet['More_Options.json'])
        self.assertEqual(data['conditional']['vocal_gender'], '按本首演唱形式确认')

    def test_changed_profile_refuses_to_overwrite_any_existing_card(self):
        update_package(self.out)
        before = {p.name: p.read_bytes() for p in self.out.iterdir()}
        override = self.out / 'override.json'
        override.write_text(json.dumps({'values': {'weirdness': 30}}))
        with self.assertRaisesRegex(ValueError, '新输出目录'):
            update_package(self.out, profile_path=override)
        for name, content in before.items():
            self.assertEqual((self.out / name).read_bytes(), content)

    def test_check_detects_missing_or_changed_ui_file_without_writes(self):
        with self.assertRaises(ValueError):
            update_package(self.out, check=True)
        self.assertFalse((self.out / 'More_Options.json').exists())
        update_package(self.out)
        target = self.out / 'More_Options.json'
        target.write_text('{}')
        with self.assertRaises(ValueError):
            update_package(self.out, check=True)
        self.assertEqual(target.read_text(), '{}')

    def test_task_override_is_validated_and_recorded(self):
        override = self.out / 'override.json'
        override.write_text(json.dumps({'profile': 'test-task', 'values': {'style_influence': 70}}))
        files = prepare(self.config, override)
        data = json.loads(files['More_Options.json'])
        self.assertEqual(data['requested']['style_influence'], 70)
        self.assertEqual(data['basis'], 'task_override')
        for values in [{'style_influence': 101}, {'weirdness': True}, {'unknown': 1}]:
            override.write_text(json.dumps({'values': values}))
            with self.assertRaises(ValueError):
                prepare(self.config, override)

    def test_exclude_guidance_does_not_silently_change_song(self):
        exclude = 'no rap, synth bass, choir, brass, EDM drop'
        files = prepare({**self.config, 'exclude': exclude})
        self.assertEqual(json.loads(files['More_Options.json'])['requested']['exclude_styles'], exclude)
        self.assertIn('请检查', files['00_Suno参数卡.md'])

    def test_audio_binding_defaults_and_description_are_exported_together(self):
        audio = self.out / 'candidate.wav'
        audio.write_bytes(b'fixture audio content')
        upload = prepare_upload(audio)
        update_package(self.out, upload=upload)
        update_package(self.out, check=True, upload=prepare_upload(audio))
        data = json.loads((self.out / 'More_Options.json').read_text())
        self.assertEqual(data['audio_upload']['file'], audio.name)
        self.assertEqual(data['audio_upload']['audio_type'], 'Full Song')
        self.assertEqual(data['audio_upload']['suggested_operation'], 'Cover')
        self.assertEqual(len(data['audio_upload']['available_types']), 10)
        self.assertNotIn(str(self.out), json.dumps(data))
        self.assertEqual((self.out / 'Audio_Description.txt').read_text().strip(), upload['description'])
        self.assertNotIn('female', upload['description'])
        self.assertEqual(data['audio_upload']['actual_upload_status'], 'not_verified')

    def test_changed_audio_or_description_requires_new_delivery(self):
        audio = self.out / 'candidate.wav'
        audio.write_bytes(b'original audio')
        update_package(self.out, upload=prepare_upload(audio))
        original = {p.name: p.read_bytes() for p in self.out.iterdir() if p != audio}
        audio.write_bytes(b'replacement audio')
        with self.assertRaisesRegex(ValueError, '新输出目录'):
            update_package(self.out, upload=prepare_upload(audio))
        with self.assertRaises(ValueError):
            update_package(self.out, check=True, upload=prepare_upload(audio))
        for name, content in original.items():
            self.assertEqual((self.out / name).read_bytes(), content)

    def test_voice_override_and_missing_or_invalid_inputs(self):
        audio = self.out / 'voice.wav'
        audio.write_bytes(b'isolated voice')
        upload = prepare_upload(audio, audio_type='Voice', description='A dry vocal excerpt.', operation='Extend')
        self.assertEqual(upload['description_basis'], 'task_supplied')
        self.assertEqual(upload['suggested_operation'], 'Extend')
        self.assertEqual(upload['audio_type'], 'Voice')
        for kwargs in [{'audio_type': 'unknown'}, {'description': ' '}, {'operation': 'unknown'}]:
            with self.assertRaises(ValueError):
                prepare_upload(audio, **kwargs)
        audio.unlink()
        with self.assertRaises(ValueError):
            prepare_upload(audio)


if __name__ == '__main__':
    unittest.main()
