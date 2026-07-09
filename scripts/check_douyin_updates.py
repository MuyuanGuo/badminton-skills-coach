#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
TEACHING_PATH = ROOT / "data" / "douyin_teaching_filtered.json"
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
REPORT_PATH = ROOT / "output" / "douyin-update-report.json"

TAXONOMIES = [
    ("发球与接发", re.compile(r"发球|接发|偷后场|发接发")),
    ("后场技术", re.compile(r"杀球|重杀|点杀|劈杀|吊球|高远球|后场|架拍|挥拍|鞭打|内旋|外旋")),
    ("网前技术", re.compile(r"搓球|勾球|扑球|放网|网前|推球|展搓|收搓")),
    ("中前场与抽挡", re.compile(r"抽挡|平抽|挡网|封网|中场|抓推|抓扑")),
    ("步法与移动", re.compile(r"步法|启动|蹬跨|并步|交叉步|回动|移动|弹性|重心|身位")),
    ("发力与身体运用", re.compile(r"发力|手腕|手指|小臂|肩|肘|核心|转体|蹬转|动力链|放松")),
    ("握拍与基本动作", re.compile(r"握拍|拍面|框架|击球点|击球|引拍|随挥|基本功")),
    ("单打战术", re.compile(r"单打|控网|拉吊|突击|四方球|节奏|线路|落点")),
    ("双打战术", re.compile(r"双打|轮转|抓回头|防守反击|封网|补位|站位|混双|男双|女双")),
    ("训练与纠错", re.compile(r"训练|练习|纠错|错误|改正|辅助|方法|教学|业余球友")),
    ("比赛分析", re.compile(r"比赛|复盘|回合|运动员|世锦赛|奥运|公开赛|大师赛")),
    ("装备与参数", re.compile(r"球拍|拍线|磅|手胶|底胶|线孔|连钉|球鞋|装备")),
]

