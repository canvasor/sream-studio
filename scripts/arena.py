#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""② 擂台编排：一份命题 → 多模型竞稿 → 六维文本评审 → top3。

用法：
    python scripts/arena.py gen --models m1,m2 --workers 4
    python scripts/arena.py score          # 规则诊断与六维文本评审分开
    python scripts/arena.py report         # 完整评审的文本初筛
    python scripts/arena.py top3           # 导出3篇文本候选，之后仍需试听

环境变量（见 templates/env.example，密钥不入库）：
    ARENA_TAG        擂台名（跑/评分/报告都走 runs_<TAG>/，互不覆盖）
    ARENA_PROMPT     提示词文件（默认 prompt.md）
    ARENA_BRIEFS     命题表 json（默认 briefs.json）
    ARENA_CHANNELS   通道过滤（如 ark,custom）
    ARENA_JUDGES     评委模型（如 doubao-seed-2.1-pro,gpt-6-sol）
"""
from __future__ import annotations

import sys

from _common import run

_STAGE_MAP = {
    "gen": ("lyrics_arena.py", "gen"),
    "score": ("lyrics_arena_score.py", "judge"),
    "judge": ("lyrics_arena_score.py", "judge"),
    "report": ("lyrics_arena_score.py", "report"),
    "top3": ("lyrics_arena_top5.py", ""),
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in _STAGE_MAP:
        print(__doc__)
        return 2 if argv else 0
    stage, rest = argv[0], argv[1:]
    tool, fixed = _STAGE_MAP[stage]
    args = ([fixed] if fixed else []) + (["--count", "3"] if stage == "top3" else []) + rest
    return run(tool, *args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
