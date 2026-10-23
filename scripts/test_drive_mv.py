#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lyric checks and local FFmpeg rendering; no network or model calls."""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("drive_mv", HERE / "drive_mv.py")
mv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mv)


class BuildAssTests(unittest.TestCase):
    def test_timing_and_text(self):
        rows = [{"start": 20.0, "end": 23.22, "text": "高山下的情哥"}]
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "a.ass"
            mv.build_ass(rows, ["高山下的情歌"], p)
            t = p.read_text(encoding="utf-8")
        self.assertIn("0:00:20.00,0:00:23.22", t)
        self.assertIn("高山下的情歌", t)
        self.assertNotIn("高山下的情哥", t)
        self.assertEqual(rows[0]['text'], '高山下的情哥')

    def test_lyrics_count_mismatch_stops_without_overwriting_subtitles(self):
        rows = [{"start": 0, "end": 1, "text": "识别一"}, {"start": 1, "end": 2, "text": "识别二"}]
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "a.ass"
            p.write_text('previous subtitles')
            with self.assertRaisesRegex(ValueError, '不匹配'):
                mv.build_ass(rows, ["只有一行"], p)
            self.assertEqual(p.read_text(), 'previous subtitles')

    def test_missing_lyrics_or_empty_timing_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "a.ass"
            for rows, lyrics in [([], None), ([], ['正确歌词']), ([{'start': 0, 'end': 1, 'text': '正确歌词'}], None)]:
                with self.assertRaises(ValueError):
                    mv.build_ass(rows, lyrics, p)
            self.assertFalse(p.exists())

    def test_equal_count_but_wrong_line_or_invalid_time_is_rejected(self):
        for rows in [
            [{'start': 0, 'end': 1, 'text': '完全不同的一句话'}],
            [{'start': -1, 'end': 1, 'text': '正确歌词'}],
            [{'start': 0, 'end': float('nan'), 'text': '正确歌词'}],
            [{'start': 2, 'end': 3, 'text': '正确歌词'}],
        ]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                mv.aligned_lyrics(rows, ['正确歌词'], duration=2)
        with self.assertRaises(ValueError):
            mv.aligned_lyrics([{'start': 0, 'end': 1, 'text': '第一句'},
                               {'start': 0.5, 'end': 2, 'text': '第二句'}], ['第一句', '第二句'])

    def test_mismatch_saves_timeline_and_never_searches_or_renders(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            lyrics = root / 'lyrics.txt'
            lyrics.write_text('正确歌词\n')
            with patch.object(mv, 'probe_duration', return_value=5), \
                 patch.object(mv, 'transcribe', return_value=[{'start': 0, 'end': 1, 'text': '错误的段落'}]), \
                 patch.object(mv, 'search_clips') as search, \
                 patch.object(mv, 'render_versions') as render:
                self.assertEqual(mv.main(['--song', 'song.wav', '--title', 'test', '--lyrics', str(lyrics), '--out', str(root / 'out')]), 1)
                search.assert_not_called()
                render.assert_not_called()
            self.assertTrue((root / 'out/_work/歌词时间轴_待核对.json').is_file())

    def test_corrected_timings_resume_without_asr(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            lyrics = root / 'lyrics.txt'
            lyrics.write_text('正确歌词\n')
            timing = root / 'timing.json'
            timing.write_text(json.dumps([dict(start=0, end=1, text='正确歌词')]))
            with patch.object(mv, 'probe_duration', return_value=5), \
                 patch.object(mv, 'transcribe') as asr, \
                 patch.object(mv, 'render_cover'), patch.object(mv, 'render_versions') as render:
                self.assertEqual(mv.main(['--song', 'song.wav', '--title', 'test', '--lyrics', str(lyrics),
                                          '--timings', str(timing), '--clips', 'clip.mp4', '--out', str(root / 'out')]), 0)
                asr.assert_not_called()
                render.assert_called_once()


class RenderCommandTests(unittest.TestCase):
    def test_both_outputs_use_original_inputs_in_one_invocation(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / 'lyrics.ass').write_text('fixture')
            with patch.object(mv, 'probe_duration', return_value=1), patch.object(mv, 'sh') as run:
                mv.render_versions([root / 'red.mp4', root / 'blue.mp4'], root / 'song.wav', root / 'cover.png',
                                   root, root / 'hi.mp4', root / 'upload.mp4', 0.4, (160, 284), 2.4)
            run.assert_called_once()
            command = run.call_args.args[0]
            inputs = [command[i + 1] for i, value in enumerate(command) if value == '-i']
            self.assertEqual(inputs, [str(root / name) for name in ['red.mp4', 'blue.mp4', 'song.wav', 'cover.png']])
            self.assertNotIn(str(root / 'hi.mp4'), inputs)
            self.assertEqual(command.count('libx264'), 2)
            graph = command[command.index('-filter_complex') + 1]
            self.assertIn('xfade=', graph)
            self.assertIn('split=2[hi][upload]', graph)
            self.assertIn('setpts=(PTS-STARTPTS)*1.450000000', graph)

    def test_invalid_durations_or_dimensions_fail(self):
        for durations, need, aspect in [([], 2, (160, 284)), ([0], 2, (160, 284)),
                                         ([1], 0, (160, 284)), ([1], 2, (161, 284))]:
            with self.assertRaises(ValueError):
                mv.video_graph(durations, need, aspect, 0.4, True)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
class LocalRenderTests(unittest.TestCase):
    def test_fade_cover_audio_and_duration_in_both_outputs(self):
        with tempfile.TemporaryDirectory(prefix="mv render's ") as d:
            root = pathlib.Path(d)
            for color in ['red', 'blue']:
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                                f'color=c={color}:s=160x284:r=30:d=1', '-c:v', 'libx264',
                                '-threads', '1', str(root / f'{color}.mp4')], check=True)
            song = root / 'song.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=48000:duration=2.4', str(song)], check=True)
            from PIL import Image
            cover = root / 'cover.png'
            Image.new('RGB', (160, 284), (0, 255, 0)).save(cover)
            mv.build_ass([dict(start=0.5, end=2.2, text='正确歌词')], ['正确歌词'], root / 'lyrics.ass', duration=2.4)
            hi, upload = root / 'hi.mp4', root / 'upload.mp4'
            mv.render_versions([root / 'red.mp4', root / 'blue.mp4'], song, cover,
                               root, hi, upload, 0.4, (160, 284), 2.4)
            for output in [hi, upload]:
                self.assertLess(abs(mv.probe_duration(output) - 2.4), 0.1)
                info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(output)]))
                self.assertTrue(any(s['codec_type'] == 'audio' and s['codec_name'] == 'aac' for s in info['streams']))
                samples = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(output), '-f', 's16le', '-ac', '1', '-'])
                self.assertTrue(any(samples))
                pixels = []
                for seconds in [0.2, 0.6, 1.2, 2.1]:
                    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', str(seconds), '-i', str(output),
                                                   '-frames:v', '1', '-vf', 'crop=4:4:0:0', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
                    self.assertEqual(len(raw), 48)
                    pixels.append(tuple(sum(raw[c::3]) / 16 for c in range(3)))
                self.assertGreater(pixels[0][1], 200)  # cover visible
                self.assertGreater(pixels[1][0], 200)  # cover gone, red clip
                self.assertGreater(pixels[2][0], 30)   # dissolve includes both clips
                self.assertGreater(pixels[2][2], 30)
                self.assertGreater(pixels[3][2], 200)  # blue clip, no looping


class CoverTests(unittest.TestCase):
    def test_cover_size(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.png"
            mv.render_cover("遇上你是我的缘", "石满仓", "完整版", p, (1440, 2560))
            from PIL import Image
            with Image.open(p) as im:
                self.assertEqual(im.size, (1440, 2560))


if __name__ == "__main__":
    unittest.main()