AD_STRONG = re.compile(r"紫电青霜|华羽|首发|发售|上新|直播间|购买|下单|福利|抽奖|礼盒|新品|库存|价格|链接|同款|预售|品牌合作")
EQUIPMENT = re.compile(r"球拍|拍线|磅数|手胶|底胶|线孔|连钉|球鞋|装备")
TEACHING = re.compile(
    r"羽毛球教学|羽毛球训练|教学|训练|发力|杀球|吊球|高远球|步法|搓球|勾球|扑球|放网|"
    r"发球|接发|握拍|挥拍|架拍|击球|双打|单打|战术|落点|线路|拍面|框架|纠错|基本功"
)
NON_TEACHING = re.compile(r"生日|拜年|新年|春节|放假|通知|停播|开播|日常|花絮|合影|见面会|招生|招募|学员反馈|感谢大家|粉丝|吃饭|旅游|搞笑")
MANUAL_EXCLUSIONS = {
    "7239168493294226740": "排除：广告/器材推广",
    "7588003889807756593": "排除：非教学",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_video_id(item):
    for key in ("video_id", "aweme_id", "id"):
        value = item.get(key)
        if value:
            return str(value)
    url = str(item.get("url") or "")
    match = re.search(r"/video/(\d+)", url)
    if match:
        return match.group(1)
    return None


def normalize_video(item):
    video_id = extract_video_id(item)
    if not video_id:
        return None
    url = item.get("url") or f"https://www.douyin.com/video/{video_id}"
    title = (
        item.get("title")
        or item.get("desc")
        or item.get("description")
        or item.get("raw_text")
        or ""
    )
    raw_text = item.get("raw_text") or title
    return {
        "video_id": str(video_id),
        "url": str(url),
        "title": str(title).strip(),
        "teaching_candidate": item.get("teaching_candidate", "unknown"),
        "raw_text": str(raw_text).strip(),
    }


def load_observed(path):
    payload = load_json(path)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("videos") or payload.get("items") or payload.get("aweme_list") or []
    else:
        raise SystemExit(f"Unsupported input JSON shape: {path}")

    videos = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        video = normalize_video(row)
        if not video or video["video_id"] in seen:
            continue
        seen.add(video["video_id"])
        videos.append(video)
    return videos


def classify(video):
    text = f"{video.get('title', '')} {video.get('raw_text', '')}"
    ad = bool(AD_STRONG.search(text))
    has_teaching = bool(TEACHING.search(text))
    equipment_only = bool(EQUIPMENT.search(text)) and not has_teaching
    explicit_non_teaching = bool(NON_TEACHING.search(text)) and not has_teaching

    decision = "排除：非教学"
    reason = "未发现明确教学动作、训练方法或战术信息"
    if ad and has_teaching:
        decision = "待复核：教学夹带推广"
        reason = "同时出现教学信号与品牌、发售或购买信号"
    elif ad or equipment_only:
        decision = "排除：广告/器材推广"
        reason = "出现品牌、发售、直播间、购买或纯器材信号"
    elif has_teaching and not explicit_non_teaching:
        decision = "保留：教学"
        reason = "包含明确技术、训练、纠错或战术信号"
    elif explicit_non_teaching:
        reason = "内容更接近日常、通知、招生或花絮"

    if video["video_id"] in MANUAL_EXCLUSIONS:
        decision = MANUAL_EXCLUSIONS[video["video_id"]]
        reason = "用户指定去除"

    matched = [name for name, pattern in TAXONOMIES if pattern.search(text)]
    primary_category = matched[0] if decision in {"保留：教学", "待复核：教学夹带推广"} and matched else ""
    return {
        **video,
        "author_status": "主页最新作品区发现",
        "decision": decision,
        "decision_reason": reason,
        "primary_category": primary_category,
        "tags": "；".join(matched),
    }


def known_ids():
    ids = set()
    for path, key in ((INDEX_PATH, "videos"), (TEACHING_PATH, "videos"), (QUEUE_PATH, "items")):
        if not path.exists():
            continue
        data = load_json(path)
        for item in data.get(key, []):
            ids.add(str(item["video_id"]))
    return ids


def append_to_index(new_videos):
    index = load_json(INDEX_PATH)
    existing = {str(item["video_id"]) for item in index["videos"]}
    inserts = [video for video in new_videos if video["video_id"] not in existing]
    if not inserts:
        return 0
    index["videos"] = inserts + index["videos"]
    index["collected_at"] = now_iso()
    index["collected_unique_links"] = len(index["videos"])
    index["note"] = "Updated by scripts/check_douyin_updates.py from observed homepage metadata."
    write_json(INDEX_PATH, index)
    return len(inserts)


def append_to_teaching_and_queue(classified):
    teaching = load_json(TEACHING_PATH)
    queue = load_json(QUEUE_PATH)
    teaching_existing = {str(item["video_id"]) for item in teaching["videos"]}
    queue_existing = {str(item["video_id"]) for item in queue["items"]}

    teaching_inserts = [
        item for item in classified
        if item["decision"] == "保留：教学" and item["video_id"] not in teaching_existing
    ]
    queue_inserts = [
        {
            "video_id": item["video_id"],
            "url": item["url"],
            "title": item["title"],
            "category": item["primary_category"],
            "tags": item["tags"],
            "status": "pending",
            "media_path": None,
            "duration_seconds": None,
            "attempts": 0,
            "error": None,
        }
        for item in teaching_inserts
        if item["video_id"] not in queue_existing
    ]

    if classified:
        if teaching_inserts:
            teaching["videos"] = teaching_inserts + teaching["videos"]
        teaching["generated_at"] = now_iso()
        teaching["counts"]["total"] = teaching["counts"].get("total", 0) + len(classified)
        teaching["counts"]["kept_teaching"] = len(teaching["videos"])
        teaching["counts"]["review"] = teaching["counts"].get("review", 0) + sum(
            item["decision"].startswith("待复核") for item in classified
        )
        teaching["counts"]["excluded_ads"] = teaching["counts"].get("excluded_ads", 0) + sum(
            item["decision"] == "排除：广告/器材推广" for item in classified
        )
        teaching["counts"]["excluded_non_teaching"] = teaching["counts"].get("excluded_non_teaching", 0) + sum(
            item["decision"] == "排除：非教学" for item in classified
        )
        write_json(TEACHING_PATH, teaching)

    if queue_inserts:
        queue["items"] = queue_inserts + queue["items"]
        counts = {}
        for item in queue["items"]:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        queue["counts"] = counts
        queue["updated_at"] = now_iso()
        write_json(QUEUE_PATH, queue)

    return len(teaching_inserts), len(queue_inserts)


def main():
    parser = argparse.ArgumentParser(
        description="Compare observed Douyin homepage videos with the local index and report new candidates."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "tmp" / "douyin_profile_latest.json",
        help="Observed homepage JSON with a videos/items list",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_PATH,
        help="Where to write the update report",
    )
    parser.add_argument("--apply", action="store_true", help="Append new teaching videos to the local index, teaching list, and queue")
    args = parser.parse_args()

    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    if not input_path.exists():
        raise SystemExit(
            f"Input snapshot not found: {input_path}\n"
            "Export the latest Douyin profile items to JSON first, then rerun this script."
        )

    observed = load_observed(input_path)
    existing_ids = known_ids()
    new_videos = [video for video in observed if video["video_id"] not in existing_ids]
    classified = [classify(video) for video in new_videos]
    teaching = [item for item in classified if item["decision"] == "保留：教学"]
    review = [item for item in classified if item["decision"].startswith("待复核")]
    excluded = [item for item in classified if item["decision"].startswith("排除")]

    applied = None
    if args.apply:
        index_count = append_to_index(new_videos)
        teaching_count, queue_count = append_to_teaching_and_queue(classified)
        applied = {
            "index_added": index_count,
            "teaching_added": teaching_count,
            "queue_added": queue_count,
        }

    report = {
        "generated_at": now_iso(),
        "input": str(input_path.relative_to(ROOT) if input_path.is_relative_to(ROOT) else input_path),
        "observed": len(observed),
        "new": len(new_videos),
        "teaching": len(teaching),
        "review": len(review),
        "excluded": len(excluded),
        "applied": applied,
        "new_videos": classified,
    }
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    write_json(report_path, report)
    print(json.dumps({
        "report": str(report_path),
        "observed": report["observed"],
        "new": report["new"],
        "teaching": report["teaching"],
        "review": report["review"],
        "excluded": report["excluded"],
        "applied": applied,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
