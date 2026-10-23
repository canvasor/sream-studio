#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阿里 Wan 视频接口客户端（虚拟歌手 MV 用）。

覆盖两个模型：
  · `wan2.2-s2v`         单图 + 人声 → 演唱/口型视频（≤20s 音频）
  · `wan3.0-video-prime` 文生视频 / 图生视频（异步任务）

配置读取 `~/.dsh/secrets/asr_models.env`（**密钥不入库**）：
    ASR_MODEL_API_KEY      阿里 MaaS 的 sk- key
    ASR_MODEL_BASE_URL     https://<host>/api/v1
    VISION_MODEL_S2V_NAME  wan2.2-s2v
    VISION_MODEL_VIDEO_NAME wan3.0-video-prime

命令：
    # 图片能否用于 s2v（同步，先跑这个再花钱）
    python3 scripts/wan_client.py face-detect --image 图.jpg

    # 演唱视频：图 + 人声
    python3 scripts/wan_client.py s2v --image 图.jpg --audio 人声.wav --out out.mp4

    # 环境/叙事视频：文生 or 图生
    python3 scripts/wan_client.py video --prompt "高原草原，镜头缓慢推进" \\
        --image 参考图.jpg --duration 5 --resolution 1080P --ratio 16:9 --out out.mp4

    # 只查任务 / 下载
    python3 scripts/wan_client.py poll --task-id <id>
    python3 scripts/wan_client.py download --task-id <id> --out out.mp4

画幅和分辨率以本次任务及模型能力为准；video 命令的历史默认值为 16:9 / 1080P。
先使用 --dry-run 预览，实际生成前明确设置 --resolution。
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import pathlib
import sys
import time
import tempfile
import urllib.error
import urllib.request

CONF = pathlib.Path.home() / ".dsh/secrets/asr_models.env"
TIMEOUT_SUBMIT = 120
POLL_INTERVAL = 10
POLL_MAX = 180          # 最多等 30 分钟


def load_conf(path: pathlib.Path = CONF) -> dict:
    kv = {}
    lines = path.read_text(encoding='utf-8').splitlines() if path.is_file() else []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip().strip('"').strip("'")
    for key in ('ASR_MODEL_API_KEY', 'ASR_MODEL_BASE_URL', 'VISION_MODEL_S2V_NAME', 'VISION_MODEL_VIDEO_NAME'):
        if os.environ.get(key):
            kv[key] = os.environ[key]
    for need in ("ASR_MODEL_API_KEY", "ASR_MODEL_BASE_URL"):
        if not kv.get(need):
            raise SystemExit(f"❌ 配置缺 {need}")
    kv["BASE"] = kv["ASR_MODEL_BASE_URL"].rstrip("/")
    return kv


def _post(conf, path: str, body: dict, async_hdr: bool = True) -> dict:
    headers = {"Authorization": f"Bearer {conf['ASR_MODEL_API_KEY']}",
               "Content-Type": "application/json",
               # 让服务端解析 oss:// 临时 URL（官方要求）
               "X-DashScope-OssResourceResolve": "enable"}
    if async_hdr:
        headers["X-Dashscope-Async"] = "enable"
    req = urllib.request.Request(f"{conf['BASE']}{path}",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SUBMIT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"❌ HTTP {e.code} @ {path}: "
                         f"{e.read().decode('utf-8', 'ignore')[:400]}")


def _get(conf, path: str) -> dict:
    req = urllib.request.Request(f"{conf['BASE']}{path}",
                                 headers={"Authorization": f"Bearer {conf['ASR_MODEL_API_KEY']}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"❌ HTTP {e.code} @ {path}: "
                         f"{e.read().decode('utf-8', 'ignore')[:300]}")


# 阿里接口按 MIME 白名单判类型，`audio/x-wav` 会被拒 → 显式映射
MIME_MAP = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".mp4": "video/mp4", ".mov": "video/quicktime",
}


def to_data_uri(path: pathlib.Path) -> str:
    """本地文件 → data URI（图片/音频都能用；MIME 按白名单显式映射）。"""
    mime = MIME_MAP.get(path.suffix.lower()) \
        or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def media_arg(value: str) -> str:
    """'图.jpg' 或 'https://…' → 接口用的 url 字段。"""
    if value.startswith(("http://", "https://", "data:")):
        return value
    p = pathlib.Path(value)
    if not p.is_file():
        raise SystemExit(f"❌ 文件不存在：{value}")
    return to_data_uri(p)


def submit(conf, path: str, body: dict) -> str:
    r = _post(conf, path, body)
    tid = (r.get("output") or {}).get("task_id") or r.get("task_id")
    if not tid:
        raise SystemExit(f"❌ 没拿到 task_id：{json.dumps(r, ensure_ascii=False)[:400]}")
    return tid


