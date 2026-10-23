#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾车行车 MV：一首歌 → 竖屏歌词 MV（前 3 秒封面 + 行车画面 + 逐句歌词）。

流程见 references/16_驾车行车MV.md。要点：
  · 素材累计时长 ≥ 歌曲时长，**不循环**，段间 0.5s 溶解
  · whisper 只取**时间轴**，文字用 `--lyrics` 给的**正确歌词**替换
  · 封面/字幕/音轨**一趟 ffmpeg 出**，避免多次编码掉画质

用法：
    python scripts/drive_mv.py --song 歌.mp3 --title 歌名 --singer 演唱者 \
        --lyrics 歌词.txt --clips A.mp4,B.mp4 --out 输出目录
    python scripts/drive_mv.py --song 歌.mp3 --title 歌名 --clips A.mp4 --out out --dry-run

环境变量：
    PEXELS_API_KEY   没给 --clips 时用于搜索素材（也可从 MPT 配置读取）
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
import urllib.request

W = pathlib.Path(__file__).resolve().parent.parent


def _ensure_deps(need_whisper: bool = True) -> None:
    """缺 soundfile/faster_whisper/PIL 时，自动切到带依赖的解释器再跑。"""
    need = ('soundfile', 'faster_whisper', 'PIL') if need_whisper else ('PIL',)
    import importlib.util as _ilu
    missing = [m for m in need if _ilu.find_spec(m) is None]
    if not missing:
        return
    import shutil as _sh
    cands = [os.environ.get("PY", ""), str(W.parent / "tools/venv-sep/bin/python"),
             str(W / "tools/venv-sep/bin/python")]
    for c in cands:
        if c and pathlib.Path(c).is_file() and c != sys.executable:
            probe = subprocess.run([c, "-c", 'import ' + ', '.join(need)],
                                   capture_output=True)
            if probe.returncode == 0:
                os.execv(c, [c, str(pathlib.Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit(f"❌ 缺依赖 {missing}；请用带这些库的解释器运行，"
             f"或设 PY=/path/to/python（如 tools/venv-sep/bin/python）")

UA = ("Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
FONT_CN = None          # 运行时按候选路径查找，见 find_font()


def find_whisper_model(explicit: str = "") -> str:
    """whisper 模型候选：显式参数 → 环境变量 → 仓库内 → 工作区 → 官方名(会自动下载)。"""
    cands = []
    for c in (explicit, os.environ.get("DRIVE_MV_WHISPER", "")):
        if c and c.strip():
            cands.append(pathlib.Path(c.strip()))
    for base in (W, W.parent):
        cands.append(base / ".hf/fw-small")
        cands.append(base / ".hf/faster-whisper-small")
    for c in cands:
        if c.is_dir():
            return str(c)
    return "small"      # 让 faster-whisper 自己去下载


def find_font() -> str:
    """字体候选：环境变量 → 仓库内 → 工作区 mv/fonts → 系统 CJK 兜底。"""
    cands = []
    env = os.environ.get("DRIVE_MV_FONT", "").strip()
    if env:
        cands.append(pathlib.Path(env))
    for base in (W, W.parent):
        cands.append(base / "mv/fonts/汉仪超粗圆简.ttf")
        cands.append(base / "mv/fonts/汉仪超粗圆简.ttf".replace("汉仪超粗圆简", "HYChaocuYuan"))
    cands += [pathlib.Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"),
              pathlib.Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")]
    for c in cands:
        if c.is_file():
            return str(c)
    raise FileNotFoundError("找不到中文字体（可用 DRIVE_MV_FONT 指定）")


def sh(cmd, **kw) -> int:
    print("  ▶", " ".join(str(c) for c in cmd), flush=True)
    kw.setdefault('cwd', str(W))
    rc = subprocess.run(cmd, **kw).returncode
    if rc != 0:
        sys.exit(f"❌ 命令失败（exit {rc}）：{cmd[0]}")
    return rc


def probe_duration(path) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    duration = float(result.stdout.strip() or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f'{pathlib.Path(path).name}: 无效的媒体时长')
    return duration


def pexels_key() -> str:
    k = os.environ.get("PEXELS_API_KEY", "").strip()
    if k:
        return k
    for p in (pathlib.Path.home() / "MoneyPrinterTurbo/config.toml",):
        if p.is_file():
            m = re.search(r'pexels_api_keys\s*=\s*\[\s*"([^"]+)"', p.read_text(encoding="utf-8", errors="ignore"))
            if m:
                return m.group(1)
    return ""


def search_clips(query: str, min_dur: int, need: float, out: pathlib.Path) -> list[pathlib.Path]:
    """Pexels 搜纵向行车素材，按时长降序取够 need 秒。"""
    key = pexels_key()
    if not key:
        sys.exit("❌ 缺 PEXELS_API_KEY（或 --clips 指定已有素材）")
    out.mkdir(parents=True, exist_ok=True)
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "portrait", "per_page": 15, "size": "medium"})
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        vids = json.loads(r.read()).get("videos", [])
    vids = [v for v in vids if (v.get("duration") or 0) >= min_dur]
    vids.sort(key=lambda v: -(v.get("duration") or 0))
    picked, total = [], 0.0
    for v in vids:
        if total >= need:
            break
        f = next((x for x in v["video_files"]
                  if 1000 <= (x.get("width") or 0) <= 1500), None) \
            or max(v["video_files"], key=lambda x: x.get("width") or 0)
        dst = out / f"{v['id']}_{v.get('duration')}s.mp4"
        if not (dst.is_file() and probe_duration(dst) > 5):
            print(f"  ⬇ {v['id']} {v.get('duration')}s", flush=True)
            rq = urllib.request.Request(f["link"], headers={"User-Agent": UA})
            with urllib.request.urlopen(rq, timeout=900) as rr, open(dst, "wb") as fh:
                shutil.copyfileobj(rr, fh, 1 << 20)
        d = probe_duration(dst)
        if d < 5:
            print(f"  ⚠️ {dst.name} 时长异常 {d}s，跳过")
            continue
        picked.append(dst)
        total += d
    if total < need:
        print(f"  ⚠️ 搜到的素材合计 {total:.1f}s < 需要 {need:.1f}s，将用慢放补齐")
    return picked


def video_graph(durations: list[float], need: float, aspect: tuple[int, int],
                cover_sec: float, has_cover: bool) -> str:
    """Assemble original clips, cover and subtitles before either final encoder."""
    w, h = aspect
    if (not durations or any(not math.isfinite(d) or d <= 0 for d in durations)
            or not math.isfinite(need) or need <= 0
            or w <= 0 or h <= 0 or w % 2 or h % 2
            or not math.isfinite(cover_sec) or cover_sec < 0):
        raise ValueError('媒体时长、封面时长或画幅无效；画幅须为正偶数')
    fade = min(0.5, min(durations) / 2) if len(durations) > 1 else 0
    # Transition overlap is fixed in output seconds, so include it before stretching.
    stretch = max(1.0, (need + fade * (len(durations) - 1)) / sum(durations))
    parts = []
    for i in range(len(durations)):
        parts.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,format=yuv420p,"
            f"setpts=(PTS-STARTPTS)*{stretch:.9f},fps=30,settb=AVTB[v{i}]")
    prev = 'v0'
    acc = durations[0] * stretch
    for i in range(1, len(durations)):
        nxt = f'x{i}'
        parts.append(f'[{prev}][v{i}]xfade=transition=fade:duration={fade:.9f}:'
                     f'offset={acc - fade:.9f}[{nxt}]')
        acc += durations[i] * stretch - fade
        prev = nxt
    if has_cover:
        parts.append(f'[{prev}][{len(durations) + 1}:v]overlay=0:0:'
                     f"enable='lt(t,{cover_sec:.9f})'[covered]")
        prev = 'covered'
    # The command runs in _work, avoiding filter escaping for user directory names.
    parts.append(f'[{prev}]ass=filename=lyrics.ass,split=2[hi][upload]')
    return ';'.join(parts)


def transcribe(song: pathlib.Path, model_dir: pathlib.Path) -> list[dict]:
    """whisper 只取时间轴；喂 numpy 数组绕开 PyAV 版本问题。"""
    import soundfile as sf
    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory(prefix='drive_mv_') as temp:
        tmp = pathlib.Path(temp) / 'asr16k.wav'
        sh(["ffmpeg", "-v", "error", "-y", "-i", str(song), "-ac", "1", "-ar", "16000", str(tmp)])
        a, sr = sf.read(tmp, dtype="float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    m = WhisperModel(str(model_dir), device="cpu", compute_type="int8")
    segs, _ = m.transcribe(a, language="zh", word_timestamps=False,
                           vad_filter=False, beam_size=5)
    rows = []
    for s in segs:
        t = (s.text or "").strip()
        if not re.search(r"[\u4e00-\u9fff]", t):     # 丢掉 "Zither Harp" 之类
            continue
        rows.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": t})
    return rows


def aligned_lyrics(rows: list[dict], lyrics: list[str] | None,
                   duration: float | None = None) -> list[dict]:
    """Reject obvious line/timing mismatches instead of publishing ASR text."""
    if not lyrics or not rows or len(lyrics) != len(rows):
        raise ValueError(f'歌词与时间轴不匹配：歌词{len(lyrics or [])}行，时间轴{len(rows)}段；请校对时间轴后用--timings重试')
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise ValueError('歌曲时长无效')

    def normalized(text):
        return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())

    result, last_end = [], 0.0
    for i, (row, lyric) in enumerate(zip(rows, lyrics), 1):
        if not isinstance(row, dict) or not isinstance(lyric, str):
            raise ValueError(f'第{i}句时间轴或歌词格式无效')
        try:
            start, end = float(row['start']), float(row['end'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'第{i}句缺少有效start/end') from exc
        if (not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start
                or start < last_end - 0.01 or (duration is not None and end > duration + 0.05)):
            raise ValueError(f'第{i}句时间范围无效、重叠或超出歌曲；请用--timings修正')
        text = row.get('text')
        if not isinstance(text, str):
            raise ValueError(f'第{i}句缺少可核对的时间轴文字')
        expected, recognized = normalized(lyric), normalized(text)
        if (not expected or not recognized
                or SequenceMatcher(None, expected, recognized, autojunk=False).ratio() < 0.75):
            raise ValueError(f'第{i}句文字与时间轴明显不匹配；请校对后用--timings重试')
        result.append(dict(start=start, end=end, text=lyric.strip()))
        last_end = end
    return result


def build_ass(rows: list[dict], lyrics: list[str] | None, dst: pathlib.Path,
              font_size: int = 96, margin_v: int = 300,
              duration: float | None = None) -> None:
    rows = aligned_lyrics(rows, lyrics, duration)

    def ts(t):
        return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1440
PlayResY: 2560
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lyric,汉仪超粗圆简,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,9,3,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = "".join(
        f"Dialogue: 0,{ts(r['start'])},{ts(r['end'])},Lyric,,0,0,0,,{r['text']}\n" for r in rows)
    dst.write_text(head + body, encoding="utf-8")


def render_cover(title: str, singer: str, label: str, dst: pathlib.Path,
                 aspect: tuple[int, int]) -> None:
    from PIL import Image, ImageDraw, ImageFont
    w, h = aspect
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    font_path = find_font()

    def f(sz):
        return ImageFont.truetype(font_path, sz)

    def put(xy, text, sz, sw):
        d.text(xy, text, font=f(sz), fill="white", anchor="mm",
               stroke_width=sw, stroke_fill="black")

    put((w // 2, int(h * 0.15)), f"《{title}》", 112, 10)
    put((w // 2, int(h * 0.225)), f"演唱：{singer}", 74, 8)
    x, y = int(w * 0.80), int(h * 0.30)
    for ch in label:
        put((x, y), ch, 96, 9)
        y += 118
    img.save(dst)


def render_versions(clips: list[pathlib.Path], song: pathlib.Path,
                    cover: pathlib.Path | None, work: pathlib.Path,
                    hi: pathlib.Path, upload: pathlib.Path, cover_sec: float,
                    aspect: tuple[int, int], duration: float) -> None:
    graph = video_graph([probe_duration(c) for c in clips], duration, aspect,
                        cover_sec, cover is not None)
    if not (work / 'lyrics.ass').is_file():
        raise ValueError('缺少已校验的lyrics.ass')
    inputs = []
    for clip in clips:
        inputs += ['-i', str(clip.resolve())]
    inputs += ['-i', str(song.resolve())]
    if cover is not None:
        inputs += ['-loop', '1', '-framerate', '30', '-i', str(cover.resolve())]
    command = ['ffmpeg', '-v', 'warning', '-y', '-filter_complex_threads', '1',
               *inputs, '-filter_complex', graph]
    for label, target, crf, bitrate in [('hi', hi, '20', '192k'), ('upload', upload, '24', '160k')]:
        command += ['-map', f'[{label}]', '-map', f'{len(clips)}:a:0',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', crf,
                    '-pix_fmt', 'yuv420p', '-threads', '2']
        if label == 'upload':
            command += ['-maxrate', '8M', '-bufsize', '16M']
        command += ['-c:a', 'aac', '-b:a', bitrate, '-ar', '48000', '-t', f'{duration:.9f}',
                    '-shortest', '-movflags', '+faststart', str(target.resolve())]
    sh(command, cwd=str(work.resolve()))


def publish_copy(title: str, singer: str, label: str, dst: pathlib.Path,
                 tags: str = "翻唱 车载音乐") -> None:
    tpl = next((c for c in (W / "templates/发布文案_模板.md",
                             W.parent / "sream-studio/templates/发布文案_模板.md")
                 if c.is_file()), W / "templates/发布文案_模板.md")
    text = tpl.read_text(encoding="utf-8") if tpl.is_file() else "# 发布文案\n\n## 标题\n\n## 正文\n\n## 话题\n"
    tag_str = " ".join(f"#{x.lstrip('#')}" for x in tags.split())
    text = (text.replace("{title}", title).replace("{singer}", singer)
                .replace("{label}", label).replace("{tags}", tag_str))
    dst.write_text(text, encoding="utf-8")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--song", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--singer", default="")
    ap.add_argument("--label", default="完整版")
    ap.add_argument("--lyrics", help="正式出片必填：正确歌词，一行一句")
    ap.add_argument('--timings', type=pathlib.Path, help='校对后的时间轴JSON，含start/end/text；不再调用Whisper')
    ap.add_argument("--clips", help="逗号分隔的素材视频；不给则从 Pexels 搜")
    ap.add_argument("--query", default="driving highway pov")
    ap.add_argument("--out", required=True)
    ap.add_argument("--aspect", default="1440x2560")
    ap.add_argument("--cover-seconds", type=float, default=3.0)
    ap.add_argument("--tags", default="翻唱 车载音乐",
                    help="两个可配话题标签（空格分隔，默认「翻唱 车载音乐」）")
    ap.add_argument("--whisper-model", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if not a.dry_run and (not a.lyrics or not pathlib.Path(a.lyrics).is_file()):
        ap.error('正式出片须提供存在的--lyrics文件，不使用未经核对的ASR唱词')

    try:
        w, h = (int(x) for x in a.aspect.lower().split('x'))
    except ValueError:
        ap.error('aspect格式须为宽x高，例如1440x2560')
    if w <= 0 or h <= 0 or w % 2 or h % 2 or not math.isfinite(a.cover_seconds) or a.cover_seconds < 0:
        ap.error('画幅须为正偶数，cover-seconds须为非负有限数')
    out = pathlib.Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"
    work.mkdir(exist_ok=True)

    song = pathlib.Path(a.song).resolve()
    need = probe_duration(song)
    print(f"  歌曲 {need:.1f}s ｜ 画幅 {w}x{h}")

    if a.dry_run:
        print('  [dry-run] 本地素材：', a.clips or '未指定；正式运行时搜索，不在预览中下载')
        return 0

    lyrics = [line.strip() for line in pathlib.Path(a.lyrics).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if not lyrics:
        raise ValueError('正确歌词文件为空')
    if a.timings:
        rows = json.loads(a.timings.read_text(encoding='utf-8-sig'))
        if isinstance(rows, dict):
            rows = rows.get('rows')
        if not isinstance(rows, list):
            raise ValueError('时间轴JSON须为数组或包含rows数组的对象')
    else:
        rows = transcribe(song, find_whisper_model(a.whisper_model))
    draft = work / '歌词时间轴_待核对.json'
    draft.write_text(json.dumps(dict(status='draft_requires_alignment_check', rows=rows), ensure_ascii=False, indent=2) + '\n')
    ass = work / "lyrics.ass"
    try:
        build_ass(rows, lyrics, ass, duration=need)
    except ValueError as exc:
        print(f'❌ {exc}\n时间轴草稿：{draft}；校对后传--timings重新运行，尚未合成视频。', file=sys.stderr)
        return 1

    clips = [pathlib.Path(p.strip()).resolve() for p in a.clips.split(',')] if a.clips else \
        search_clips(a.query, 30, need, work / 'clips')
    if not clips:
        raise ValueError('没有可用素材')

    cover = work / "cover.png"
    render_cover(a.title, a.singer, a.label, cover, (w, h))

    hi = out / f"{a.title}_驾车MV_高清.mp4"
    up = out / f"{a.title}_驾车MV_上传版.mp4"
    render_versions(clips, song, cover, work, hi, up, a.cover_seconds, (w, h), need)
    publish_copy(a.title, a.singer, a.label, out / "发布文案.md", a.tags)

    print(f"\n✅ 完成：{hi.name}（{probe_duration(hi):.1f}s）｜ {up.name}")
    return 0


if __name__ == "__main__":
    if not any(flag in sys.argv for flag in ('--help', '-h', '--dry-run')):
        _ensure_deps(need_whisper=not any(arg == '--timings' or arg.startswith('--timings=') for arg in sys.argv))
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f'❌ 出片失败：{exc}')
