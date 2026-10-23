#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""局部降调修音：只把歌里某几个字/句的音高改掉，其余部分不动。

场景：某个字（如副歌结尾的「方」）旋律冲高了，听着"顶上去了"，想让它落下来。

做法：`rubberband` 保共振峰变调（不会变闷、不会变另一个人），
再用余弦交叉淡化把改过的片段贴回原曲，时长与采样率不变。

用法：
    python scripts/patch_pitch.py --in song.wav --out fixed.wav \\
        --patch 63.22:64.86:-5 --patch 127.20:128.86:-5 --patch 172.52:174.15:-5

    --patch  START:END:SEMITONES    可重复，按顺序应用
    --fade   边沿淡化秒数（默认 0.06）
    --formant preserved|shifted    默认 preserved
    --dry-run                      只打印将要改的区间

定位技巧（详见 references/17_局部降调修音.md）：
  ASR/歌词对轴经常给出不可靠的时间戳；**用基频轨迹找"突然上挑并停在高位"的位置**最准。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf


def shift_segment(src: str, start: float, end: float, semitones: float,
                  formant: str = "preserved") -> np.ndarray:
    """把 [start,end) 变调，返回 float32 立体声数组（与源同采样率、同时长）。"""
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "seg.wav"
        out = Path(td) / "shift.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
             "-i", src, "-c:a", "pcm_s16le", str(raw)],
            check=True)
        ratio = 2.0 ** (semitones / 12.0)          # 半音 → 频率比
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(raw),
             "-af", f"rubberband=pitch={ratio:.6f}:formant={formant}:transients=crisp",
             "-c:a", "pcm_s16le", str(out)],
            check=True)
        seg, _ = sf.read(out, dtype="float32", always_2d=True)
    return seg


def apply_patch(full: np.ndarray, sr: int, src: str, start: float, end: float,
                semitones: float, fade: float, formant: str) -> None:
    """就地修改 full 的 [start,end) 区间。"""
    i0, i1 = int(start * sr), int(end * sr)
    n = i1 - i0
    if n <= 0:
        raise ValueError(f"区间无效：{start}–{end}")
    seg = shift_segment(src, start, end, semitones, formant)
    if len(seg) < n:
        seg = np.pad(seg, ((0, n - len(seg)), (0, 0)))
    seg = seg[:n]

    nf = max(1, min(int(fade * sr), n // 2))
    env = np.ones(n, dtype="float32")
    r = np.linspace(0, 1, nf, dtype="float32")
    env[:nf] = 0.5 - 0.5 * np.cos(np.pi * r)        # 0 → 1
    env[-nf:] = 0.5 + 0.5 * np.cos(np.pi * r)       # 1 → 0
    full[i0:i1] = full[i0:i1] * (1 - env[:, None]) + seg * env[:, None]


def parse_patch(s: str) -> tuple[float, float, float]:
    parts = s.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("格式应为 START:END:SEMITONES，如 63.22:64.86:-5")
    a, b, c = parts
    return float(a), float(b), float(c)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", required=True, help="源音频")
    ap.add_argument("--out", dest="dst", required=True, help="输出音频")
    ap.add_argument("--patch", type=parse_patch, action="append", required=True,
                    help="START:END:SEMITONES，可重复")
    ap.add_argument("--fade", type=float, default=0.06, help="边沿淡化秒数（默认 0.06）")
    ap.add_argument("--formant", choices=("preserved", "shifted"),
                    default="preserved", help="共振峰处理，默认保留")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    for s, e, semi in a.patch:
        if not (0 <= s < e):
            ap.error(f"区间必须递增：{s}–{e}")
    a.patch.sort(key=lambda x: x[0])
    for i in range(1, len(a.patch)):
        if a.patch[i][0] < a.patch[i - 1][1]:
            ap.error(f"区间重叠：{a.patch[i-1]} 与 {a.patch[i]}")

    if a.dry_run:
        for s, e, semi in a.patch:
            print(f"  [dry-run] {s:.2f}–{e:.2f}s  {semi:+.1f} 半音")
        return 0

    full, sr = sf.read(a.src, dtype="float32", always_2d=True)
    # 依次应用：每次都基于当前结果重算，避免读到旧数据
    for s, e, semi in a.patch:
        apply_patch(full, sr, a.src, s, e, semi, a.fade, a.formant)
        print(f"  ✓ {s:.2f}–{e:.2f}s  {semi:+.1f} 半音")
    sf.write(a.dst, full, sr, subtype="PCM_24")
    print(f"✅ {a.dst}（{len(full)/sr:.2f}s / {sr}Hz / {full.shape[1]}ch）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
