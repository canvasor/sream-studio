"""Local catalog loading and non-destructive archive writes."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from _common import tools_dir


def workspace_dir():
    return Path(os.environ.get('WORKSPACE_DIR') or Path.home() / 'dsh-workspace').expanduser()


def library_dir():
    return Path(os.environ.get('MUSIC_LIBRARY_DIR') or Path.home() / 'music-studio/作品库').expanduser()


def load_songs():
    """Load the optional local catalog only after CLI argument parsing."""
    source = tools_dir() / 'release_meta.py'
    if not source.is_file():
        raise SystemExit('缺少本地歌曲目录：请在 TOOLS_DIR 下配置 release_meta.py（SONGS 列表），见 references/21_创作证据与生成记录.md')
    spec = importlib.util.spec_from_file_location('release_meta', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SONGS


def check_song(song, library):
    """Catalog values must stay inside one real work directory."""
    for key in ('name', 'lib_dir', 'wav'):
        value = song.get(key)
        if not isinstance(value, str) or value in {'', '.', '..'} or '/' in value or '\\' in value:
            raise ValueError(f'歌曲目录字段 {key} 必须为单个文件或目录名')
    directory = library / song['lib_dir']
    if directory.is_symlink() or directory.resolve().parent != library.resolve():
        raise ValueError('作品目录不能指向作品库之外')
    return directory


def write_record(out, content, force=False, dry_run=False):
    """Exclusive creation; explicit replacement retains an independent backup."""
    if out.exists() and not force:
        print(f'  跳过已有档案：{out.name}（需要替换时使用 --force，会先备份）')
        return False
    if out.is_symlink():
        raise ValueError('档案目标不能为符号链接')
    if dry_run:
        print(f'  预览：{out}（{len(content)} 字符；不写文件）')
        return True
    out.parent.mkdir(parents=True, exist_ok=True)
    if not force:
        with out.open('x', encoding='utf-8') as stream:
            stream.write(content)
        return True
    if out.exists():
        backup = out.with_name(f'{out.name}.backup-{uuid.uuid4().hex}')
        shutil.copy2(out, backup)
    # Keep the old target intact until the replacement is fully written.
    with tempfile.NamedTemporaryFile(dir=out.parent, prefix='.record-', delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(content.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temp.unlink()
            raise
    try:
        temp.replace(out)
    finally:
        temp.unlink(missing_ok=True)
    return True
