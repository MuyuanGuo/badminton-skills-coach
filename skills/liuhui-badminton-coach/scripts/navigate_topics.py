#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOPIC_MAP = ROOT / "references" / "topic-map.json"
PRACTICE_RULES = ROOT / "references" / "practice-plan-rules.json"

LEARNING_TERMS = [
    "系统学",
    "系统学习",
    "学习路径",
    "从零",
    "入门",
    "进阶",
    "路线",
    "顺序",
    "阶段",
    "怎么学",
]
NAVIGATION_TERMS = [
    "主题",
    "知识图谱",
    "图谱",
    "结构",
    "目录",
    "有哪些",
    "展开",
    "哪几块",
    "分哪",
    "分类",
    "模块",
]
LEVEL_SIGNALS = {
    "beginner": ["零基础", "新手", "初学", "刚学", "入门"],
    "intermediate": ["中级", "有基础", "业余中级", "打了几年"],
    "advanced": ["高级", "高水平", "专业", "校队", "省队"],
}
DISCIPLINE_SIGNALS = {
    "singles": ["单打"],
    "doubles": ["双打", "混双", "男双", "女双", "搭档轮转"],
}
SETUP_SIGNALS = {
    "solo": [
        "一个人练",
        "一个人",
        "单人练",
        "单人",
        "独练",
        "没有陪练",
        "无陪练",
        "自己练",
        "自己",
    ],
    "coach": ["教练喂球", "有教练", "私教"],
    "partner": [
        "有搭档",
        "搭档喂球",
        "有陪练",
        "朋友喂球",
        "有人喂球",
        "帮我喂球",
        "给我喂球",
    ],
}
PAIN_SIGNALS = ["疼", "痛", "受伤", "扭伤", "拉伤", "不适"]


def normalize(text):
    return re.sub(r"\s+", "", text.lower())


def score_text(query, values):
    score = 0
    query_norm = normalize(query)
    for value in values:
        value_norm = normalize(value)
        if not value_norm:
            continue
        if value_norm in query_norm:
            score += 6
        if query_norm and query_norm in value_norm:
            score += 4
        for keyword in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", value_norm):
            for index in range(max(1, len(keyword) - 1)):
                shard = keyword[index : index + 2]
                if shard in query_norm:
                    score += 1
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", value_norm):
            if token in query_norm:
                score += 2
    return score


def detect_intent(query):
    text = normalize(query)
    if any(term in text for term in LEARNING_TERMS):
        return "learning_path"
    if any(term in text for term in NAVIGATION_TERMS):
        return "topic_navigation"
    return "coaching"


def match_topics(graph, query, limit):
    matches = []
    query_norm = normalize(query)
    discipline = infer_signal(query, DISCIPLINE_SIGNALS)
    for category in graph["categories"]:
        category_discipline = category.get("discipline", "general")
        if discipline == "singles" and category_discipline == "doubles":
            continue
        if discipline == "doubles" and category_discipline == "singles":
            continue
        category_score = (
            18 if normalize(category["name"]) in query_norm else 0
        )
        for subtopic in category["subtopics"]:
            if subtopic.get("is_fallback"):
                continue
            reasons = []
            score = category_score
            if category_score:
                reasons.append(category["name"])
            if normalize(subtopic["name"]) in query_norm:
                score += 14
                reasons.append(subtopic["name"])
            for keyword in subtopic["keywords"]:
                if normalize(keyword) in query_norm:
                    score += 8
                    reasons.append(keyword)
            if score <= 0:
                continue
            matches.append(
                {
                    "category": category["name"],
                    "category_description": category["description"],
                    "subtopic": subtopic["name"],
                    "keywords": subtopic["keywords"],
                    "video_count": subtopic["video_count"],
                    "ready_count": subtopic["ready_count"],
                    "score": score,
                    "match_reasons": sorted(set(reasons)),
                    "representative_videos": subtopic["representative_videos"][:3],
                }
            )
    matches.sort(key=lambda item: (-item["score"], -item["video_count"], item["category"], item["subtopic"]))
    return matches[:limit]


def suggested_queries(query, matches):
    queries = []
    for match in matches[:3]:
        topic_terms = " ".join([match["category"], match["subtopic"], *match["keywords"][:3]])
        queries.append(f"{query} {topic_terms}")
    return queries


