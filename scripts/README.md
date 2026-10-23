# 运行编排脚本

设置`TOOLS_DIR`指向工作区底层工具，`PY`选择含numpy/librosa/pypinyin的解释器。需要生成或分轨时配置`AUDIOCPP_HOST`和`AUDIOCPP_PORT`。密钥与地址不入库。

```bash
export TOOLS_DIR=~/dsh-workspace/tools
export PY=~/dsh-workspace/tools/venv-sep/bin/python
```

| 脚本 | 用途 |
|---|---|
| arena.py | gen / score（judge别名）/ report / top3；新版六维评审 |
| ace_three.py | top3×3方向，预览、来源验证、静音检查及默认逐候选Suno上传参数包 |
| split_vocal.py | 完整人声与末100秒清唱，记录原曲偏移 |
| make_suno_config.py | 任意Markdown新歌导出Suno输入、平台纯文本及More Options参数卡 |
| make_lyrics.py | `--source`导出通用交付；旧`--song`保留历史兼容 |
| listening_test.py | 匿名响度归一试听、选择记录与汇总 |
| sync_delivery.py | 共享交付复制、SHA256校验、预览、续跑与只读复核 |
| drive_mv.py | 校验歌词与时间轴，原素材一次合成高清/上传两个行车MV版本 |
| patch_pitch.py | 局部降调修音：只把某几个字的音高改掉，其余不动；保共振峰、交叉淡化贴回 |
| album_covers.py | 专辑 1:1 封面批量候选（GPT-Image / Seedream 两条通道，含文字核对图）|
| compose_square_cover.py | 底图叠字出 1:1 封面（模型文字不可用时的备选路径）|
| wan_client.py | 独立Wan接口：演唱/叙事镜头、任务查询与下载；支持离线预览 |
| make_evidence_pack.py | 创作文件快照、SHA256清单及ZIP；保留目录层级，拒绝覆盖旧包 |
| make_generation_record.py | 当前归档文件整理成待核实草稿；已有记录默认跳过 |
| recover_generation_record.py | 从PDF和完整配置原文提取记录；已有记录默认跳过，强制替换先备份 |
| ../skills/music-mv-storyboard/scripts/timeline.py | 分镜双时间轴校验与表格导出，无需生成服务 |

建议先用`--help`了解真实参数。完整出曲前使用`ace_three.py --dry-run`，预览不会连接服务或写音频。

```bash
python scripts/arena.py score --songs writer__0,other__1
python scripts/arena.py report
python scripts/arena.py top3
python scripts/ace_three.py --dir /path/to/runs --songs a__0,b__1,c__2 \
  --out /path/to/new-batch/ace --service-version local-model-version --dry-run
python scripts/split_vocal.py --src /path/to/new-batch/ace --out /path/to/new-batch/tail
python scripts/make_suno_config.py --source /path/to/song.md --out /path/to/package-v1
python scripts/make_suno_config.py --source /path/to/song.md --out /path/to/package-v1 --check
python scripts/make_suno_config.py --source /path/to/song.md --audio /path/to/candidate.wav \
  --out /path/to/package-audio-v1
```

Suno导出包含`More_Options.json`与`00_Suno参数卡.md`，默认值见`templates/suno_more_options.json`。任务级修改可加`--ui-profile /path/to/task-options.json`，例如`{"profile":"task-example","values":{"style_influence":70}}`；复核时使用相同配置。`--check`只检查文件，不写入，也不验证Suno界面是否已设置。参数变化使用新输出目录。界面适用范围见[配置与歌词](../references/06_Suno配置与歌词.md)。独立参数卡测试：`python3 scripts/test_suno_options.py`。

`ace_three.py`生成通过检查后，自动为每条候选建立`<out>/suno/<音频stem>/`，包括歌词/Styles、上传配置及More Options；`--check-only`只读核验这些文件，`--dry-run`不导出。该命令也支持`--ui-profile`，生成与复核时须一致。手动`make_suno_config.py --audio ...`会将音频类型（默认Full Song）、描述与建议操作合入同一张参数卡和`More_Options.json`，另给可复制的`Audio_Description.txt`；支持`--audio-type`、`--audio-description-file`和`--audio-operation`覆盖。上传模板见`templates/suno_audio_upload.json`，文件SHA256变化需新配置目录；模板描述需实际听辨确认。没有自动上传或Suno生成。编排测试：`python3 scripts/test_ace_suno_delivery.py`。

生成、评审等封装依赖外部`tools/`，单独克隆技能仓库不能替代底层实现。试听工具依赖Python与FFmpeg；共享同步工具只依赖Python标准库，均可独立使用。选曲流程见[质量与试听](../references/12_质量与试听.md)，同步命令与Windows核验见[产出与归档](../references/11_产出与归档.md)。

行车MV正式出片须传`--lyrics`；行数、时间范围或句子对应明显不匹配时，保存`_work/歌词时间轴_待核对.json`并停止。校对后传`--timings`可跳过Whisper恢复制作。拼接、封面、字幕与音轨由一次FFmpeg调用输出两版，每版各编码一次；不再生成中间视频或从高清版二次转码。完整用法见[16](../references/16_驾车行车MV.md)，本地渲染测试：`python3 scripts/test_drive_mv.py`。

Wan用法与接口核实范围见[19](../references/19_虚拟歌手MV.md)；证据脚本的本地歌曲目录、环境变量、预览和备份行为见[21](../references/21_创作证据与生成记录.md)。这些脚本的`--help`不需要本地歌曲目录或凭据。例：

```bash
python3 scripts/make_evidence_pack.py --song 示例歌曲 --out /path/to/evidence-v1 --dry-run
python3 scripts/make_generation_record.py --song 示例歌曲 --dry-run
python3 scripts/wan_client.py s2v --image /path/to/person.jpg --audio /path/to/vocal.wav \
  --resolution 480P --out /path/to/shot.mp4 --dry-run
python3 skills/music-mv-storyboard/scripts/timeline.py /path/to/timeline.json --max-seconds 10
```
