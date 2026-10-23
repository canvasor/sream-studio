#!/usr/bin/env python3
"""Generate top3 × three directions; verify the exact candidate manifest before delivery."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
from _common import require_env, run
from make_suno_config import main as export_suno
from suno_options import prepare


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_candidates(out, source, songs):
    manifest = json.loads((out/'candidates.json').read_text())
    if manifest.get('version') != 'ace-candidates-v2':
        raise ValueError('候选清单版本不符')
    expected = {(song, c) for song in songs for c in (1,2,3)}
    jobs = manifest['jobs']
    actual = {(j['stem'], j['candidate']) for j in jobs}
    if actual != expected or len(jobs) != 9:
        raise ValueError('候选不是指定top3各三条，不能用目录文件总数代替')
    files = []
    for job in jobs:
        if job.get('status') not in ('complete','cached'):
            raise ValueError(f"候选未成功：{job['file']}")
        expected_file = f"{job['stem']}_ace_c{job['candidate']}.wav"
        if job['file'] != expected_file:
            raise ValueError('候选文件名与映射不符')
        file = out/expected_file
        meta = json.loads(file.with_suffix('.json').read_text())
        if (meta.get('input_hash') != job['input_hash'] or meta.get('audio_sha256') != digest(file)
                or job['source_hash'] != digest(source/f"{job['stem']}.md")):
            raise ValueError(f'{file.name}: 来源或音频指纹不一致')
        files.append(file)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dir', required=True)
    ap.add_argument('--songs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--dur', type=int, default=215)
    ap.add_argument('--tempo-hint', default='')
    ap.add_argument('--guidance', type=float, default=1.)
    ap.add_argument('--service-version', default='unspecified')
    ap.add_argument('--variants')
    ap.add_argument('--ui-profile', help='自动生成Suno参数卡时使用的More Options覆盖JSON')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--check-only', action='store_true')
    a = ap.parse_args(argv)
    songs = [s.strip() for s in a.songs.split(',') if s.strip()]
    if len(songs) != 3 or len(set(songs)) != 3:
        ap.error('需要三个不同的歌词stem')
    try:
        # Reject invalid UI overrides before spending time on live generation.
        prepare({'styles': '', 'lyrics': '', 'exclude': ''}, a.ui_profile)
        if not a.check_only:
            args = ['--dir', a.dir, '--songs', ','.join(songs), '--out', a.out,
                    '--dur', str(a.dur), '--no-split', '--guidance', str(a.guidance),
                    '--service-version', a.service_version]
            if a.tempo_hint:
                args += ['--tempo-hint', a.tempo_hint]
            if a.variants:
                args += ['--variants', a.variants]
            if a.dry_run:
                return run('ace_from_arena.py', *args, '--dry-run')
            require_env('AUDIOCPP_HOST','AUDIOCPP_PORT')
            run('ace_from_arena.py', *args)
        files = verify_candidates(Path(a.out), Path(a.dir), songs)
        for file in files:
            run('windows_audio_api.py', 'check', str(file))
        for file in files:
            stem = file.stem.rsplit('_ace_c', 1)[0]
            args = ['--source', str(Path(a.dir) / f'{stem}.md'),
                    '--out', str(Path(a.out) / 'suno' / file.stem), '--audio', str(file)]
            if a.ui_profile:
                args += ['--ui-profile', a.ui_profile]
            if a.check_only:
                args.append('--check')
            if export_suno(args):
                raise ValueError(f'{file.name}: Suno上传配置或More Options验收失败')
        print('9条候选来源、技术检查与逐条Suno上传配置通过；音乐方向和内容描述仍需试听核实。')
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f'验收失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
