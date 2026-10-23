"""Exercise default per-candidate upload delivery without model or service calls."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ace_three


class AceSunoDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'sources'
        self.out = self.root / 'ace'
        self.source.mkdir()
        self.out.mkdir()
        jobs = []
        for stem in ['song_a', 'song_b', 'song_c']:
            source = self.source / f'{stem}.md'
            source.write_text(stem)
            for candidate in [1, 2, 3]:
                audio = self.out / f'{stem}_ace_c{candidate}.wav'
                audio.write_bytes(f'fixture {stem} {candidate}'.encode())
                job = dict(stem=stem, candidate=candidate, status='complete', file=audio.name,
                           source_hash=ace_three.digest(source), input_hash=f'{stem}-{candidate}')
                audio.with_suffix('.json').write_text(json.dumps({**job, 'audio_sha256': ace_three.digest(audio)}))
                jobs.append(job)
        (self.out / 'candidates.json').write_text(json.dumps({'version': 'ace-candidates-v2', 'jobs': jobs}))
        self.args = ['--dir', str(self.source), '--songs', 'song_a,song_b,song_c', '--out', str(self.out)]

    def fake_song_export(self, tool, *args, **kwargs):
        self.assertEqual(tool, 'song_package.py')
        target = Path(args[args.index('--out') + 1])
        if '--check' in args:
            return 0 if (target / 'suno_config.json').is_file() else 1
        source = Path(args[args.index('--source') + 1])
        target.mkdir(parents=True, exist_ok=True)
        config = dict(title=source.stem, styles='female lead', lyrics='[Chorus]\n测试歌词',
                      exclude='rap', source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        (target / 'suno_config.json').write_text(json.dumps(config))
        return 0

    def test_generation_emits_nine_bound_cards_and_check_is_read_only(self):
        with patch('ace_three.run', return_value=0) as runner, \
             patch('ace_three.require_env'), \
             patch('make_suno_config.run', side_effect=self.fake_song_export):
            self.assertEqual(ace_three.main(self.args), 0)
            self.assertEqual(runner.call_args_list[0].args[0], 'ace_from_arena.py')
            cards = list((self.out / 'suno').glob('*/More_Options.json'))
            self.assertEqual(len(cards), 9)
            for card in cards:
                data = json.loads(card.read_text())
                audio = self.out / (card.parent.name + '.wav')
                self.assertEqual(data['audio_upload']['sha256'], ace_three.digest(audio))
                self.assertEqual(data['audio_upload']['file'], audio.name)
                self.assertTrue((card.parent / 'Audio_Description.txt').is_file())
            before = {p: p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
            runner.reset_mock()
            self.assertEqual(ace_three.main(self.args + ['--check-only']), 0)
            self.assertTrue(all(call.args[0] == 'windows_audio_api.py' for call in runner.call_args_list))
            self.assertEqual(before, {p: p.read_bytes() for p in self.out.rglob('*') if p.is_file()})
            cards[0].unlink()
            self.assertEqual(ace_three.main(self.args + ['--check-only']), 1)

    def test_dry_run_does_not_export_or_require_service(self):
        with patch('ace_three.run', return_value=0) as runner, \
             patch('ace_three.require_env') as env, patch('ace_three.export_suno') as export:
            self.assertEqual(ace_three.main(self.args + ['--dry-run']), 0)
            self.assertIn('--dry-run', runner.call_args.args)
            env.assert_not_called()
            export.assert_not_called()
            self.assertFalse((self.out / 'suno').exists())

    def test_invalid_profile_stops_before_generation(self):
        profile = self.root / 'invalid.json'
        profile.write_text(json.dumps({'values': {'weirdness': 101}}))
        with patch('ace_three.run') as runner:
            self.assertEqual(ace_three.main(self.args + ['--ui-profile', str(profile)]), 1)
            runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