def wait(conf, task_id: str, quiet: bool = False) -> dict:
    for i in range(POLL_MAX):
        s = _get(conf, f"/tasks/{task_id}")
        st = (s.get("output") or {}).get("task_status") or s.get("task_status")
        if not quiet:
            print(f"  [{i*POLL_INTERVAL:>4}s] {st}", flush=True)
        if st in ("SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"):
            return s
        time.sleep(POLL_INTERVAL)
    raise SystemExit(f'❌ 轮询超时；任务 {task_id} 可能仍在运行，请用 poll / download 查询，不要重复提交')


def video_url_of(task: dict) -> str:
    """兼容三种返回形状：video_url / results.video_url(dict) / results[0].url(list)。"""
    out = task.get("output") or {}
    for k in ("video_url", "url", "video"):
        if out.get(k):
            return out[k]
    res = out.get("results")
    if isinstance(res, dict):
        for k in ("video_url", "url", "video"):
            if res.get(k):
                return res[k]
    if isinstance(res, list) and res:
        for k in ("video_url", "url", "video"):
            if isinstance(res[0], dict) and res[0].get(k):
                return res[0][k]
    return ""


def download(url: str, out: pathlib.Path) -> None:
    if out.exists() or out.is_symlink():
        raise FileExistsError(f'成片已存在，请选择新路径：{out}')
    out.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "wan-client/1.0"})
    temp = None
    try:
        with urllib.request.urlopen(req, timeout=600) as r, tempfile.NamedTemporaryFile(dir=out.parent, prefix='.wan-', delete=False) as f:
            temp = pathlib.Path(f.name)
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        if not temp.stat().st_size:
            raise OSError('下载结果为空')
        # Publish without replacing a destination created during download.
        os.link(temp, out)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    print(f"  ✅ {out}（{out.stat().st_size/1e6:.1f}MB）")


# ── 临时文件上传（百炼官方：本地文件 → oss:// URL，48 小时有效）──────────

UPLOAD_BASE = "https://dashscope.aliyuncs.com/api/v1"


def get_upload_policy(conf, model: str) -> dict:
    """取上传凭证。必须在 model 里写明文件将被哪个模型使用。"""
    import urllib.parse
    q = urllib.parse.urlencode({"action": "getPolicy", "model": model})
    req = urllib.request.Request(
        f"{UPLOAD_BASE}/uploads?{q}",
        headers={"Authorization": f"Bearer {conf['ASR_MODEL_API_KEY']}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"❌ getPolicy HTTP {e.code}: "
                         f"{e.read().decode('utf-8','ignore')[:300]}")
    if not d.get("data"):
        raise SystemExit(f"❌ getPolicy 无 data：{str(d)[:300]}")
    return d["data"]


def upload_temp(conf, path: pathlib.Path, model: str) -> str:
    """本地文件 → oss:// 临时 URL（48h，同账号同模型可用）。"""
    import uuid
    policy = get_upload_policy(conf, model)
    key = f"{policy['upload_dir']}/{uuid.uuid4().hex}_{path.name}"
    boundary = "----wanclient" + uuid.uuid4().hex
    fields = {
        "OSSAccessKeyId": policy["oss_access_key_id"],
        "Signature": policy["signature"],
        "policy": policy["policy"],
        "x-oss-object-acl": policy["x_oss_object_acl"],
        "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"],
        "key": key,
        "success_action_status": "200",
    }
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                 f"{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
             ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        policy["upload_host"], data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            if r.status != 200:
                raise SystemExit(f"❌ 上传失败 HTTP {r.status}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"❌ 上传失败 HTTP {e.code}: "
                         f"{e.read().decode('utf-8','ignore')[:300]}")
    return f"oss://{key}"


def media_for_model(conf, value: str, model: str) -> str:
    """本地路径 → 自动走临时上传；http(s)/oss:// 原样返回。"""
    if value.startswith(("http://", "https://", "oss://")):
        return value
    p = pathlib.Path(value)
    if not p.is_file():
        raise SystemExit(f"❌ 文件不存在：{value}")
    print(f"  ⬆ 上传 {p.name} → 临时存储 …", flush=True)
    url = upload_temp(conf, p, model)
    print(f"  ✅ {url}", flush=True)
    return url


# ── 两个模型 ────────────────────────────────────────────────────────────

def face_detect(conf, image: str) -> dict:
    """s2v 前置：图片是否适合做口型（同步接口）。"""
    return _post(conf, "/services/aigc/image2video/face-detect",
                 {"model": conf.get("VISION_MODEL_S2V_NAME", "wan2.2-s2v"),
                  "input": {"image_url": media_for_model(conf, image, conf.get("VISION_MODEL_S2V_NAME", "wan2.2-s2v"))}}, async_hdr=False)


