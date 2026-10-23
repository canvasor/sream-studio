#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「AI 生成记录档案」—— 腾讯音乐版权登记 / 客户核验 / 内部举证用

这是当前归档材料的整理草稿，缺失信息与事实声明需核实。
对外提交前另行审阅；已有档案默认保留，显式替换会先备份。

用法：
    python3 scripts/make_generation_record.py --album 高原三帖
    python3 scripts/make_generation_record.py --song 端一壶酥油茶
    python3 scripts/make_generation_record.py --all
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from _release_common import check_song, library_dir, load_songs, write_record

LIB = library_dir()

ALBUM = {"端一壶酥油茶": "高原三帖", "铜铃摇在帐篷边": "高原三帖", "青稞熟了茶还烫": "高原三帖"}
VOICE = {"端一壶酥油茶": "男声", "铜铃摇在帐篷边": "女声", "青稞熟了茶还烫": "女声"}
BPM = {"端一壶酥油茶": 88, "铜铃摇在帐篷边": 84, "青稞熟了茶还烫": 92}
STYLE = {
    "端一壶酥油茶": "高原民谣情歌（Mandarin plateau folk love ballad）",
    "铜铃摇在帐篷边": "草原民谣情歌（Mandarin grassland love ballad）",
    "青稞熟了茶还烫": "高原民谣情歌（Mandarin plateau love ballad）",
}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore").strip() if p.is_file() else "（缺失）"


def build(j: dict, force: bool = False, dry_run: bool = False) -> Path:
    name = j["name"]
    d = check_song(j, LIB)
    if not d.is_dir():
        raise FileNotFoundError(f'作品目录不存在：{j["lib_dir"]}')
    cfg = d / "06_文档"
    lyr = d / "04_歌词"

    styles = read(cfg / "Styles.txt")
    excl = read(cfg / "Exclude.txt")
    lyrics = read(lyr / f"{name}_歌词_纯文本.txt")
    suno_ly = read(lyr / f"{name}_歌词_Suno结构.txt")
    conf = read(cfg / "suno_config.json")
    shots = sorted((d / "05_生成记录").glob("*.png")) if (d / "05_生成记录").is_dir() else []

    out_dir = d / "05_生成记录"
    out = out_dir / f"{name}.md"

    # 默认保留已有记录；显式替换仍保存独立备份。
    if out.is_file() and not force:
        print(f"  ⏭ {name}: 档案已存在，跳过（--force 可强制覆盖）")
        return out

    content = f"""# AI 生成记录整理草稿 · {name}

> **用途**：整理当前归档文件，供人工核实生成过程；不等同平台原始生成日志。
> **归档位置**：`{j['lib_dir']}/05_生成记录/{name}.md`（相对作品库）
> **内部待核实草稿**：不自动证明授权、创作经历或权利归属；对外提交前另行审阅。

---

## 歌曲信息

| 项目 | 内容 |
|---|---|
| **歌曲名** | {name} |
| **所属专辑** | {j.get('album', ALBUM.get(name, '待核实'))} |
| **时长** | {j['dur']}（{j['wav']}）|
| **曲风** | {STYLE.get(name, '')} |
| **速度 / 声部** | {BPM.get(name, '?')} BPM · {VOICE.get(name, '')} |
| **署名** | 词/曲/演唱：Sream（AI辅助）|
| **歌词来源** | {j.get('ly_src', '待核实')} |
| **30 秒窗口** | {j.get('clip_start', '')}s 起（副歌入点见作品说明）|
| **发布状态** | 待核实，以平台后台记录为准 |

---

## 当前归档配置（是否为生成时原文待核实）

### Styles（风格提示词）

```
{styles}
```

### Exclude（排除项）

```
{excl}
```

### Lyrics（Suno 结构版）

```
{suno_ly}
```

### suno_config.json

```json
{conf}
```

---

## 歌词全文（纯文本）

```
{lyrics}
```

---

## 生成记录截图

{"".join(f"- `{p.name}`（{p.stat().st_size/1024:.0f}KB）" + chr(10) for p in shots) or "- ⚠️ 未放入截图，请把 Suno 后台的生成记录截图存到本目录"}

---

## 授权材料待核实

- 生成日期、作品链接或平台任务编号：待补录。
- 生成时适用的账号、套餐与订阅凭证：待补录，不从当前下载日期推断。
- 当时适用的服务条款、许可范围与素材来源：待核实并保留对应证据。
- 本草稿不自动判断可否商用或是否享有版权。

---

## 人工介入说明

请根据实际过程填写歌词修改、提示词调整、版本筛选、后期处理等操作，
并关联原始稿件、工程或操作记录。未提供记录时，不自动声称这些步骤已完成。

---

**档案生成时间**：{datetime.now().isoformat(timespec="seconds")}
**状态**：本文件仅整理生成时可读取的归档内容；缺失项与事实陈述须人工核实。
"""
    if not write_record(out, content, force=force, dry_run=dry_run):
        return out
    if dry_run:
        return out
    print(f"  ✅ {name} → 05_生成记录/{out.name}（Styles {len(styles)} 字 / 歌词 {len(lyrics)} 字 / 截图 {len(shots)} 张）")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default=None)
    ap.add_argument("--album", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="先备份再替换已有档案（默认跳过）")
    ap.add_argument('--dry-run', action='store_true', help='预览，不写入或备份文件')
    a = ap.parse_args()
    picked = [j for j in load_songs()
              if a.all
              or (a.song and a.song in j["name"])
              or (a.album and j.get('album', ALBUM.get(j["name"])) == a.album)]
    if not picked:
        sys.exit("❌ 没匹配到歌曲")
    for j in picked:
        build(j, a.force, a.dry_run)


if __name__ == "__main__":
    main()
