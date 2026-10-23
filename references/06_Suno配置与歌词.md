# 分轨与两套歌词交付

## 分轨

```bash
python scripts/split_vocal.py --src /path/to/ace --out /path/to/tail --tail 100 \
  --cache-dir /path/to/local-cache --service-version sep-model-version
```

HTDemucs输入先适配采样率；完整人声保留在源目录供内部分析，交付清唱为末约100秒。每个片段附JSON，包含来源路径、原轨起止秒数。`--skip-split`只使用已有完整人声，不需要连接分轨服务。

重采样缓存按源音频SHA256与服务版本隔离；同名新音频不会复用上版数据。完整人声附来源和输出校验值，来源变化、文件损坏或旧人声缺少记录时停止，使用新输出目录。缓存默认在系统临时目录，可显式指定工作区临时目录，不放进共享交付。服务版本省略时标为`unversioned-service`，不宣称覆盖服务更换的缓存失效。

分析人声占比时应重采样并比较原曲相同时间窗。片段没有偏移元数据时跳过该项，不猜其位置。分轨人声可能有伪影，不能当成录音室干声。

## 任意新歌的Suno与平台交付

```bash
python scripts/make_suno_config.py --source /path/to/song.md --out /path/to/package-v1
python scripts/make_suno_config.py --source /path/to/song.md --out /path/to/package-v1 --check
```

输出：`suno_config.json`、`Styles.txt`、`Lyrics_Suno.txt`、`Exclude.txt`、`歌词_平台纯文本.txt`，以及`More_Options.json`、`00_Suno参数卡.md`。参数卡列出通用界面设置与本首演唱选项；传入`--audio`时额外输出`Audio_Description.txt`，并将音频类型、描述与操作建议合入同一张卡及`More_Options.json.audio_upload`。歌词与风格分别粘入对应框。两个JSON都是本地交付结构，不是Suno官方导入API格式，也不会自动操作界面。

- Suno歌词保留英文结构标签与演唱提示。
- 发布平台歌词去结构标签与空行，保留唱词、连续重复、标点与普通空格；异常控制字符阻止导出。
- 改稿使用新输出目录，检查模式核对交付文件与当前来源。
- `make_lyrics.py --source ... --out ...`也可导出同一套文件。旧固定歌曲的`--song`命令只作历史兼容。
- 新交付使用`--source`流程；历史固定歌名卡可能含旧规则，不作为最新界面参数的依据。直接调用外部`song_package.prepare()`时，须再调用本仓库`suno_options.update_package()`补齐参数卡；ACE音频同时用`prepare_upload()`生成并传入`upload`，核验实际交付文件，不能只说模板已更新。

人声、主体曲风、速度感、主要乐器与段落变化写清楚即可。Exclude按实际需要简短填写；不要把2–4项、固定滑杆数值或[End]能防止拖尾写成无条件保证。记录当次界面与模型版本，成品再次检查。

## 上传音频与母版

保留ACE作为候选来源，默认每条生成后都备齐上传配置，再试听挑出值得继续的版本，决定直接使用或上传Suno。`ace_three.py`自动逐条导出；手动出曲或为旧音频另做配置时：

```bash
python scripts/make_suno_config.py --source /path/to/song.md --audio /path/to/candidate.wav \
  --out /path/to/package-v2
python scripts/make_suno_config.py --source /path/to/song.md --audio /path/to/candidate.wav \
  --out /path/to/package-v2 --check
```

默认Full Song与保守内容描述；可用`--audio-type 'Song Demo'`或`--audio-type Voice`覆盖，并用`--audio-description-file /path/to/description.txt`提供经听辨确认的UTF-8描述。`--audio-operation Cover|Extend|Edit`记录建议操作，默认Cover。描述框文案、全部十个类型选项与所选类型、源音频SHA256、上传完成提示及操作建议都在`00_Suno参数卡.md`中，More Options保持同页；JSON记录同样信息。模板在[上传配置](../templates/suno_audio_upload.json)。上传或描述改变后用新目录；复核使用相同音频与覆盖项。纯文本导出不传`--audio`，JSON的`audio_upload`为null。

描述模板只按内容类型给出起点，标记待实际听辨核实，不把Styles中的期望声线、语言、BPM或地域唱法写成已听到的事实。详细选择与上传后操作区别见[17_音频上传与母版选择](17_音频上传与母版选择.md)。不能以“粗糙音质”代替对歌曲结构是否完整的判断。

## More Options / Advanced Options

在支持自定义歌词的模式中打开高级选项，以实际界面为准。项目默认来自用户的明确填写偏好，源配置为[模板JSON](../templates/suno_more_options.json)：Variety **Off**、Style Influence **80%**、Max Mode **On**、Weirdness **45%**、Duration **Auto**、Personalize / My Taste **Off**；Exclude通常取本首的**2–4项裸元素，不加no**。后续明确任务要求可覆盖，不自动改动已交付批次。

- 控件缺失、名称不同或当前模型不支持时，记录实际情况，不假定设置成功。Variety若只有数值滑杆，先确认其最小值是否代表关闭，不凭名称推定映射。
- Vocal Gender按本首Styles与演唱形式填写；模型版本记录实际选择，跨候选对照保持一致。需要唱词时关闭纯伴奏。
- Audio Influence仅上传音频时适用；纯文本对照不填，不套用历史20%经验。Persona、续写或翻唱按任务决定，纯文本对照时不启用。
- 参数卡是请求值；生成记录另记实际模型、滑杆和不支持项。Suno滑杆与本地ACE的steps、guidance、seed等没有数值等价关系。设置变化后另开对照轮次。

任务级覆盖文件只需指定变化项，例如`{"profile":"task-example","values":{"style_influence":70}}`：

```bash
python scripts/make_suno_config.py --source /path/to/song.md --out /path/to/package-v2 \
  --ui-profile /path/to/task-options.json
python scripts/make_suno_config.py --source /path/to/song.md --out /path/to/package-v2 \
  --ui-profile /path/to/task-options.json --check
```

官方[Creative Sliders](https://help.suno.com/en/articles/6141377)说明Weirdness的50%为常规中点，Style Influence控制Loose到Strong，并说明上传音频时有Audio Influence。它不支持“50%丢掉一半提示词权威”；也不能据此断言Variety Normal使提示词完全失效、Custom必然硬切、Max Mode必然更优。其他行为按对应版本核实，证据边界见[13](13_参数证据.md)。