def submit_s2v(conf, image: str, audio: str, prompt: str = "",
               resolution: str = "") -> str:
    """图 + 人声 → 演唱视频任务。音频建议 ≤20 秒；resolution 可给 480P/720P。"""
    model = conf.get("VISION_MODEL_S2V_NAME", "wan2.2-s2v")
    body = {"model": model,
            "input": {"image_url": media_for_model(conf, image, model),
                      "audio_url": media_for_model(conf, audio, model)}}
    if prompt:
        body["input"]["prompt"] = prompt
    if resolution:
        body["parameters"] = {"resolution": resolution}
    return submit(conf, "/services/aigc/image2video/video-synthesis", body)


def submit_video(conf, prompt: str = "", image: str = "", duration: int = 5,
                 resolution: str = "1080P", ratio: str = "16:9") -> str:
    """文生/图生视频任务（image 给了就是图生视频）。"""
    model = conf.get("VISION_MODEL_VIDEO_NAME", "wan3.0-video-prime")
    inp = {}
    if prompt:
        inp["prompt"] = prompt
    if image:
        # ⭐ wan3.0 的图生视频必须走 media 数组 + type=first_frame，
        #    传 img_url 会被忽略并退化成纯文生视频（人物会被重新生成）
        inp["media"] = [{"type": "first_frame",
                         "url": media_for_model(conf, image, model)}]
        if ratio != "adaptive":
            ratio = "adaptive"      # 官方建议首帧模式用 adaptive
    body = {"model": model, "input": inp,
            "parameters": {"resolution": resolution, "ratio": ratio,
                           "duration": duration}}
    return submit(conf, "/services/aigc/video-generation/video-synthesis", body)


# ── CLI ────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("face-detect", help="检查图片能否用于 s2v")
    p.add_argument("--image", required=True)
    p.add_argument('--dry-run', action='store_true')

    p = sub.add_parser("s2v", help="图 + 人声 → 演唱视频")
    p.add_argument("--image", required=True)
    p.add_argument("--audio", required=True)
    p.add_argument("--prompt", default="")
    p.add_argument("--out", required=True)
    p.add_argument("--resolution", default="", help="480P/720P（空=服务端默认）")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument('--dry-run', action='store_true')

    p = sub.add_parser("video", help="文生/图生视频")
    p.add_argument("--prompt", default="")
    p.add_argument("--image", default="")
    p.add_argument("--duration", type=int, default=5)
    p.add_argument("--resolution", default="1080P")
    p.add_argument("--ratio", default="16:9")
    p.add_argument("--out", required=True)
    p.add_argument("--no-wait", action="store_true")
    p.add_argument('--dry-run', action='store_true')

    p = sub.add_parser("poll", help="查任务状态")
    p.add_argument("--task-id", required=True)

    p = sub.add_parser("download", help="按 task_id 下载成片")
    p.add_argument("--task-id", required=True)
    p.add_argument("--out", required=True)

    a = ap.parse_args(argv)
    if a.cmd in {'s2v', 'video', 'download'} and (pathlib.Path(a.out).exists() or pathlib.Path(a.out).is_symlink()):
        ap.error('输出已存在，请选择新的 --out 路径')
    if getattr(a, 'dry_run', False):
        # Deliberately avoid config loading, uploads, and all API requests.
        print(json.dumps(vars(a), ensure_ascii=False, indent=2))
        print('预览：未读取凭据、未上传或调用 API；本地媒体将在实际执行时临时上传。')
        return 0
    conf = load_conf()

    if a.cmd == "face-detect":
        print(json.dumps(face_detect(conf, a.image), ensure_ascii=False, indent=1)[:800])
        return 0

    if a.cmd == "poll":
        print(json.dumps(_get(conf, f"/tasks/{a.task_id}"), ensure_ascii=False, indent=1)[:1200])
        return 0

    if a.cmd == "download":
        s = _get(conf, f"/tasks/{a.task_id}")
        url = video_url_of(s)
        if not url:
            raise SystemExit("❌ 任务里没有成片 URL（可能还没成功）")
        download(url, pathlib.Path(a.out))
        return 0

    if a.cmd == "s2v":
        tid = submit_s2v(conf, a.image, a.audio, a.prompt, a.resolution)
    else:
        tid = submit_video(conf, a.prompt, a.image, a.duration, a.resolution, a.ratio)
    print(f"  task_id: {tid}")
    if a.no_wait:
        print("  （未等待，稍后用 poll / download 取回）")
        return 0
    task = wait(conf, tid)
    url = video_url_of(task)
    if not url:
        print(json.dumps(task, ensure_ascii=False)[:600])
        raise SystemExit("❌ 任务结束但没有成片 URL")
    download(url, pathlib.Path(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
