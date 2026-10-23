#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_pitch 的纯函数测试：不调用 ffmpeg、不写共享盘。"""
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent

try:
    import numpy as np
    import soundfile as sf          # noqa: F401
    HAVE_AUDIO = True
except ImportError:                 # 系统 python 没这些库时跳过，不判失败
    HAVE_AUDIO = False

pp = None
if HAVE_AUDIO:
    spec = importlib.util.spec_from_file_location("patch_pitch", HERE / "patch_pitch.py")
    pp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pp)


@unittest.skipUnless(HAVE_AUDIO, "需要 numpy + soundfile（用 tools/venv-sep/bin/python 跑）")


@unittest.skipUnless(HAVE_AUDIO, "需要依赖")
class ParseTests(unittest.TestCase):
    def test_parse_ok(self):
        self.assertEqual(pp.parse_patch("63.22:64.86:-5"), (63.22, 64.86, -5.0))

    def test_parse_positive(self):
        self.assertEqual(pp.parse_patch("1:2:3.5"), (1.0, 2.0, 3.5))

    def test_parse_bad(self):
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            pp.parse_patch("1:2")

    def test_cli_rejects_overlap(self):
        with self.assertRaises(SystemExit):
            pp.main(["--in", "a.wav", "--out", "b.wav",
                     "--patch", "1:5:-2", "--patch", "4:8:-2", "--dry-run"])

    def test_cli_rejects_reversed(self):
        with self.assertRaises(SystemExit):
            pp.main(["--in", "a.wav", "--out", "b.wav",
                     "--patch", "5:1:-2", "--dry-run"])

    def test_dry_run_ok(self):
        rc = pp.main(["--in", "a.wav", "--out", "b.wav",
                      "--patch", "1:2:-3", "--patch", "5:6:-4", "--dry-run"])
        self.assertEqual(rc, 0)


@unittest.skipUnless(HAVE_AUDIO, "需要依赖")
class ApplyTests(unittest.TestCase):
    def test_patch_touches_only_region(self):
        """只在目标区间改动，其余采样必须完全一致。"""
        sr = 8000
        n = sr * 3
        full = np.zeros((n, 2), dtype="float32")
        full[:, :] = 0.5
        before = full.copy()
        # 桩：shift_segment 返回同一段但幅度减半，便于判断
        orig = pp.shift_segment
        pp.shift_segment = lambda *a, **k: np.full((int(0.5 * sr), 2), 0.25, dtype="float32")
        try:
            pp.apply_patch(full, sr, "unused.wav", 1.0, 1.5, -5, 0.02, "preserved")
        finally:
            pp.shift_segment = orig

        i0, i1 = int(1.0 * sr), int(1.5 * sr)
        # 区间外未动
        self.assertTrue(np.allclose(full[:i0], before[:i0]))
        self.assertTrue(np.allclose(full[i1:], before[i1:]))
        # 区间中段已被替换（0.25 而不是 0.5）
        mid = (i0 + i1) // 2
        self.assertLess(full[mid, 0], 0.45)

    def test_short_segment_is_padded(self):
        sr = 8000
        full = np.full((sr, 2), 0.5, dtype="float32")
        orig = pp.shift_segment
        pp.shift_segment = lambda *a, **k: np.full((10, 2), 0.1, dtype="float32")
        try:
            pp.apply_patch(full, sr, "unused.wav", 0.1, 0.6, -3, 0.01, "preserved")
        finally:
            pp.shift_segment = orig
        self.assertEqual(full.shape, (sr, 2))     # 长度不变


if __name__ == "__main__":
    unittest.main()