def infer_signal(query, signal_groups, default="unknown"):
    text = normalize(query)
    matched = [
        name
        for name, signals in signal_groups.items()
        if any(normalize(signal) in text for signal in signals)
    ]
    if len(matched) == 1:
        return matched[0]
    if set(matched) == {"singles", "doubles"}:
        return "both"
    return default


def setup_signal_in_text(text, signal):
    needle = normalize(signal)
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return False
        negated_you = (
            needle.startswith("有")
            and index > 0
            and text[index - 1] in {"没", "无"}
        )
        if not negated_you:
            return True
        start = index + 1


def infer_practice_setup(query):
    text = normalize(query)
    for setup in ["coach", "partner", "solo"]:
        if any(
            setup_signal_in_text(text, signal)
            for signal in SETUP_SIGNALS[setup]
        ):
            return setup
    return "unknown"


def chinese_number(text):
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100}
    if not any(char in units for char in text):
        return int("".join(str(digits[char]) for char in text))
    total = 0
    current = 0
    for char in text:
        if char in digits:
            current = digits[char]
        else:
            total += (current or 1) * units[char]
            current = 0
    return total + current


def infer_session_minutes(query, default):
    text = normalize(query)
    match = re.search(r"(\d{1,3})分钟", text)
    if match:
        return int(match.group(1)), "query"
    chinese_match = re.search(
        r"([零〇一二两三四五六七八九十百]{1,5})分钟", text
    )
    if chinese_match:
        return chinese_number(chinese_match.group(1)), "query"
    if "半小时" in text:
        return 30, "query"
    if "一小时" in text or "1小时" in text:
        return 60, "query"
    return default, "default"


def build_user_context(
    query,
    rules,
    level="auto",
    discipline="auto",
    setup="auto",
    session_minutes=None,
):
    inferred_minutes, minutes_source = infer_session_minutes(
        query, rules["default_session_minutes"]
    )
    inferred_level = infer_signal(query, LEVEL_SIGNALS)
    inferred_discipline = infer_signal(query, DISCIPLINE_SIGNALS)
    inferred_setup = infer_practice_setup(query)
    context = {
        "level": inferred_level if level == "auto" else level,
        "discipline": (
            inferred_discipline if discipline == "auto" else discipline
        ),
        "practice_setup": (
            inferred_setup if setup == "auto" else setup
        ),
        "session_minutes": (
            inferred_minutes if session_minutes is None else session_minutes
        ),
        "handedness": (
            "left" if any(term in normalize(query) for term in ["左手", "左拍"]) else
            "right" if any(term in normalize(query) for term in ["右手", "右拍"]) else
            "unknown"
        ),
        "pain_or_injury": any(
            normalize(signal) in normalize(query) for signal in PAIN_SIGNALS
        ),
        "sources": {
            "level": (
                "argument"
                if level != "auto"
                else "query"
                if inferred_level != "unknown"
                else "default"
            ),
            "discipline": (
                "argument"
                if discipline != "auto"
                else "query"
                if inferred_discipline != "unknown"
                else "default"
            ),
            "practice_setup": (
                "argument"
                if setup != "auto"
                else "query"
                if inferred_setup != "unknown"
                else "default"
            ),
            "session_minutes": minutes_source if session_minutes is None else "argument",
        },
    }
    minimum, maximum = rules["session_minutes_range"]
    if not minimum <= context["session_minutes"] <= maximum:
        raise ValueError(
            f"session minutes must be between {minimum} and {maximum}"
        )
    return context


def allocate_minutes(total):
    labels = ["warm_up", "isolated_cue", "pressure_or_decision", "self_check"]
    weights = [0.2, 0.4, 0.3, 0.1]
    minutes = [1, 1, 1, 1]
    remaining = total - sum(minutes)
    raw = [remaining * weight for weight in weights]
    additions = [int(value) for value in raw]
    minutes = [base + addition for base, addition in zip(minutes, additions)]
    for index in sorted(
        range(len(raw)),
        key=lambda item: raw[item] - additions[item],
        reverse=True,
    )[: total - sum(minutes)]:
        minutes[index] += 1
    return dict(zip(labels, minutes))


