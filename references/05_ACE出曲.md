# ACE候选与可复现性

每篇歌词提供三种有名称的音乐方向，例如口语叙述、节奏问答、长线抒情。默认方向仅为起点；可用JSON覆盖，每项包含`name / direction / seed / temperature`。不同方向是否实际落地要听音频，不能根据不同种子就宣布曲调不同。

```bash
python scripts/ace_three.py --dir /path/to/runs --songs a__0,b__1,c__2 \
  --out /path/to/new-batch/ace --service-version local-model-version --dry-run
```

检查请求后去掉`--dry-run`生成。`--variants`可指定三条方向的JSON；`--guidance`显式覆盖扩散guidance，基线为1。时长默认215秒，可用`--dur`调整，须≤240秒。

每条音频附JSON，保存来源、请求、方向、配置指纹和音频校验值；批次含`candidates.json`。同名音频无侧车、音频损坏或歌词/参数改变时明确失败，使用新输出目录。记录`--service-version`，更换服务或模型后更新标签。

`ace_three.py`在候选来源和技术检查通过后，默认生成`<out>/suno/<音频stem>/`，逐条包含Styles、歌词、Exclude、`More_Options.json`、`00_Suno参数卡.md`及`Audio_Description.txt`。上传配置与More Options在同一张卡和同一个JSON中，绑定对应音频的文件名与SHA256；完整歌曲默认Full Song、建议后续Cover，描述采用保守模板并标为待听辨核实。默认不猜歌手性别、语言、BPM或地域唱法。配置生成不自动上传、不调用Suno。

可传`--ui-profile /path/to/task-options.json`覆盖本批More Options；该配置在生成前验证，复核时须传同一文件。`--dry-run`只预览，不生成音频或参数卡。底层工具直接出曲时，也须按[06](06_Suno配置与歌词.md)逐条使用`--audio`导出，不能遗漏上传配置。

```bash
python scripts/ace_three.py --dir /path/to/runs --songs a__0,b__1,c__2 \
  --out /path/to/new-batch/ace --check-only
```

此命令核对指定3篇各3条和来源指纹，调用分段静音检查，并只读复核逐候选Suno输入、上传配置与More Options；缺失或过期即失败，不自动补写。历史批次没有参数卡时，另建配置目录，用[06](06_Suno配置与歌词.md)的`--audio`命令补齐；不要改动已发布批次。技术检查通过后仍需匿名试听。

## 候选保留与进入Suno的条件

ACE保留为本地候选来源，不能因为某批落选就从技能移除，也不要求每个Suno任务都先跑ACE。先试听再决定用途：成品满意可直接交付；旋律、句子布局或演唱方向值得保留时，再选作Suno音频母版；未获认可的候选保留为待选，不自动全部上传并生成。这样减少盲目重抽的Suno额度消耗，但上传后的Cover或其他生成仍可能消耗额度，以界面显示为准。

完整ACE歌曲通常按Full Song上传；局部旋律草稿按Song Demo、分轨清唱按Voice，具体见[17_音频上传与母版选择](17_音频上传与母版选择.md)。本地音质不够理想不等于旋律不能用；也不能承诺Suno一定只改善音质而保留全部旋律和音色。

BPM、速度文字、guidance的作用与模型/曲风相关。旧gs=3优势说法已失去当前本地实验支持，不能作通用默认。慢民谣可尝试`--tempo-hint`描述速度感，但不要承诺数字精确执行。证据范围见[13](13_参数证据.md)。
