"""Separate vocals without reusing another revision's same-name audio."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

VERSION = 'vocal-source-cache-v1'


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def separate_one(api, source, target, cache_root, service_version):
    source, target = Path(source), Path(target)
    source_hash = digest(source)
    identity = dict(cache_version=VERSION, source_sha256=source_hash,
                    service_version=service_version)
    receipt = target.with_suffix('.json')
    if target.exists():
        if not receipt.is_file():
            raise ValueError(f'{target.name}: 旧人声没有来源记录，请使用新输出目录')
        previous = json.loads(receipt.read_text())
        if (any(previous.get(k) != v for k, v in identity.items())
                or previous.get('vocal_sha256') != digest(target)):
            raise ValueError(f'{target.name}: 来源、服务版本或人声已变化，请使用新输出目录')
        return previous
    namespace = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache = Path(cache_root) / namespace
    cache.mkdir(parents=True, exist_ok=True)
    wav = cache / 'source44.wav'
    # Rebuild from the verified source; no filename-only resampling cache.
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source),
                    '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', str(wav)], check=True)
    with tempfile.TemporaryDirectory(prefix='.separation-', dir=cache) as temp:
        stems = Path(temp) / 'stems'
        api.separate(wav, stems)
        vocal = stems / 'vocals.wav'
        if not vocal.is_file() or vocal.stat().st_size <= 44:
            raise ValueError('服务未返回有效vocals.wav')
        if digest(source) != source_hash:
            raise ValueError('分轨期间源音频改变，停止交付')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.pending')
        shutil.copyfile(vocal, temporary)
        metadata = dict(identity, vocal_sha256=digest(temporary), sample_rate=44100)
        temporary.replace(target)
    staged_receipt = receipt.with_name(receipt.name + '.pending')
    staged_receipt.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    staged_receipt.replace(receipt)
    return metadata
