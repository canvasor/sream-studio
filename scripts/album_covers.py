#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量出「专辑封面」1:1 图（GPT-Image / 豆包 Seedream 两条通道）。

为什么单独有这个脚本：
  · **尺寸必须写进提示词** —— GPT 图片接口的 `size` 参数实测无效，
    真正起作用的是提示词里的画幅描述（见 `llm_client.with_aspect`）。
  · 中文标题/概语**让模型直出**质量已经够好（实测 8/8 无错字），
    但要**逐张核对**，所以这里额外产出「文字裁切图」便于检查。
  · 一次出 8 版不同风格，方便挑；统一走同一套提示词块。

用法：
    # 先看会发什么（不联网）
    python3 scripts/album_covers.py --jobs templates/专辑封面_题单.json --out /tmp/cov --dry-run

    # 真出图（默认 GPT-Image）
    python3 scripts/album_covers.py --jobs jobs.json --out DIR --sheet

    # 换豆包 Seedream（需 ~/.dsh/secrets/ark_api_key）
    python3 scripts/album_covers.py --jobs jobs.json --out DIR --provider seedream --model pro

提示词结构与选型参考 `references/18_专辑封面出图.md`；
风格模板来自 `gpt-image-2-style-library` 技能（先看那本再写 prompt）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent          # sream-studio/
WS = W.parent                                        # 工作区
TOOLS = Path(os.environ.get("TOOLS_DIR", WS / "tools"))
ARK_KEY_FILE = Path.home() / ".dsh/secrets/ark_api_key"
SEEDREAM = Path.home() / ".agents/skills/byted-ark-seedream-skill/scripts/generate.js"

# 提示词块：subject → scene → palette → text → style → constraints
PROMPT = (
    "正方形 {aspect} 构图的音乐专辑封面。{scene}。"
    "主色为{palette}。{style}"
    "画面上方居中写中文大字「{album}」，下方写一行中文小字「{slogan}」，"
    "字体简洁端正、文字清晰、不要错字、不要英文、不要水印。"
)


def load_jobs(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    if "jobs" not in d or not isinstance(d["jobs"], list):
        raise SystemExit("❌ 题单缺少 jobs 数组")
    for i, j in enumerate(d["jobs"]):
        for k in ("tag", "scene"):
            if not j.get(k):
                raise SystemExit(f"❌ 第 {i+1} 条缺 {k}")
        j.setdefault("slogan", "")
        j.setdefault("style", "")
        j.setdefault("palette", "清透的蓝天与青绿草甸，白云蓬松，不要偏黄、不要夕阳暖调")
    d.setdefault("album", "")
    d.setdefault("aspect", "1:1")
    d.setdefault("outsize", "1920x1920")
    return d


def build_prompt(job: dict, d: dict) -> str:
    return PROMPT.format(
        aspect=d["aspect"], album=d["album"], slogan=job["slogan"],
        scene=job["scene"], palette=job["palette"], style=job["style"],
    ).replace("。。", "。").replace("，，", "，")


def gen_gpt(prompt: str, out: Path, d: dict, tag: str) -> None:
    sys.path.insert(0, str(TOOLS))
    from llm_client import load_image_models, gen_image      # noqa: E402

    models, err = load_image_models()                        # ⚠️ 返回 (list, err)
    if err or not models:
        raise SystemExit(f"❌ 读取图片模型配置失败：{err}")
    m = next((x for x in models if x.get("tag") == tag), models[0])
    gen_image(m, prompt, size=d["aspect"], out_size=d["outsize"], out_path=str(out))


def gen_seedream(prompt: str, out: Path, d: dict, model: str = "pro") -> None:
    if not ARK_KEY_FILE.is_file():
        raise SystemExit(f"❌ 缺 {ARK_KEY_FILE}")
    env = dict(os.environ, ARK_SEEDREAM_SAVE_PATH=str(out.parent))
    r = subprocess.run(
        ["node", str(SEEDREAM), "--model", model, "--size", d["outsize"],
         "--watermark", "false", "--prompt", prompt,
         "--api-key", ARK_KEY_FILE.read_text(encoding="utf-8").strip()],
        capture_output=True, text=True, env=env)
    if r.returncode:
        raise SystemExit(f"❌ Seedream 失败：{(r.stderr or r.stdout)[:300]}")
    got = sorted(out.parent.rglob("*.jpg"))
    if not got:
        raise SystemExit("❌ Seedream 未产出图片")
    got[-1].replace(out)


def make_sheets(images: list[Path], out_dir: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(WS / "mv/fonts/方正粗黑宋简体.ttf"), 26)
    T, cols = 460, 4
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (T * cols, T * rows), "white")
    for i, f in enumerate(images):
        im = Image.open(f).resize((T, T))
        d = ImageDraw.Draw(im)
        d.rectangle([0, T - 34, T, T], fill=(0, 0, 0))
        d.text((8, T - 30), f.stem, font=font, fill="white")
        sheet.paste(im, ((i % cols) * T, (i // cols) * T))
    sheet.save(out_dir / "_总览.jpg", quality=90)

    # 文字裁切图（核对中文：标题 + 概语区）
    crops = []
    for f in images:
        im = Image.open(f)
        w, h = im.size
        c = im.crop((int(w * 0.04), int(h * 0.03), int(w * 0.96), int(h * 0.38)))
        c = c.resize((900, int(900 * c.size[1] / c.size[0])), Image.LANCZOS)
        crops.append(c)
    if crops:
        th = max(c.size[1] for c in crops)
        tsheet = Image.new("RGB", (900, th * len(crops)), "white")
        for i, c in enumerate(crops):
            tsheet.paste(c, (0, i * th))
        tsheet.save(out_dir / "_文字核对.jpg", quality=92)
    print(f"  ✅ 总览/文字核对图 → {out_dir}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", required=True, help="题单 JSON")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--provider", choices=("gpt", "seedream"), default="gpt")
    ap.add_argument("--model", default="pro", help="seedream: lite/pro")
    ap.add_argument("--tag", default="", help="gpt: 指定模型 tag（默认第一个）")
    ap.add_argument("--only", default="", help="只出某个 tag（逗号分隔）")
    ap.add_argument("--sheet", action="store_true", help="出总览图 + 文字核对图")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    d = load_jobs(Path(a.jobs))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = {x.strip() for x in a.only.split(",") if x.strip()}

    made = []
    for j in d["jobs"]:
        if wanted and j["tag"] not in wanted:
            continue
        prompt = build_prompt(j, d)
        dst = out / f"{j['tag']}.jpg"
        if a.dry_run:
            print(f"\n── {j['tag']}（{d['outsize']}）\n{prompt}")
            continue
        if dst.is_file() and dst.stat().st_size > 10_000:
            print(f"  ⏭ {j['tag']} 已存在")
            made.append(dst)
            continue
        print(f"  ⏳ {j['tag']} …", flush=True)
        if a.provider == "seedream":
            gen_seedream(prompt, dst, d, a.model)
        else:
            gen_gpt(prompt, dst, d, a.tag)
        made.append(dst)
        print(f"  ✅ {dst.name}")

    if a.dry_run:
        return 0
    if a.sheet and made:
        make_sheets(made, out)
    print(f"\n完成 {len(made)} 张 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
