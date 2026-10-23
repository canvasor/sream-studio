"""Export requested Suno UI settings separately from song text and generation APIs."""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

PROFILE = Path(__file__).resolve().parent.parent / 'templates' / 'suno_more_options.json'
UPLOAD_PROFILE = PROFILE.with_name('suno_audio_upload.json')
LABELS = {
    'variety': 'Variety',
    'style_influence': 'Style Influence',
    'max_mode': 'Max Mode',
    'weirdness': 'Weirdness',
    'duration': 'Duration',
    'personalize': 'Personalize / My Taste',
}


def prepare_upload(audio, *, audio_type=None, description=None, operation=None):
    """Bind manual upload instructions to the actual file; do not infer its sound."""
    profile = json.loads(UPLOAD_PROFILE.read_text(encoding='utf-8'))
    audio_type = audio_type or profile['default_type']
    if audio_type not in profile['descriptions']:
        raise ValueError('不支持的音频类型')
    operation = operation or profile['default_operation']
    if operation not in ('Cover', 'Extend', 'Edit'):
        raise ValueError('上传后操作须为Cover、Extend或Edit')
    default_description = description is None
    description = profile['descriptions'][audio_type] if default_description else description.strip()
    if not description or any(ord(char) < 32 and char not in '\n\t' for char in description):
        raise ValueError('音频描述不能为空或包含异常控制字符')
    audio = Path(audio)
    if not audio.is_file() or audio.stat().st_size == 0:
        raise ValueError('上传源音频不存在或为空')
    digest = hashlib.sha256()
    with audio.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return dict(version=profile['version'], file=audio.name, sha256=digest.hexdigest(),
                audio_type=audio_type, description=description, suggested_operation=operation,
                description_basis='type_template_pending_listening_review' if default_description else 'task_supplied',
                selection_basis=profile['basis'],
                available_types=list(profile['descriptions']),
                actual_upload_status='not_verified', audio_influence=None)


