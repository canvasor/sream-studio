#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⑤ 生成平台用的纯文本无格式歌词（Suno 那套和平台这套是两份，分开生成）。

用法：
    python scripts/make_lyrics.py --song <歌名>
    python scripts/make_lyrics.py --check      # 只体检不写
"""
from __future__ import annotations

import sys

from _common import run


def main(argv: list[str]) -> int:
    if any(arg == '--source' or arg.startswith('--source=') for arg in argv):
        from make_suno_config import main as export_suno
        return export_suno(argv)
    return run("make_clean_lyrics.py", *argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
