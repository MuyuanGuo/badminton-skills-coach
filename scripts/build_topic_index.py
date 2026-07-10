#!/usr/bin/env python3
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
JSON_OUTPUT = ROOT / "data" / "knowledge" / "topic_index.json"
SKILL_MARKDOWN_OUTPUT = (
    ROOT / "skills" / "liuhui-badminton-coach" / "references" / "topic-index.md"
)


TAXONOMY = [
    {
        "name": "后场技术",
        "description": "后场击球、被动处理、杀吊突击与架拍框架。",
        "subtopics": {
            "被动后场与高远": ["被动", "高远", "后高点", "底线", "摆脱", "反手后场"],
            "杀球、突击与压球": ["杀球", "突击", "压球", "重杀", "点杀", "落点"],
            "架拍与框架": ["架拍", "框架", "抬拍", "举拍", "顶肘"],
            "吊球与劈吊": ["吊球", "劈吊", "滑板", "假动作"],
            "反手后场": ["反手", "反拍", "反手高远"],
        },
    },
    {
        "name": "步法与移动",
        "description": "启动、移动、回动、低重心和不同区域步法。",
        "subtopics": {
            "启动与预动": ["启动", "预动", "起动", "蹬地"],
            "回动与连贯": ["回动", "连贯", "衔接", "下一拍"],
            "交叉步与并步": ["交叉步", "并步", "垫步", "步伐"],
            "低重心与被动救球": ["低重心", "被动步法", "救球", "重心"],
            "正手区与网前步法": ["正手区", "网前步法", "上网", "前后步法"],
        },
    },
    {
        "name": "发力与身体运用",
        "description": "放松发力、旋转传导、腰腹、手腕与击球发力区间。",
        "subtopics": {
            "放松与爆发": ["放松", "爆发", "发力", "打透"],
            "腰腹与身体旋转": ["腰腹", "核心", "旋转", "转体", "身体"],
            "手腕、内旋与拍面": ["手腕", "内旋", "拍面", "握拍"],
            "贴球发力": ["贴球", "贴近", "发力空间"],
            "挥拍路径": ["挥拍", "随挥", "半程", "全程", "大臂"],
        },
    },
    {
        "name": "中前场与抽挡",
        "description": "抽挡、接杀、防守、网前技术和中前场转换。",
        "subtopics": {
            "平抽挡与高速对抗": ["抽挡", "平抽挡", "高速对抗", "快球"],
            "接杀与防守": ["接杀", "防守", "防反", "挡杀"],
            "网前搓勾扑": ["网前", "搓球", "勾球", "扑球", "滚网"],
            "挡网与放网": ["挡网", "放网", "网前球"],
            "中前场衔接": ["中前场", "衔接", "连贯", "封网"],
        },
    },
    {
        "name": "双打战术",
        "description": "双打轮转、防守站位、封网、进攻组织和发接发配合。",
        "subtopics": {
            "双打发接发": ["双打发接发", "接发", "发接发", "抓球"],
            "轮转与补位": ["轮转", "补位", "前后", "左右"],
            "双打防守站位": ["双打防守", "防守站位", "平行", "护边"],
            "封网与抢网": ["封网", "抢网", "前场"],
            "进攻组织": ["进攻", "组织", "压制", "后杀前封"],
        },
    },
    {
        "name": "发球与接发",
        "description": "单打与双打发球、接发、发接发目的性。",
        "subtopics": {
            "发球": ["发球", "发小球", "偷后场"],
            "接发": ["接发", "接发球", "抢发"],
            "发接发目的性": ["目的性", "抓球", "主动", "限制"],
        },
    },
    {
        "name": "训练与纠错",
        "description": "训练设计、常见错误、实战复盘和恢复对抗能力。",
        "subtopics": {
            "训练方法": ["训练", "练习", "多球", "三步", "方法"],
            "常见错误纠正": ["错误", "不对", "纠正", "问题"],
            "实战复盘": ["实战", "战术", "复盘", "比赛"],
            "恢复与体能": ["恢复", "体能", "对抗能力", "精疲力尽"],
        },
    },
    {
        "name": "握拍与基本动作",
        "description": "握拍、基础挥拍、基础动作和拍面控制。",
        "subtopics": {
            "握拍": ["握拍", "正手握拍", "反手握拍"],
            "基础挥拍": ["基础挥拍", "挥拍", "随摆"],
            "拍面控制": ["拍面", "角度", "控制"],
        },
    },
]


