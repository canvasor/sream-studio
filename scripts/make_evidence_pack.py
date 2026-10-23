#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「创作过程证据包」—— 时间戳存证 / 版权登记 / 维权举证 用

整理已有归档材料、复制校验与音频指纹。文件快照不单独证明创作时间或权利归属。

⚠️ 本包是**内部举证材料**，不对外传（含绝对路径、Suno 账号归属等信息）。
   对外材料按接收方要求另行审阅；本脚本不生成授权结论。

产出（每首一个目录 + 一个 zip）：
    <out>/<歌名>_存证包_<日期>/
        ├── 00_存证说明.md          ← 人看的：这份包证明了什么
        ├── 01_清单_SHA256.txt       ← 每个文件的 SHA256，防篡改
        ├── 02_manifest.json        ← 机器可读：文件清单 + 指纹 + 时间
        ├── 03_歌词/                ← 纯文本 + Suno 结构版（不同版本=迭代证据）
        ├── 04_生成配置/            ← Styles / Exclude / suno_config.json / 参数卡
        ├── 05_音频指纹.txt         ← 母版时长/采样率/SHA256
        ├── 06_封面/                ← 封面图（作品与视觉的关联证据）
        ├── 07_文件时间线.txt       ← 按 mtime 排序的佐证时间轴
        └── 08_Suno生成记录/        ← 平台生成记录截图（第三方证据）

用法：
    python3 scripts/make_evidence_pack.py --song 端一壶酥油茶
    python3 scripts/make_evidence_pack.py --album 高原三帖
    python3 scripts/make_evidence_pack.py --all
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from _release_common import check_song, library_dir, load_songs, workspace_dir

LIB = library_dir()
OUT = Path(os.environ.get('EVIDENCE_OUT') or workspace_dir() / '账号资料/创作证据包').expanduser()

