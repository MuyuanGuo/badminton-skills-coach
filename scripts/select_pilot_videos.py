#!/usr/bin/env python3
import csv
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "douyin_teaching_filtered.json"
OUTPUT_JSON = ROOT / "data" / "pilot_25_videos.json"
OUTPUT_CSV = ROOT / "data" / "pilot_25_videos.csv"

QUOTAS = {
    "后场技术": 4,
    "发力与身体运用": 3,
    "步法与移动": 3,
    "网前技术": 3,
    "发球与接发": 3,
    "双打战术": 3,
    "单打战术": 2,
    "握拍与基本动作": 2,
    "中前场与抽挡": 1,
    "训练与纠错": 1,
}

TECHNIQUE_TERMS = re.compile(
    r"杀球|吊球|高远球|发力|步法|启动|搓球|勾球|扑球|发球|接发|"
    r"双打|单打|握拍|挥拍|架拍|抽挡|落点|线路|纠错|框架|击球点"
)
SCENE_TERMS = re.compile(r"实战|对抗|防守|进攻|衔接|回动|高速|被动|主动|网前|后场")
EQUIPMENT_TERMS = re.compile(r"华羽|紫电青霜|球拍|拍线|手胶|底胶|线孔|连钉|球鞋")


def score(video):
    text = video["title"]
    value = min(len(text), 140) / 14
    value += 5 if "#羽毛球教学" in text or "羽毛球教学" in text else 0
    value += 3 if TECHNIQUE_TERMS.search(text) else 0
    value += 2 if SCENE_TERMS.search(text) else 0
    value -= 8 if EQUIPMENT_TERMS.search(text) else 0
    value -= 2 if len(text) < 25 else 0
    return value


def signature(video):
    words = TECHNIQUE_TERMS.findall(video["title"])
    return words[0] if words else video["title"][:6]


source = json.loads(SOURCE.read_text(encoding="utf-8"))
selected = []
for category, quota in QUOTAS.items():
    candidates = [
        video for video in source["videos"]
        if video["primary_category"] == category
    ]
    candidates.sort(key=score, reverse=True)
    used_signatures = set()
    picks = []
    for video in candidates:
        marker = signature(video)
        if marker in used_signatures and len(candidates) >= quota * 2:
            continue
        picks.append(video)
        used_signatures.add(marker)
        if len(picks) == quota:
            break
    if len(picks) < quota:
        for video in candidates:
            if video not in picks:
                picks.append(video)
                if len(picks) == quota:
                    break
    selected.extend(picks)

records = []
for index, video in enumerate(selected, start=1):
    records.append({
        "pilot_order": index,
        "video_id": video["video_id"],
        "primary_category": video["primary_category"],
        "tags": video["tags"],
        "title": video["title"],
        "url": video["url"],
        "processing_status": "待提取",
        "selection_score": round(score(video), 2),
    })

OUTPUT_JSON.write_text(
    json.dumps({
        "purpose": "首批教学内容提取与知识库流程验证",
        "count": len(records),
        "quotas": QUOTAS,
        "videos": records,
    }, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=records[0].keys())
    writer.writeheader()
    writer.writerows(records)

print(json.dumps({
    "selected": len(records),
    "by_category": {
        category: sum(row["primary_category"] == category for row in records)
        for category in QUOTAS
    },
}, ensure_ascii=False, indent=2))
