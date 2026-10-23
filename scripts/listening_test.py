#!/usr/bin/env python3
"""Prepare anonymous, normalized listening clips and record real pairwise choices."""
from __future__ import annotations
import argparse
import json
import math
import random
import subprocess
import sys
import tempfile
from pathlib import Path


def normalization_pass(source, start, duration, destination):
    base = ['ffmpeg','-v','info','-ss',str(start),'-t',str(duration),'-i',str(source),'-vn']
    first = subprocess.run(base+['-af','loudnorm=I=-18:TP=-2:LRA=11:print_format=json',
                                 '-f','null','-'],capture_output=True,text=True,check=True)
    left, right = first.stderr.rfind('{'), first.stderr.rfind('}')
    stats = json.loads(first.stderr[left:right+1])
    for field in ('input_i','input_tp','input_lra','input_thresh','target_offset'):
        if not math.isfinite(float(stats[field])):
            raise ValueError('片段静音或无法测量响度')
    effect = (f"loudnorm=I=-18:TP=-2:LRA=11:measured_I={stats['input_i']}:"
              f"measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}:"
              f"measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:"
              'linear=true:print_format=json')
    second = subprocess.run(base+['-af',effect,'-ar','44100','-ac','2','-c:a','pcm_s16le',str(destination)],
                            capture_output=True,text=True,check=True)
    left, right = second.stderr.rfind('{'), second.stderr.rfind('}')
    output = json.loads(second.stderr[left:right+1])
    return dict(input_lufs=float(stats['input_i']), output_lufs=float(output['output_i']))


def prepare(manifest, out, seed):
    if out.exists():
        raise ValueError('试听目录已存在，请使用新版本目录')
    key_path = out.parent/f'{out.name}_private_key.json'
    if key_path.exists():
        raise ValueError('答案表已存在，请使用新版本目录')
    config = json.loads(manifest.read_text())
    clips = config['clips']
    if not 2 <= len(clips) <= 26:
        raise ValueError('每组需要2–26个同一首歌的候选')
    durations = []
    for item in clips:
        start, end = float(item['start']), float(item['end'])
        if not all(math.isfinite(v) for v in (start,end)) or start < 0 or end <= start:
            raise ValueError('片段时间不合法')
        durations.append(end-start)
        source = Path(item['file'])
        item['resolved_file'] = source.resolve() if source.is_absolute() else (manifest.parent/source).resolve()
        probe = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                                 '-of','csv=p=0',str(item['resolved_file'])],capture_output=True,text=True,check=True)
        if end > float(probe.stdout.strip())+.03:
            raise ValueError(f"片段超出文件时长：{source.name}")
    if max(durations)-min(durations) > .05:
        raise ValueError('同组试听片段长度应一致；起点可按各版实际段落调整')
    random.Random(seed).shuffle(clips)
    out.parent.mkdir(parents=True,exist_ok=True)
    key = {}
    with tempfile.TemporaryDirectory(prefix='.listening-',dir=out.parent) as temp:
        stage = Path(temp)/'public'
        stage.mkdir()
        labels = []
        for index,item in enumerate(clips):
            label = chr(ord('A')+index)
            labels.append(label)
            stats = normalization_pass(item['resolved_file'],item['start'],item['end']-item['start'],stage/f'{label}.wav')
            key[label] = {k:str(v) if isinstance(v,Path) else v for k,v in item.items()}
            key[label]['normalization'] = stats
        rows = '\n'.join(f'<p>{label}</p><audio controls preload="none" src="{label}.wav"></audio>' for label in labels)
        (stage/'试听.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>候选试听</title>'
            '<body style="font:18px sans-serif;max-width:700px;margin:40px auto;padding:16px">'
            '<h1>候选试听</h1><p>先听，再记录更愿意重听的一条及具体理由。听后隔一段时间，写下记住的一句。</p>'
            +rows+'</body></html>')
        (stage/'ratings.json').write_text(json.dumps(dict(version='listening-v1',labels=labels,comparisons=[]),indent=2)+'\n')
        stage.rename(out)
    key_path.write_text(json.dumps(dict(version='listening-v1',seed=seed,mapping=key),ensure_ascii=False,indent=2)+'\n')
    print(f'试听：{out/"试听.html"}\n映射与技术数据：{key_path}')


def record(path, pair, choice, reason, remembered):
    data = json.loads(path.read_text())
    labels = pair.split(',')
    if len(labels) != 2 or len(set(labels)) != 2 or not set(labels) <= set(data['labels']):
        raise ValueError('pair须为本组两个不同编号，如A,B')
    if choice not in labels+['tie'] or not reason.strip():
        raise ValueError('choice须为其中一个编号或tie，并填写具体理由')
    data['comparisons'].append(dict(pair=labels,choice=choice,reason=reason,remembered_lyric=remembered))
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def summarize(path, key_path, out):
    data, key = json.loads(path.read_text()),json.loads(key_path.read_text())
    if not data['comparisons']:
        raise ValueError('还没有真实试听选择，不能生成胜负结论')
    if set(data['labels']) != set(key['mapping']):
        raise ValueError('评分与映射不属于同一组')
    counts = {label:0 for label in data['labels']}
    for row in data['comparisons']:
        if row['choice'] != 'tie':
            counts[row['choice']] += 1
    out.write_text(json.dumps(dict(version='listening-v1',wins=counts,comparisons=data['comparisons'],
        mapping=key['mapping'],note='个人试听偏好；对比次数不同或样本很少时不能推导模型优劣。'),ensure_ascii=False,indent=2)+'\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='stage',required=True)
    p=sub.add_parser('prepare');p.add_argument('--manifest',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--seed',type=int,default=20261017)
    p=sub.add_parser('record');p.add_argument('--ratings',required=True,type=Path);p.add_argument('--pair',required=True);p.add_argument('--choice',required=True);p.add_argument('--reason',required=True);p.add_argument('--remembered',default='')
    p=sub.add_parser('summarize');p.add_argument('--ratings',required=True,type=Path);p.add_argument('--key',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    a=ap.parse_args(argv)
    try:
        if a.stage=='prepare':prepare(a.manifest,a.out,a.seed)
        elif a.stage=='record':record(a.ratings,a.pair,a.choice,a.reason,a.remembered)
        else:summarize(a.ratings,a.key,a.out)
        return 0
    except (ValueError,OSError,KeyError,subprocess.CalledProcessError) as exc:
        print(f'试听工具失败：{exc}',file=sys.stderr);return 1


if __name__=='__main__':
    sys.exit(main())