def prepare(config, profile_path=None, upload=None):
    profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    if profile_path:
        override = json.loads(Path(profile_path).read_text(encoding='utf-8'))
        if not isinstance(override, dict):
            raise ValueError('ui-profile须为JSON对象')
        values = override.get('values', {})
        if not isinstance(values, dict) or set(values) - set(LABELS):
            raise ValueError('ui-profile.values包含未知控件')
        profile['values'].update(values)
        profile['profile'] = override.get('profile', 'task-override')
        profile['basis'] = 'task_override'
    values = profile['values']
    for field in ('style_influence', 'weirdness'):
        value = values[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise ValueError(f'{field}须为0–100之间的数值')
    for field in ('variety', 'max_mode', 'duration', 'personalize'):
        if not isinstance(values[field], str) or not values[field].strip():
            raise ValueError(f'{field}须为非空界面值')
    exclude = config.get('exclude', '').strip()
    items = [s.strip() for s in re.split(r'[,，;；\n]+', exclude) if s.strip()]
    genders = set(re.findall(r'\b(female|male)\b', config['styles'], re.I))
    genders = {s.lower() for s in genders}
    gender = next(iter(genders)).title() if len(genders) == 1 else '按本首演唱形式确认'
    data = dict(
        version='suno-ui-options-v2', profile=profile['profile'],
        basis=profile['basis'], purpose='manual_settings_request',
        requested={**values, 'exclude_styles': exclude},
        exclude_policy=profile['exclude_policy'],
        conditional=dict(vocal_gender=gender, audio_influence=None),
        audio_upload=upload,
        notes=profile['notes'], official_slider_reference=profile['official_slider_reference'],
    )
    title = config.get('title', '未命名歌曲').replace('\n', ' ')
    rows = [f'# Suno 参数卡 · {title}', '',
            '以下为用户指定的项目默认值；后续明确要求可覆盖。它们是手动填写建议，不代表已设置Suno，也不是官方通用最优值。', '',
            '在支持自定义歌词的模式中打开 More Options / Advanced Options。控件名称和可用项以当前账户、模型和界面为准；找不到就记录“不支持/未找到”，不要假定已生效。', '',
            '## 通用界面参数', '', '| 控件 | 本首填写 | 依据与说明 |', '|---|---|---|']
    for key, label in LABELS.items():
        value = f'{values[key]}%' if key in ('style_influence', 'weirdness') else values[key]
        rows.append(f'| {label} | **{value}** | {profile["notes"][key]} |')
    rows.append(f'| Exclude Styles | 复制本首 Exclude.txt（当前{len(items)}项） | {profile["exclude_policy"]} |')
    if any(re.match(r'^no\b', item, re.I) for item in items):
        rows.extend(['', '本首Exclude含以no开头的项目，请检查是否应改为裸元素；导出不会自动改写原始输入。'])
    if upload is not None:
        rows.extend(['', '## 上传音频：本候选配置', '',
                     '| 上传页面项目 | 本次填写 |', '|---|---|',
                     f'| 源文件 | {upload["file"]} |',
                     f'| 音频类型 | **{upload["audio_type"]}** |',
                     f'| 上传后建议操作 | {upload["suggested_operation"]}；按任务确认，并非已执行 |',
                     '| 上传状态 | 等待Uploading Clip完成，再点Continue |',
                     '| Audio Influence | 上传并启用参考后按任务填写，记录实际值 |', '',
                     'Describes the contents of your uploaded audio（也可复制Audio_Description.txt）：', '',
                     '```text', upload['description'], '```', '',
                     '此描述来自类型模板或任务填写，尚未通过实际听辨核实；请确认与源文件一致。默认不从Styles推断实际歌手性别、语言、BPM、调性或地域唱法。', '',
                     '页面音频类型选项：' + '、'.join(upload['available_types']) + '。完整歌曲默认Full Song；草稿选Song Demo，清唱选Voice，单独乐器分轨选Instrument Stem。', '',
                     f'源音频SHA256：`{upload["sha256"]}`。配置只绑定源文件，不代表已上传、已使用参考或已生成；上传选段时另记原曲起止时间。'])
    rows.extend(['', '## 按本首与任务填写', '',
                 '| 项目 | 填写方式 |', '|---|---|',
                 '| Model / 模型版本 | 记录当前实际版本；同轮对照固定一致 |',
                 f'| Vocal Gender | {gender}；来自Styles，合唱/对唱须按设计确认 |',
                 '| Instrumental / 纯伴奏 | 需要唱词时关闭；纯器乐任务按需求开启 |',
                 '| Audio Influence | 纯文本生成不填；上传参考音频才按任务设置并记录实际值，不默认20% |',
                 '| Persona / 续写 / 翻唱 | 纯文本平台对照时不启用；任务明确需要时另行记录 |', '',
                 '## 输入与记录', '',
                 '- Styles.txt、Lyrics_Suno.txt、Exclude.txt分别粘入对应输入框。More_Options.json是本地参数记录，不是官方导入API。',
                 '- 界面滑杆在界面里设置，不把百分比或本地ACE参数写进Styles充当设置。',
                 '- 记录实际模型、实际控件值和缺失控件；一次返回的候选都保留。新设置与旧轮默认滑杆结果分开记录。',
                 '- 参数卡或歌词修订后使用新交付目录，保留历史版本。', '',
                 '## 使用ACE或其他音频母版时', '',
                 '- 先试听选母版；ACE成品满意可直接用，值得继续的候选再上传Suno，不自动消耗额度重做全部候选。已有满意Suno作品也可继续编辑。',
                 '- 完整主唱加伴奏、有完整歌曲结构：通常选Full Song；局部旋律草稿：Song Demo；分离清唱：Voice；单独乐器声部：Instrument Stem。按实际内容选，不把类型当作质量或旋律锁定开关。',
                 '- Describes the contents写源文件实际的人声、乐器、语言、结构与录音特点；改编目标另填Styles。上传完成后再Continue。',
                 '- 上传入库不等于已启用参考：生成时确认源音频及Cover、Extend或编辑操作，记录选段与Audio Influence。纯文本分支不启用音频参考。',
                 '- Cover适合尝试再演绎，Extend用于续写；不能保证只提升音质而不改变旋律、音色或结构。', '',
                 '官方[Creative Sliders](' + profile['official_slider_reference'] + ')说明Weirdness从Safe到Chaos、50%为常规中点，Style Influence从Loose到Strong，上传音频时提供Audio Influence。该文不支持“50%丢掉一半提示词权威”的解释。其他控件的完整行为仍须按对应版本核实。', ''])
    files = {'More_Options.json': json.dumps(data, ensure_ascii=False, indent=2) + '\n',
             '00_Suno参数卡.md': '\n'.join(rows)}
    if upload is not None:
        files['Audio_Description.txt'] = upload['description'] + '\n'
    return files


def update_package(out, *, check=False, profile_path=None, upload=None):
    out = Path(out)
    config = json.loads((out / 'suno_config.json').read_text(encoding='utf-8'))
    files = prepare(config, profile_path, upload)
    for name, content in files.items():
        path = out / name
        if check:
            if not path.is_file() or path.read_text(encoding='utf-8') != content:
                raise ValueError(f'{name}缺失或与当前界面参数配置不一致')
        elif path.exists() and path.read_text(encoding='utf-8') != content:
            raise ValueError('已有参数卡与本次配置不同，请使用新输出目录')
    if not check:
        for name, content in files.items():
            target = out / name
            temp = target.with_name(target.name + '.tmp')
            temp.write_text(content, encoding='utf-8')
            temp.replace(target)
