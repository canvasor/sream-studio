#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""④ 分轨：完整版 + 清唱版（清唱只录最后 ~100s 一段）。

按源音频指纹隔离缓存后运行HTDemucs，再把每首的人声轨截取末 ~100s。

用法：
    python scripts/split_vocal.py --src <9首wav目录> --out <输出目录> --tail 100

环境变量：
    AUDIOCPP_HOST / AUDIOCPP_PORT   HTDemucs 服务地址
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import require_env, tools_dir
from vocal_cache import separate_one


def _trim_tail(src: Path, dst: Path, tail: int) -> dict:
    """用 ffmpeg 截取末 tail 秒（不足则整体）。"""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(src)], capture_output=True, text=True, check=True)
    dur = float(probe.stdout.strip() or 0)
    if dur <= 0 or tail <= 0 or src.resolve() == dst.resolve():
        raise ValueError("时长无效，或输出与原轨相同")
    start = max(0.0, dur - tail)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}",
                    "-i", str(src), "-c:a", "pcm_s16le", str(dst)], check=True)
    metadata = dict(version="vocal-segment-v2", source_audio=str(src.resolve()),
                    source_start_seconds=start, source_end_seconds=dur,
                    duration_seconds=dur-start)
    dst.with_suffix('.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n')
    return metadata


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, help="ACE 产物目录（含 *_ace_c*.wav）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--tail", type=int, default=100, help="清唱只录末尾秒数，默认 100")
    ap.add_argument("--skip-split", action="store_true", help="人声轨已存在，只做截取")
    ap.add_argument("--cache-dir", type=Path, default=Path(tempfile.gettempdir())/'sream-studio-vocals',
                    help="分轨缓存根目录；内部按源SHA256隔离，不应放入共享交付目录")
    ap.add_argument("--service-version", default="unversioned-service",
                    help="分轨模型/服务版本；未提供时不宣称跨服务版本缓存有效")
    a = ap.parse_args(argv)

    if a.tail <= 0:
        ap.error("tail必须为正数")

    src, out = Path(a.src), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if not a.skip_split:
        require_env("AUDIOCPP_HOST", "AUDIOCPP_PORT")
        sys.path.insert(0, str(tools_dir()))
        from windows_audio_api import WindowsAudioAPI
        api = WindowsAudioAPI()
        originals = sorted(p for p in src.glob('*_ace_c*.wav')
                           if re.fullmatch(r'.+_ace_c[123]', p.stem))
        if not originals:
            ap.error('找不到候选混音')
        for original in originals:
            separate_one(api, original, original.with_name(original.stem+'_清唱.wav'),
                         a.cache_dir, a.service_version)

    # 找到每首的清唱版（人声轨），截取末 tail 秒
    vocals = sorted(p for p in src.glob("*_清唱.wav") if p.is_file())
    if not vocals:
        sys.exit(f"❌ 在 {src} 里没找到清唱版（*清唱*.wav），先确认分轨是否成功")
    for v in vocals:
        dst = out / f"{v.stem}_末{a.tail}s.wav"
        _trim_tail(v, dst, a.tail)
        print(f"  ✅ {dst.name}  ({dst.stat().st_size // 1024} KB)")
    print(f"✅ 分轨 + 清唱末 {a.tail}s 完成：{len(vocals)} 首")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
