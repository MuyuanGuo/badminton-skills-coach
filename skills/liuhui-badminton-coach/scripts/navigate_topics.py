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
PAIN_SIGNALS = ["疼", "痛", "受伤", "扭伤", "拉伤", "不适", "不舒服"]


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


def build_user_context(
    query,
    rules=None,
    level="auto",
    discipline="auto",
    setup="auto",
):
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
        },
    }
    return context


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


def learning_path(matches, context, rules=None):
    """Return evidence-navigation stages, never a synthetic training plan."""

    if not matches:
        return []
    primary = matches[0]
    reps = primary["representative_videos"]
    discipline = context.get("discipline", "unknown")
    discipline_boundary = {
        "singles": "只在单打约束内核对站位、回位和线路结论",
        "doubles": "只在双打约束内核对搭档职责、站位和线路结论",
        "both": "分别核对单双打证据，不能把一方规则直接迁移到另一方",
        "unknown": "需要站位或战术结论时，先区分单打与双打证据",
    }[discipline]
    return [
        {
            "stage": "主题定位",
            "goal": f"把问题定位到「{primary['category']} / {primary['subtopic']}」，并保留用户原始场景。",
            "evidence_leads": reps[:1],
        },
        {
            "stage": "证据拆分",
            "goal": "分别检索动作机制、可观察错误和适用条件；每个结论只使用直接覆盖它的来源。",
            "evidence_leads": reps[:2],
        },
        {
            "stage": "场景边界",
            "goal": discipline_boundary + "。",
            "evidence_leads": reps[:2],
        },
        {
            "stage": "答案取舍",
            "goal": "只展示实际参与最终回答的视频，并逐条说明引用原因、观看价值和观看重点。",
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
        "training_boundary": {
            "mode": practice_rules["mode"],
            "statement": practice_rules["training_boundary_statement"],
            "synthetic_fields_forbidden": practice_rules[
                "synthetic_fields_forbidden"
            ],
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
