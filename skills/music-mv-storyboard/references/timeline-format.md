# 时间表契约

数字单位为秒，源曲绝对时间 = `source_start` + 片段相对时间。以下为虚构示例：

```json
{
  "source_start": 60,
  "duration": 12,
  "source_sha256": "optional-original-file-hash",
  "cues": [
    {"id": "L1", "start": 0.4, "end": 5.2, "text": "示例唱词", "evidence": "asr_estimate"}
  ],
  "beats": [
    {"start": 0, "end": 6, "shot": "S1", "cue_ids": ["L1"], "action": "望向远路", "camera": "缓慢跟随"},
    {"start": 6, "end": 12, "shot": "S1", "cue_ids": [], "action": "器乐中继续前行", "camera": "保持同一机位"}
  ],
  "parts": [{"name": "完整", "start": 0, "end": 12}]
}
```

- `cues`只记录实际可辨的唱句，允许器乐空隙和伴唱重叠；按起点排序。区间内可能含延音，不据末字 ASR 结束时间强制闭嘴。
- `beats`是覆盖整个片段的表演区间，无缝无重叠；同一`shot`可含多个节拍。每个节拍引用的唱句须与其时间相交。
- `parts`是一套可执行分段，从0覆盖至片段结尾；完整导演稿另写文本。不同上限的备选分段应分别保存 JSON，不能混在同一覆盖表内。
- `evidence`可用`asr_estimate`、`forced_alignment`、`manual_listening`、`unverified`。记录依据，不因小数位多就升级证据。
- `action`和`camera`供表格阅读；具体光线、身份与音频约束放导演稿，避免表格重复冗长文字。
