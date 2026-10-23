#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 PDF 还原被覆盖的「AI 生成记录档案」.md

从同名 PDF 提取档案结构，Styles / Lyrics 从 `04_歌词/歌词_Suno原文.md` 取全文。
已有 Markdown 默认跳过；显式 --force 替换前会备份。缺少完整原文时停止，保留原档案。

用法：
    python3 scripts/recover_generation_record.py --all
    python3 scripts/recover_generation_record.py --song 纸箱里的月亮
"""
import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from _release_common import check_song, library_dir, load_songs, write_record

LIB = library_dir()

HEADINGS = [
    "歌曲信息", "AI 工具使用记录", "Suno Styles", "Suno Lyrics",
    "版权与授权", "交付物存档", "备注",
]


def pdf_text(pdf: Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                          capture_output=True, text=True, timeout=120, check=True).stdout


def suno_parts(md: Path) -> tuple:
    """从 歌词_Suno原文.md 取完整 Styles / Lyrics"""
    if not md.is_file():
        return "", ""
    t = md.read_text(encoding="utf-8", errors="ignore")
    def grab(name):
        m = re.search(rf"###\s*{name}\s*\n+```[^\n]*\n(.*?)\n```", t, re.S)
        return m.group(1).strip() if m else ""
    return grab("Styles"), grab("Lyrics")


def split_sections(text: str) -> dict:
    """按已知标题切段"""
    lines = text.splitlines()
    out, cur, buf = {}, "前言", []
    for ln in lines:
        # ⚠️ 表格行也可能以标题词开头（如 "Suno Styles 全文   见下方"），
        #    用「行内是否有多空格对齐」排除掉，否则会误切段
        s = ln.strip()
        hit = None
        if not re.search(r"\s{2,}", s):
            hit = next((h for h in HEADINGS if s.startswith(h)), None)
        if hit:
            out[cur] = buf
            cur, buf = hit, []
        else:
            buf.append(ln)
    out[cur] = buf
    return out


def rows_to_table(lines: list, drop_first: bool = True) -> str:
    """把「键    值」空格对齐的块转成 markdown 表格"""
    rows = []
    for ln in lines:
        if not ln.strip():
            continue
        parts = re.split(r"\s{2,}", ln.strip(), maxsplit=1)
        if len(parts) == 2:
            rows.append((parts[0].strip(), parts[1].strip()))
        elif len(parts) == 1:
            rows.append((parts[0].strip(), ""))
    if not rows:
        return ""
    if drop_first and rows[0][0] in ("项目", "文件"):
        head, body = rows[0], rows[1:]
    else:
        head, body = ("项目", "内容"), rows
    md = [f"| {head[0]} | {head[1]} |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in body]
    return "\n".join(md)


def recover(j: dict, force: bool = False, dry_run: bool = False) -> bool:
    name = j["name"]
    directory = check_song(j, LIB)
    d = directory / "05_生成记录"
    out = d / f'{name}.md'
    if out.exists() and not force:
        print(f'  跳过已有档案：{name}（--force 会先备份再替换）')
        return False
    pdf = d / f"{name}.pdf"
    if not pdf.is_file():
        print(f"  ⚠️ {name}: 没有 PDF，跳过")
        return False
    text = pdf_text(pdf)
    if len(text) < 300:
        print(f"  ⚠️ {name}: PDF 取样太少，跳过")
        return False

    sec = split_sections(text)
    styles, lyrics = suno_parts(directory / "04_歌词/歌词_Suno原文.md")
    if not styles or not lyrics:
        print(f'  {name}：缺少完整 Styles / Lyrics，停止还原，未修改档案')
        return False
    if not {'歌曲信息', 'AI 工具使用记录'}.issubset(sec):
        print(f'  {name}：PDF 缺少预期档案结构，停止还原，未修改档案')
        return False

    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), f"AI 生成记录档案 · {name}")
    quote = [ln.strip() for ln in sec.get("前言", [])
             if ln.strip() and ln.strip() != first][:3]

    md = [f"# {first}", ""]
    if quote:
        md += [f"> {ln}" for ln in quote]
        md += [""]

    # 歌曲信息
    if "歌曲信息" in sec:
        t = rows_to_table(sec["歌曲信息"])
        if t:
            md += ["## 歌曲信息", "", t, ""]

    # AI 工具使用记录
    if "AI 工具使用记录" in sec:
        t = rows_to_table(sec["AI 工具使用记录"])
        if t:
            md += ["## AI 工具使用记录", "",
                   "> 从 PDF 提取；提交要求与内容需另行核实。", "", t, ""]

    # Styles / Lyrics（用完整原文，PDF 会截断）
    md += ["## Suno Styles（Suno 记录原文）", "", "```",
           styles or "（原 Styles 缺失，请从 Suno 页面补录）", "```", ""]
    md += ["## Suno Lyrics（Suno 记录原文）", "", "```",
           lyrics or "（原歌词缺失）", "```", ""]

    # 版权与授权
    if "版权与授权" in sec:
        t = rows_to_table(sec["版权与授权"])
        if t:
            md += ["## 版权与授权", "", t, ""]

    # 交付物存档 / 备注（保留原排版，避免表格错乱）
    for h in ("交付物存档", "备注"):
        if h in sec:
            body = [ln.rstrip() for ln in sec[h]]
            while body and not body[0].strip():
                body.pop(0)
            while body and not body[-1].strip():
                body.pop()
            if body:
                md += [f"## {h}", "", "```text"] + body + ["```", ""]

    md += ["---", "",
           f"> 本文件于 {datetime.now().date().isoformat()} 由 `recover_generation_record.py` 从同名 PDF 提取；",
           "> Styles / Lyrics 两段改取自 `04_歌词/歌词_Suno原文.md`（完整版）。",
           "> 提取结果需与 PDF 和原始配置人工比对，不能代替平台原始生成日志。", ""]

    if not write_record(out, '\n'.join(md), force=force, dry_run=dry_run):
        return False
    if dry_run:
        return True
    print(f"  ✅ {name}: 还原 {len(md)} 行（Styles {len(styles)} 字 / Lyrics {len(lyrics)} 字）")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument('--force', action='store_true', help='先备份再替换已有档案')
    ap.add_argument('--dry-run', action='store_true', help='只读提取与核对，不写入或备份')
    a = ap.parse_args()
    picked = [j for j in load_songs() if a.all or (a.song and a.song in j["name"])]
    if not picked:
        sys.exit("❌ 没匹配到")
    ok = sum(recover(j, a.force, a.dry_run) for j in picked)
    print(f"\n还原 {ok} 首")


if __name__ == "__main__":
    main()