def flatten(value):
    if isinstance(value, dict):
        return " ".join(flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return str(value)


def video_text(video):
    return flatten(
        {
            "title": video["title"],
            "teaching_note": video["teaching_note"],
        }
    ).lower()


def keyword_score(text, keywords):
    return sum(text.count(keyword.lower()) for keyword in keywords)


def video_score(video, text, keywords):
    score = keyword_score(text, keywords)
    if video["confidence"] == "curated":
        score += 3
    if video["processing_status"] == "needs_visual_review":
        score -= 2
    return score


def compact_video(video, score):
    note = video.get("teaching_note") or {}
    return {
        "video_id": video["video_id"],
        "title": video["title"],
        "url": video["url"],
        "category": video["category"],
        "confidence": video["confidence"],
        "processing_status": video["processing_status"],
        "topic": note.get("topic") or note.get("title") or video["title"],
        "score": score,
    }


def build_index(data):
    categories = []
    coverage_counter = Counter()
    assigned_video_ids = set()
    text_cache = {video["video_id"]: video_text(video) for video in data["videos"]}

    for category in TAXONOMY:
        subtopics = []
        category_video_ids = set()
        for name, keywords in category["subtopics"].items():
            matches = []
            for video in data["videos"]:
                score = video_score(video, text_cache[video["video_id"]], keywords)
                if score > 0:
                    matches.append(compact_video(video, score))
            matches.sort(
                key=lambda item: (
                    -item["score"],
                    item["processing_status"] == "needs_visual_review",
                    item["title"],
                )
            )
            ready_count = sum(item["processing_status"] == "ready" for item in matches)
            review_count = sum(
                item["processing_status"] == "needs_visual_review" for item in matches
            )
            category_video_ids.update(item["video_id"] for item in matches)
            assigned_video_ids.update(item["video_id"] for item in matches)
            subtopics.append(
                {
                    "name": name,
                    "keywords": keywords,
                    "video_count": len(matches),
                    "ready_count": ready_count,
                    "needs_visual_review_count": review_count,
                    "representative_videos": matches[:5],
                }
            )
        for video_id in category_video_ids:
            coverage_counter[video_id] += 1
        categories.append(
            {
                "name": category["name"],
                "description": category["description"],
                "video_count": len(category_video_ids),
                "subtopics": subtopics,
            }
        )

    return {
        "version": "topic-index-v1",
        "source": str(SOURCE.relative_to(ROOT)),
        "scope": data.get("scope"),
        "source_updated_at": data.get("updated_at"),
        "video_count": len(data["videos"]),
        "assigned_video_count": len(assigned_video_ids),
        "multi_topic_video_count": sum(count > 1 for count in coverage_counter.values()),
        "categories": categories,
    }


def markdown(index):
    lines = [
        "# 刘辉羽毛球主题索引",
        "",
        "Use this index to orient retrieval and answer structure. It is a topic map, not a substitute for timestamped evidence from `knowledge-base.json`.",
        "",
        f"- Source: `{index['source']}`",
        f"- Videos: `{index['video_count']}`",
        f"- Assigned videos: `{index['assigned_video_count']}`",
        f"- Multi-topic videos: `{index['multi_topic_video_count']}`",
        "",
        "## How To Use",
        "",
        "1. Locate the user's issue in the topic map.",
        "2. Run `scripts/search_knowledge.py` with the user's actual words and the closest topic keywords.",
        "3. Use representative videos only as leads; cite timestamped evidence from retrieved entries.",
        "4. If a representative video is marked `needs_visual_review`, treat it as a lead until reviewed.",
        "",
        "## Topic Map",
        "",
    ]

    for category in index["categories"]:
        lines.extend(
            [
                f"### {category['name']}",
                "",
                f"{category['description']}",
                "",
                f"- Matched videos: `{category['video_count']}`",
                "",
            ]
        )
        for subtopic in category["subtopics"]:
            lines.append(
                f"- **{subtopic['name']}**: `{subtopic['video_count']}` videos, "
                f"`{subtopic['ready_count']}` ready, "
                f"`{subtopic['needs_visual_review_count']}` needs visual review."
            )
            lines.append(f"  Keywords: {', '.join(subtopic['keywords'])}")
            reps = subtopic["representative_videos"][:3]
            if reps:
                lines.append("  Representative videos:")
                for video in reps:
                    status = video["processing_status"]
                    lines.append(
                        f"  - {video['title']} [{status}] {video['url']}"
                    )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    index = build_index(data)
    JSON_OUTPUT.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    SKILL_MARKDOWN_OUTPUT.write_text(markdown(index), encoding="utf-8")
    print(
        json.dumps(
            {
                "video_count": index["video_count"],
                "assigned_video_count": index["assigned_video_count"],
                "categories": len(index["categories"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
