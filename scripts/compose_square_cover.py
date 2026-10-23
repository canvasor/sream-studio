#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在底图上叠 1:1 专辑封面文字（备选路径：模型文字不可用时自己叠）。

版式：顶部左《专辑名》/ 中间居中歌名 / 右下艺人签名，上下压暗带保证文字可读。

用法：
    python3 scripts/compose_square_cover.py --art 底图.jpg --title 歌名 \\
        --album 专辑名 --out 输出.jpg [--accent 232,196,140] [--artist "Sream 锦霖"]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W = Path(__file__).resolve().parent.parent
S = 1920

FONT_CANDS = [
    os.environ.get("COVER_FONT_TITLE", ""),
    str(W.parent / "mv/fonts/方正粗黑宋简体.ttf"),
    str(W / "mv/fonts/方正粗黑宋简体.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
]
SIGN_CANDS = [
    os.environ.get("COVER_FONT_SIGN", ""),
    str(W.parent / "mv/fonts/汉仪雪君体简.ttf"),
    str(W / "mv/fonts/汉仪雪君体简.ttf"),
]


def pick(cands: list[str]) -> str:
    for c in cands:
        if c and Path(c).is_file():
            return c
    raise FileNotFoundError("找不到中文字体；用 COVER_FONT_TITLE / COVER_FONT_SIGN 指定")


def darken_bands(img: Image.Image) -> Image.Image:
    a = np.asarray(img, dtype="float32").copy()
    y = np.arange(S)[:, None, None]
    a *= (1 - 0.45 * np.clip(1 - y / (S * 0.22), 0, 1))     # 顶部渐暗
    a *= (1 - 0.60 * np.clip((y - S * 0.58) / (S * 0.42), 0, 1))  # 底部渐暗
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"), "RGB")


def compose(art: Path, title: str, album: str, out: Path,
            accent=(232, 196, 140), artist: str = "Sream 锦霖") -> None:
    img = Image.open(art).convert("RGB")
    if img.size != (S, S):
        img = img.resize((S, S), Image.LANCZOS)
    img = darken_bands(img)
    d = ImageDraw.Draw(img)

    m = 90
    d.rectangle([m, m, S - m, S - m], outline=accent, width=3)
    d.text((m + 58, m + 52), f"《{album}》",
           font=ImageFont.truetype(pick(FONT_CANDS), 58), fill=accent)

    size = 200 if len(title) <= 6 else (172 if len(title) <= 8 else 150)
    d.text((S // 2, int(S * 0.46)), title,
           font=ImageFont.truetype(pick(FONT_CANDS), size),
           fill=(250, 247, 240), anchor="mm",
           stroke_width=9, stroke_fill=(22, 16, 10))

    d.text((S - m - 66, S - m - 74), artist,
           font=ImageFont.truetype(pick(SIGN_CANDS), 108), fill=accent, anchor="rs")

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=94)
    print(f"  ✅ {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--album", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--accent", default="232,196,140")
    ap.add_argument("--artist", default="Sream 锦霖")
    a = ap.parse_args()
    compose(Path(a.art), a.title, a.album, Path(a.out),
            tuple(int(x) for x in a.accent.split(",")), a.artist)


if __name__ == "__main__":
    main()