ALBUM = {"端一壶酥油茶": "高原三帖", "铜铃摇在帐篷边": "高原三帖", "青稞熟了茶还烫": "高原三帖"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(p: Path) -> dict:
    """音频规格：时长/采样率/声道/码率"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,bit_rate:stream=sample_rate,channels,codec_name",
             "-of", "json", str(p)],
            capture_output=True, text=True, timeout=60, check=True).stdout
        j = json.loads(out or "{}")
        st = (j.get("streams") or [{}])[0]
        fm = j.get("format") or {}
        return {"duration_s": round(float(fm.get("duration") or 0), 2),
                "sample_rate": st.get("sample_rate"),
                "channels": st.get("channels"),
                "codec": st.get("codec_name"),
                "bit_rate": fm.get("bit_rate")}
    except Exception as e:
        return {"error": str(e)[:120]}


def collect(j: dict) -> list:
    """收集该曲所有可作证据的本地文件"""
    d = check_song(j, LIB)
    files = []
    if not d.is_dir():
        return files
    covers = sorted(p.name for p in d.glob('03_封面*') if p.is_dir())
    for sub in ("01_音频母版", *covers, "04_歌词", "06_文档", "05_生成记录"):
        p = d / sub
        if p.is_symlink():
            raise ValueError(f'证据源不能为符号链接：{p.name}')
        if p.is_dir():
            for x in sorted(p.rglob('*')):
                if x.is_symlink():
                    raise ValueError(f'证据源不能包含符号链接：{x.name}')
                if x.is_file() and x.stat().st_size > 0:
                    files.append(x)
    return files


def build(j: dict, today: str, dry_run: bool = False) -> Path:
    name = j["name"]
    files = collect(j)
    if not files:
        print(f"  ⚠️ {name}: 作品库/{j['lib_dir']} 里没有找到文件，跳过")
        return None

    pack = OUT / f"{name}_存证包_{today}"
    zip_path = OUT / f"{name}_存证包_{today}.zip"
    if pack.exists() or zip_path.exists():
        raise FileExistsError('已有同名证据包或 ZIP；请用 --out 选择新的输出父目录，不覆盖旧证据')
    if LIB.resolve() == OUT.resolve() or LIB.resolve() in OUT.resolve().parents:
        raise ValueError('证据包输出必须位于作品库之外，避免递归收集')
    if dry_run:
        print(f'  预览：{name}，{len(files)} 个源文件 → {pack}（不写文件）')
        return pack
    pack.mkdir(parents=True)

    # 分目录拷贝 + 记录
    entries = []
    for f in files:
        rel = f.relative_to(LIB / j["lib_dir"])
        kind = rel.parts[0]
        bucket = {
            "01_音频母版": "05_音频指纹",   # 音频本体不进包（太大），只留指纹
            "03_封面": "06_封面",
            "04_歌词": "03_歌词",
            "06_文档": "04_生成配置",
            "05_生成记录": "08_Suno生成记录",   # 平台生成记录截图 = 最直接的第三方证据
        }.get(kind, '06_封面' if kind.startswith('03_封面') else "04_生成配置")
        digest = sha256(f)
        entries.append({
            "path": str(rel), "bucket": bucket, "bytes": f.stat().st_size,
            "sha256": digest,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
        })
        if bucket != "05_音频指纹":
            # Keep alternative cover sets separate from the original covers.
            nested = rel.parts if kind.startswith('03_封面') and kind != '03_封面' else rel.parts[1:]
            dst = pack / bucket / Path(*nested)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            if sha256(dst) != digest:
                raise OSError(f'证据复制校验失败：{rel}')
            entries[-1]['pack_path'] = dst.relative_to(pack).as_posix()

    # 音频指纹
    audio = LIB / j["lib_dir"] / "01_音频母版" / j["wav"]
    spec = probe(audio) if audio.is_file() else {}
    (pack / "05_音频指纹.txt").write_text(
        f"""音频母版指纹 · 《{name}》

文件      : {j['wav']}
SHA256    : {sha256(audio) if audio.is_file() else '（母版缺失）'}
字节数    : {audio.stat().st_size if audio.is_file() else 0}
时长      : {spec.get('duration_s')} 秒（{j['dur']}）
采样率    : {spec.get('sample_rate')} Hz
声道      : {spec.get('channels')}
编码      : {spec.get('codec')}
码率      : {spec.get('bit_rate')}

⚠️ 音频本体不放进存证包（体积大）。做时间戳时**单独上传母版**，
   或用本文件里的 SHA256 与母版比对，证明「这份母版就是当时那一份」。
""", encoding="utf-8")

    # manifest
    (pack / "02_manifest.json").write_text(json.dumps({
        "song": name, "album": j.get('album', ALBUM.get(name, '')), "lib_dir": j["lib_dir"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "platform_credit": "词/曲/演唱：Sream（AI辅助）",
        "artist": "Sream 锦霖",
        "files": entries,
        "audio_master": spec,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 时间线
    tl = sorted(entries, key=lambda e: e["mtime"])
    (pack / "07_文件时间线.txt").write_text(
        f"""《{name}》文件时间线（按文件修改时间排序）

⚠️ 说明：文件系统时间可被篡改，**不能单独作为权利证明**。
   它只是辅助梳理「创作到成品的先后顺序」。
   真正的在先证据要靠：①时间戳存证 ②版权登记 ③平台首发记录。

""" + "".join(f"{e['mtime']}  {e['path']}\n" for e in tl), encoding="utf-8")

    # 存证说明
    (pack / "00_存证说明.md").write_text(
        f"""# 创作过程证据包 · 《{name}》

> 所属专辑：**《{j.get('album', ALBUM.get(name, ''))}》**　｜　打包日期：{today}
> 署名：**Sream 锦霖**；权利人身份与授权材料请另行核实。

## 这份包证明了什么

1. **现有文件快照**：收集实际存在的歌词、配置、封面与生成记录；缺失内容不会自动补齐
2. **参数待核对**：Styles / Exclude / suno_config.json 为当前归档文件，不自动证明与生成时输入一致
3. **音频可校验**：母版 SHA256 写进 `05_音频指纹.txt`，可与任何一份音频比对

## 怎么用

| 场景 | 用法 |
|---|---|
| **时间戳存证** | 按存证服务要求提交本包与母版，保留回执；本脚本不执行提交 |
| **版权登记** | 依受理机构要求准备歌词、录音及创作说明；本包本身不证明权利归属 |
| **被反向投诉时申诉** | 提交本包 + 时间戳证书 + 平台首发后台截图 |

## ⚠️ 本包不对外

含内网路径与本地文件时间，**只用于存证与举证**，不要上传给音乐平台。
对平台上传用的是另一套干净版：`账号资料/权利说明/权利说明_{name}.pdf`。

## 目录

```
00_存证说明.md      本文件
01_清单_SHA256.txt  每个文件的 SHA256（防篡改）
02_manifest.json    机器可读清单
03_歌词/            歌词（多个版本 = 迭代证据）
04_生成配置/        Styles / Exclude / suno_config.json
05_音频指纹.txt     母版规格 + SHA256
06_封面/            封面图
07_文件时间线.txt   按 mtime 排序（辅助，非核心证据）
```
""", encoding="utf-8")

    # Checksum paths refer to actual package files, including generated metadata.
    (pack / '01_清单_SHA256.txt').write_text(''.join(
        f'{sha256(f)}  {f.relative_to(pack).as_posix()}\n'
        for f in sorted(pack.rglob('*')) if f.is_file()
    ), encoding='utf-8')
    with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(pack.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(OUT))
    print(f"  ✅ {name}: {len(entries)} 个文件 → {zip_path.name}"
          f"（{zip_path.stat().st_size/1024:.0f}KB）")
    return pack


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default=None)
    ap.add_argument("--album", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument('--out', type=Path, help='新的输出父目录；已有包不会覆盖')
    ap.add_argument('--dry-run', action='store_true', help='只清点，不创建目录或 ZIP')
    a = ap.parse_args()

    global OUT
    if a.out:
        OUT = a.out.expanduser()

    today = datetime.now().strftime("%Y%m%d")
    picked = []
    for j in load_songs():
        if a.all:
            picked.append(j)
        elif a.song and a.song in j["name"]:
            picked.append(j)
        elif a.album and j.get('album', ALBUM.get(j["name"])) == a.album:
            picked.append(j)
    if not picked:
        sys.exit("❌ 没有匹配到歌曲（用 --song / --album / --all）")

    print(f"打证据包：{len(picked)} 首 → {OUT}")
    ok = 0
    for j in picked:
        if build(j, today, a.dry_run):
            ok += 1
    print(f"\n共 {ok} 首 → {OUT}")


if __name__ == "__main__":
    main()
