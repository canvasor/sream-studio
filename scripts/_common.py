#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/ 共用：解析工具目录 / 解释器 / 环境，供各编排脚本调用。

设计约定：
  · 本仓库只放**编排层**，底层实现（lyrics_arena / ace_from_arena / …）在外部 tools 目录，
    由 TOOLS_DIR 指定。这样既复用已验证逻辑，又不把大段实现重复拷贝进仓库。
  · 密钥/服务地址一律读环境变量，本文件不硬编码任何真实值。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 工具目录：默认 ~/dsh-workspace/tools，可用 TOOLS_DIR 覆盖
_TOOLS_DEFAULT = Path.home() / "dsh-workspace" / "tools"


def tools_dir() -> Path:
    d = Path(os.environ.get("TOOLS_DIR", "") or _TOOLS_DEFAULT).expanduser()
    if not d.is_dir():
        sys.exit(f"❌ TOOLS_DIR 不存在：{d}\n   请 `export TOOLS_DIR=<你的 tools 目录>`")
    return d


def python() -> str:
    """解释器：默认 python3；分析类工具要带 numpy/librosa 的环境，可用 PY 覆盖。"""
    py = os.environ.get("PY", "").strip() or "python3"
    return py


def run(tool: str, *args: str, env: dict | None = None, check: bool = True) -> int:
    """以正确解释器跑一个底层工具，透传参数；返回退出码。"""
    cmd = [python(), str(tools_dir() / tool), *args]
    merged = {**os.environ, **(env or {})}
    r = subprocess.run(cmd, env=merged)
    if check and r.returncode != 0:
        sys.exit(f"❌ {tool} 退出码 {r.returncode}")
    return r.returncode


def require_env(*names: str) -> None:
    """要求某些环境变量已配置（如服务地址），缺了直接报清楚，不猜默认值。"""
    missing = [n for n in names if not os.environ.get(n, "").strip()]
    if missing:
        sys.exit("❌ 缺少环境变量：" + ", ".join(missing) + "\n"
                 "   请先 export 后再跑（参考 templates/env.example，⛔ 别把真实值提交进仓库）")
