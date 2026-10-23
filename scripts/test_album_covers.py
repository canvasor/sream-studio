#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""album_covers 的纯函数测试：不联网、不出图。"""
import importlib.util
import json
import pathlib
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("album_covers", HERE / "album_covers.py")
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)


def _write_jobs(tmp, data):
    p = pathlib.Path(tmp) / "jobs.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


class LoadJobsTests(unittest.TestCase):
    def test_defaults_filled(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_jobs(td, {"album": "测试", "jobs": [{"tag": "01", "scene": "草原"}]})
            d = ac.load_jobs(p)
        self.assertEqual(d["aspect"], "1:1")
        self.assertEqual(d["outsize"], "1920x1920")
        self.assertEqual(d["jobs"][0]["slogan"], "")
        self.assertIn("蓝天", d["jobs"][0]["palette"])

    def test_missing_jobs_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_jobs(td, {"album": "x"})
            with self.assertRaises(SystemExit):
                ac.load_jobs(p)

    def test_missing_tag_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_jobs(td, {"jobs": [{"scene": "草原"}]})
            with self.assertRaises(SystemExit):
                ac.load_jobs(p)


class BuildPromptTests(unittest.TestCase):
    def setUp(self):
        self.d = {
            "album": "高原三帖", "aspect": "1:1",
            "outsize": "1920x1920",
            "jobs": [{"tag": "01", "scene": "牧场", "slogan": "天亮之前",
                      "style": "实拍。", "palette": "蓝天白云，不要偏黄"}],
        }

    def test_contains_all_blocks(self):
        p = ac.build_prompt(self.d["jobs"][0], self.d)
        for must in ("正方形 1:1", "牧场", "蓝天白云", "实拍", "高原三帖", "天亮之前",
                     "不要错字"):
            self.assertIn(must, p)

    def test_no_double_punctuation(self):
        p = ac.build_prompt(self.d["jobs"][0], self.d)
        self.assertNotIn("。。", p)
        self.assertNotIn("，，", p)

    def test_prompt_mentions_aspect_so_size_not_needed(self):
        """尺寸必须出现在提示词里 —— 这是 GPT 通道的关键约定。"""
        p = ac.build_prompt(self.d["jobs"][0], self.d)
        self.assertIn("1:1", p)


class DryRunTests(unittest.TestCase):
    def test_dry_run_no_network(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_jobs(td, {
                "album": "测试", "jobs": [
                    {"tag": "01_a", "scene": "草原", "slogan": "一句话"},
                    {"tag": "02_b", "scene": "雪山", "slogan": "另一句"},
                ]})
            out = pathlib.Path(td) / "out"
            rc = ac.main(["--jobs", str(p), "--out", str(out), "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertFalse(any(out.glob("*.jpg")))     # dry-run 不出图

    def test_only_filter(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write_jobs(td, {"album": "x", "jobs": [
                {"tag": "01_a", "scene": "草原"}, {"tag": "02_b", "scene": "雪山"}]})
            out = pathlib.Path(td) / "out"
            rc = ac.main(["--jobs", str(p), "--out", str(out),
                          "--dry-run", "--only", "02_b"])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
