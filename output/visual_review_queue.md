# 刘辉羽毛球视觉复核队列

This queue ranks `needs_visual_review` videos by likely coaching value. Use it to review the most useful visual-first clips before treating them as strong evidence.

- Source: `data/knowledge/douyin_knowledge_base.json`
- Pending videos: `0`

## Review Status Values

- `approved`: teaching content is clear and timestamped cues are reliable.
- `needs_correction`: teaching content is useful, but ASR/topic fields need correction.
- `not_teaching`: exclude from coaching evidence.
- `low_value`: teaching exists but should not be prioritized.

## Top Priority Items
