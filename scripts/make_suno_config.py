#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出任意Markdown定稿的Suno输入与平台纯文本歌词。

    python scripts/make_suno_config.py --source song.md --out package-v1
    python scripts/make_suno_config.py --source song.md --out package-v1 --check

历史固定歌名参数卡兼容 --song <歌名> 或 --all。
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

from _common import run
from suno_options import prepare_upload, update_package


def main(argv: list[str]) -> int:
    if any(arg == '--source' or arg.startswith('--source=') for arg in argv):
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('--ui-profile', help='任务级界面参数覆盖JSON；values中只写需要改的控件')
        parser.add_argument('--audio', type=Path, help='绑定本候选上传源音频，并导出类型与描述')
        parser.add_argument('--audio-type', help='上传内容类型；完整ACE歌曲默认Full Song')
        parser.add_argument('--audio-description-file', type=Path, help='UTF-8描述文案覆盖文件')
        parser.add_argument('--audio-operation', choices=['Cover', 'Extend', 'Edit'], help='上传后建议操作，默认Cover')
        options, remaining = parser.parse_known_args(argv)
        if '--help' in remaining:
            result = run('song_package.py', *remaining, check=False)
            print('附加选项：--ui-profile、--audio、--audio-type、--audio-description-file、--audio-operation；音频配置与More Options一起导出')
            return result
        try:
            if not options.audio and any((options.audio_type, options.audio_description_file, options.audio_operation)):
                raise ValueError('音频类型、描述与操作覆盖须同时指定--audio')
            upload = prepare_upload(
                options.audio, audio_type=options.audio_type,
                description=options.audio_description_file.read_text(encoding='utf-8-sig') if options.audio_description_file else None,
                operation=options.audio_operation) if options.audio else None
        except (OSError, ValueError) as exc:
            print(f'上传配置失败：{exc}', file=sys.stderr)
            return 1
        result = run('song_package.py', *remaining, check=False)
        if result:
            return result
        package = argparse.ArgumentParser(add_help=False)
        package.add_argument('--out', required=True)
        package.add_argument('--check', action='store_true')
        parsed, _ = package.parse_known_args(remaining)
        try:
            update_package(parsed.out, check=parsed.check, profile_path=options.ui_profile, upload=upload)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'界面参数卡失败：{exc}', file=sys.stderr)
            return 1
        print('界面参数卡检查通过' if parsed.check else '已导出More Options与本首参数卡（有音频时含上传类型及描述）')
        return 0
    if '--help' in argv:
        result = run('song_package.py', *argv, check=False)
        print('附加选项（配合--source）：--ui-profile、--audio、--audio-type、--audio-description-file、--audio-operation；音频配置与More Options一起导出')
        return result
    # Legacy fixed-song cards remain available with their actual positional CLI.
    if "--all" in argv:
        argv = [x for x in argv if x != "--all"]
    if "--song" in argv:
        argv = [x for x in argv if x != "--song"]
    return run("make_suno_cards.py", *argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
