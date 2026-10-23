#!/usr/bin/env python3
"""Validate clip-relative choreography and render a dual-clock Markdown table."""
import argparse
import json
import math
from pathlib import Path


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('时间必须为有限数字秒')
    return value


def interval(row, duration):
    start, end = number(row['start']), number(row['end'])
    if not 0 <= start < end <= duration:
        raise ValueError('区间超出片段或时长非正')
    return start, end


def coverage(rows, duration):
    if not rows:
        raise ValueError('覆盖表不能为空')
    cursor = 0
    for row in rows:
        start, end = interval(row, duration)
        if abs(start - cursor) > 1e-6:
            raise ValueError('覆盖表有空隙、重叠或乱序')
        cursor = end
    if abs(cursor - duration) > 1e-6:
        raise ValueError('覆盖表未到片段结尾')


def validate(data, max_seconds=None):
    duration = number(data['duration'])
    if duration <= 0 or number(data['source_start']) < 0:
        raise ValueError('片段时长必须为正，源起点不能为负')
    cues = {}
    previous = -1
    for cue in data['cues']:
        start, _ = interval(cue, duration)
        if start < previous or not cue['id'] or cue['id'] in cues:
            raise ValueError('唱句未排序或编号重复/为空')
        if cue['evidence'] not in {'asr_estimate', 'forced_alignment', 'manual_listening', 'unverified'}:
            raise ValueError('未知时间证据类型')
        if not isinstance(cue['text'], str) or not cue['text'].strip():
            raise ValueError('唱词不能为空')
        previous = start
        cues[cue['id']] = cue
    for key in ('beats', 'parts'):
        coverage(data[key], duration)
    referenced = set()
    for beat in data['beats']:
        for key in ('shot', 'action', 'camera'):
            if not isinstance(beat[key], str) or not beat[key].strip():
                raise ValueError('节拍缺少镜头、动作或运镜')
        for cue_id in beat['cue_ids']:
            cue = cues.get(cue_id)
            if cue is None:
                raise ValueError('节拍引用不存在的唱句')
            if max(cue['start'], beat['start']) >= min(cue['end'], beat['end']):
                raise ValueError('节拍与引用唱句时间不相交')
            referenced.add(cue_id)
    if referenced != set(cues):
        raise ValueError('有唱句未分配表演节拍')
    names = [part['name'] for part in data['parts']]
    if any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != len(names):
        raise ValueError('分段名称为空或重复')
    if max_seconds is not None:
        if number(max_seconds) <= 0:
            raise ValueError('单段时长上限必须为正')
        for part in data['parts']:
            if part['end'] - part['start'] > max_seconds + 1e-6:
                raise ValueError(f"分段 {part['name']} 超过单段上限 {max_seconds:g}s")
    return data


def clock(seconds):
    millis = round(seconds * 1000)
    minutes, rest = divmod(millis, 60000)
    return f'{minutes:02d}:{rest / 1000:06.3f}'


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def table(data):
    validate(data)
    cues = {cue['id']: cue for cue in data['cues']}
    lines = ['# 分镜双时间轴', '', '时间为导演区间；唱字、换气与延音以输入音频为准。', '',
             '| 片段时间 | 源曲时间 | 镜头 | 唱词与时间证据 | 表演 | 运镜 |',
             '|---|---|---|---|---|---|']
    for beat in data['beats']:
        start, end = beat['start'], beat['end']
        text = '；'.join(cues[key]['text'] + ' (' + cues[key]['evidence'] + ')' for key in beat['cue_ids'])
        row = [f'{clock(start)}–{clock(end)}',
               f"{clock(start + data['source_start'])}–{clock(end + data['source_start'])}",
               beat['shot'], text or '无指定唱句，沿音频延续', beat['action'], beat['camera']]
        lines.append('| ' + ' | '.join(map(cell, row)) + ' |')
    lines += ['', '## 备用分段', '', '| 段 | 片段区间 | 源曲区间 | 时长 |', '|---|---|---|---|']
    for part in data['parts']:
        start, end = part['start'], part['end']
        lines.append(f"| {cell(part['name'])} | {clock(start)}–{clock(end)} | "
                     f"{clock(start + data['source_start'])}–{clock(end + data['source_start'])} | {end-start:g}s |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('timeline', type=Path)
    parser.add_argument('--table', type=Path)
    parser.add_argument('--max-seconds', type=float, help='核验每段不超过此秒数，采用视频与音频限制的较小值')
    args = parser.parse_args()
    try:
        data = validate(json.loads(args.timeline.read_text(encoding='utf-8')), args.max_seconds)
        if args.table:
            args.table.write_text(table(data), encoding='utf-8')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'时间表无效：{exc}\n')
    print(f"通过：{data['duration']:g}s，{len(data['beats'])}个表演节拍，{len(data['parts'])}段；不代表口型验收通过。")


if __name__ == '__main__':
    main()
