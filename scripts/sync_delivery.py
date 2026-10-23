#!/usr/bin/env python3
"""Copy a delivery batch to an explicit destination and verify every file with SHA256."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

RECEIPT = '共享同步校验.json'
STATE = '.sync-state.json'
VERSION = 'sync-delivery-v1'


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def inventory(root):
    """Do not follow links out of the batch or copy caches and old receipts."""
    def fail_walk(error):
        raise error

    rows = []
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=fail_walk):
        dirs[:] = sorted(d for d in dirs if d not in ('__pycache__', '.git'))
        for name in dirs + names:
            if (Path(directory) / name).is_symlink():
                raise ValueError(f'批次中有符号链接，请先整理成独立文件：{name}')
        for name in sorted(names):
            path = Path(directory) / name
            if name in (RECEIPT, STATE) or path.suffix in ('.pyc', '.pyo'):
                continue
            if not path.is_file():
                raise ValueError(f'不是普通文件：{path}')
            rows.append(dict(file=path.relative_to(root).as_posix(),
                             bytes=path.stat().st_size, sha256=digest(path)))
    return sorted(rows, key=lambda row: row['file'])


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def verify(source_rows, target):
    receipt = json.loads((target / RECEIPT).read_text(encoding='utf-8'))
    if (not isinstance(receipt, dict) or receipt.get('status') != 'copied_and_sha256_verified'
            or receipt.get('sha256') != source_rows):
        raise ValueError('目标校验记录与当前源批次不一致；改稿请使用新批次，不覆盖交付')
    if inventory(target) != source_rows:
        raise ValueError('目标文件缺失、增加或内容改变；停止，不覆盖已有交付')


def entry(target, unc_root):
    print(f'目标文件校验通过：{target}', flush=True)
    if unc_root:
        print('Windows 批次路径：' + unc_root.rstrip('\\/') + '\\' + target.name, flush=True)
    print('Windows 可见性需通过客户端实际访问或用户确认；本机文件检查不代替此项。', flush=True)


def synchronize(source, parent, *, dry_run=False, check_only=False, resume=False, unc_root=''):
    source = source.expanduser().resolve(strict=True)
    parent = parent.expanduser().resolve(strict=True)
    if not source.is_dir() or not parent.is_dir():
        raise ValueError('source 与 dest-parent 都必须是已有目录')
    target = parent / source.name
    if target == source or source in target.parents or target in source.parents:
        raise ValueError('源与目标必须分离，不能相同或互相包含')
    rows = inventory(source)
    if not rows:
        raise ValueError('源批次为空')
    print(f'文件 {len(rows)} 个，共 {sum(row["bytes"] for row in rows)} 字节；目标 {target}', flush=True)
    if dry_run:
        print('仅预览：未写目标、未生成校验记录；已有目标仍需 --check-only 核验。')
        return target
    if target.is_symlink():
        raise ValueError('目标是符号链接，停止')
    if target.exists():
        verify(rows, target)
        entry(target, unc_root)
        return target
    if check_only:
        raise ValueError('目标批次不存在，尚未同步')

    stage = parent / f'.{source.name}.syncing'
    plan = dict(version=VERSION, sha256=rows)
    if stage.is_symlink():
        raise ValueError('暂存目录是符号链接，停止')
    if stage.exists():
        if not resume:
            raise ValueError('存在未完成暂存目录；输入未变化时可加 --resume 续跑')
        if json.loads((stage / STATE).read_text(encoding='utf-8')) != plan:
            raise ValueError('输入已变化或暂存来源不符，不能续用；请改用新批次')
        # Reject links even in a partially copied directory before writing to it.
        inventory(stage)
    else:
        stage.mkdir()
        save(stage / STATE, plan)

    for index, row in enumerate(rows, 1):
        original, copied = source / row['file'], stage / row['file']
        copied.parent.mkdir(parents=True, exist_ok=True)
        if not copied.is_file() or digest(copied) != row['sha256']:
            shutil.copyfile(original, copied)
        if copied.stat().st_size != row['bytes'] or digest(copied) != row['sha256']:
            raise ValueError(f'复制校验失败：{row["file"]}；保留暂存，停止本次执行')
        if index % 15 == 0 or index == len(rows):
            print(f'已复制并校验 {index}/{len(rows)}', flush=True)
    if inventory(source) != rows:
        raise ValueError('复制期间源文件改变；保留暂存，不能宣布完成')
    receipt = dict(version=VERSION, status='copied_and_sha256_verified', files=len(rows),
                   completed_at=datetime.datetime.now().astimezone().isoformat(),
                   windows_visibility='not_confirmed', sha256=rows)
    save(stage / RECEIPT, receipt)
    verify(rows, stage)
    if target.exists() or target.is_symlink():
        raise ValueError('复制期间目标已出现；保留暂存，不覆盖')
    stage.rename(target)
    entry(target, unc_root)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='已验收的工作区批次目录')
    parser.add_argument('--dest-parent', required=True, type=Path, help='共享区已有父目录；不猜服务地址')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--dry-run', action='store_true', help='预览文件数量与目标，不写入')
    modes.add_argument('--check-only', action='store_true', help='只核对已同步目标与当前来源')
    modes.add_argument('--resume', action='store_true', help='输入未变化时续用本脚本的暂存目录')
    parser.add_argument('--unc-root', default='', help='可选：dest-parent 对应的 UNC 路径，仅用于打印入口')
    args = parser.parse_args(argv)
    try:
        synchronize(args.source, args.dest_parent, dry_run=args.dry_run,
                    check_only=args.check_only, resume=args.resume, unc_root=args.unc_root)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'同步未完成：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