def practice_adaptation(context, rules):
    return {
        "session_minutes": context["session_minutes"],
        "minute_allocation": allocate_minutes(context["session_minutes"]),
        "level_focus": rules["levels"][context["level"]],
        "setup_adaptation": rules["practice_setups"][context["practice_setup"]],
        "discipline_boundary": rules["discipline_boundaries"][context["discipline"]],
        "quality_stop_rules": rules["quality_stop_rules"],
        "pain_boundary": (
            "问题包含疼痛或受伤信号：停止相关动作，先由合格医疗专业人士评估；本路径不作诊断。"
            if context["pain_or_injury"]
            else None
        ),
    }


def clarification_questions(context):
    questions = []
    if context["pain_or_injury"]:
        questions.append("疼痛或受伤是否已经由合格医疗专业人士评估，并允许继续训练？")
    if context["discipline"] == "unknown":
        questions.append("这套内容主要用于单打、双打，还是两者都要？")
    if context["practice_setup"] == "unknown":
        questions.append("练习时是独练，还是有搭档、陪练或教练稳定喂球？")
    if context["level"] == "unknown":
        questions.append("你目前是刚入门、有稳定基础，还是已经能在对抗中使用这个动作？")
    return questions[:2]


def learning_path(matches, context, rules):
    if not matches:
        return []
    primary = matches[0]
    reps = primary["representative_videos"]
    level_rule = rules["levels"][context["level"]]
    setup_rule = rules["practice_setups"][context["practice_setup"]]
    discipline_rule = rules["discipline_boundaries"][context["discipline"]]
    return [
        {
            "stage": "基础定位",
            "goal": f"先确认问题属于「{primary['category']} / {primary['subtopic']}」的哪个场景。",
            "evidence_leads": reps[:1],
        },
        {
            "stage": "动作原则",
            "goal": f"用最强的一到两个证据视频提炼动作原则；当前水平重点：{level_rule['focus']}。",
            "evidence_leads": reps[:2],
        },
        {
            "stage": "单点练习",
            "goal": f"把原则拆成一个可观察 cue，按 {context['session_minutes']} 分钟单次练习分配执行。训练条件：{setup_rule}。",
            "evidence_leads": reps[:2],
        },
        {
            "stage": "对抗迁移",
            "goal": f"按“{level_rule['pressure']}”增加压力，只保留一个自测标准。项目边界：{discipline_rule}。",
            "evidence_leads": reps[:3],
        },
    ]


def main():
    parser = argparse.ArgumentParser(description="Navigate the Liu Hui badminton topic map.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--level",
        choices=["auto", "beginner", "intermediate", "advanced", "unknown"],
        default="auto",
    )
    parser.add_argument(
        "--discipline",
        choices=["auto", "singles", "doubles", "both", "unknown"],
        default="auto",
    )
    parser.add_argument(
        "--practice-setup",
        choices=["auto", "solo", "partner", "coach", "unknown"],
        default="auto",
    )
    parser.add_argument("--session-minutes", type=int)
    args = parser.parse_args()

    if not args.query.strip():
        raise SystemExit("query cannot be empty")
    if not 1 <= args.limit <= 20:
        raise SystemExit("--limit must be between 1 and 20")

    graph = json.loads(TOPIC_MAP.read_text(encoding="utf-8"))
    practice_rules = json.loads(PRACTICE_RULES.read_text(encoding="utf-8"))
    try:
        context = build_user_context(
            args.query,
            practice_rules,
            level=args.level,
            discipline=args.discipline,
            setup=args.practice_setup,
            session_minutes=args.session_minutes,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    matches = match_topics(graph, args.query, args.limit)
    payload = {
        "query": args.query,
        "intent": detect_intent(args.query),
        "user_context": context,
        "context_assumptions": [
            field
            for field, source in context["sources"].items()
            if source == "default"
        ],
        "material_clarification_questions": clarification_questions(context),
        "source": str(TOPIC_MAP.relative_to(ROOT)),
        "matches": matches,
        "suggested_search_queries": suggested_queries(args.query, matches),
        "learning_path": learning_path(matches, context, practice_rules),
        "practice_adaptation": practice_adaptation(context, practice_rules),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
