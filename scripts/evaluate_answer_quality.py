#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "data" / "evaluation" / "golden_questions.json"
SEARCH = ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "search_knowledge.py"
NAVIGATE = ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "navigate_topics.py"
REPORT = ROOT / "output" / "golden_answer_review.md"


ANSWER_CONTRACT_SECTIONS = [
    "诊断",
    "刘辉相关原则",
    "纠正提示",
    "练习方法",
    "证据来源",
    "置信边界",
]
PRACTICE_PLAN_SECTIONS = [
    "今日 15 分钟",
    "3 天修正",
    "2 周巩固",
    "自测标准",
    "常见错误",
    "暂停或复核信号",
    "来源证据",
]
TOPIC_NAVIGATION_SECTIONS = [
    "主题定位",
    "学习顺序",
    "每阶段目标",
    "代表证据",
    "下一步检索词",
    "边界",
]


def run_search(query, limit=5):
    completed = subprocess.run(
        ["python3", str(SEARCH), query, "--limit", str(limit)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def run_navigation(query, limit=5):
    completed = subprocess.run(
        ["python3", str(NAVIGATE), query, "--limit", str(limit)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def load_knowledge():
    data = json.loads(
        (ROOT / "data" / "knowledge" / "douyin_knowledge_base.json").read_text(
            encoding="utf-8"
        )
    )
    return {video["video_id"]: video for video in data["videos"]}


def has_evidence(video):
    note = video.get("teaching_note") or {}
    for key in [
        "principles",
        "training_cues",
        "key_evidence",
        "error_evidence",
        "action_cues",
        "visual_review_evidence",
    ]:
        if note.get(key):
            return True
    return False


def evaluate_case(case, knowledge):
    payload = run_search(case["query"])
    results = payload["results"]
    ids = [item["video_id"] for item in results]
    top_ids = ids[:3]
    expected = case.get("expected_any") or []
    navigation_payload = None

    retrieval_pass = True
    if expected:
        retrieval_pass = any(video_id in top_ids for video_id in expected)

    no_non_teaching = all(
        knowledge[video_id]["processing_status"] not in {"not_teaching", "low_value"}
        for video_id in ids
    )
    evidence_ready = all(has_evidence(knowledge[video_id]) for video_id in top_ids if video_id in knowledge)

    visual_review_pass = True
    if case.get("requires_visual_reviewed"):
        visual_review_pass = any(
            knowledge[video_id]["confidence"] == "visual_reviewed"
            for video_id in top_ids
            if video_id in knowledge
        )

    topic_navigation_pass = True
    learning_path_pass = True
    if case.get("requires_topic_navigation"):
        navigation_payload = run_navigation(case["query"])
        nav_text = json.dumps(navigation_payload, ensure_ascii=False)
        topic_navigation_pass = bool(navigation_payload["matches"]) and all(
            expected_topic in nav_text for expected_topic in case.get("expected_topics", [])
        )
        if case.get("requires_learning_path"):
            learning_path_pass = (
                navigation_payload["intent"] == "learning_path"
                and len(navigation_payload["learning_path"]) >= 3
                and bool(navigation_payload["suggested_search_queries"])
            )

    if case.get("requires_safety_rule"):
        answer_requirements = ["安全边界", "不冒充本人"]
    elif case.get("requires_practice_plan"):
        answer_requirements = PRACTICE_PLAN_SECTIONS
    elif case.get("requires_topic_navigation"):
        answer_requirements = TOPIC_NAVIGATION_SECTIONS
    else:
        answer_requirements = ANSWER_CONTRACT_SECTIONS

    passed = (
        retrieval_pass
        and no_non_teaching
        and evidence_ready
        and visual_review_pass
        and topic_navigation_pass
        and learning_path_pass
    )
    return {
        **case,
        "retrieved_ids": ids,
        "top_titles": [item["title"] for item in results[:3]],
        "navigation_intent": navigation_payload["intent"] if navigation_payload else None,
        "navigation_matches": [
            f"{item['category']} / {item['subtopic']}"
            for item in (navigation_payload or {}).get("matches", [])[:3]
        ],
        "retrieval_pass": retrieval_pass,
        "no_non_teaching": no_non_teaching,
        "evidence_ready": evidence_ready,
        "visual_review_pass": visual_review_pass,
        "topic_navigation_pass": topic_navigation_pass,
        "learning_path_pass": learning_path_pass,
        "answer_requirements": answer_requirements,
        "pass": passed,
    }


def render_report(summary, results):
    lines = [
        "# Golden Answer Review",
        "",
        "This report checks golden coaching questions against retrieval, evidence readiness, visual-review handling, and expected answer structure.",
        "",
        "## Summary",
        "",
        f"- Total cases: `{summary['total']}`",
        f"- Passed: `{summary['passed']}`",
        f"- Failed: `{summary['failed']}`",
        f"- Practice-plan cases: `{summary['practice_plan_cases']}`",
        f"- Safety/boundary cases: `{summary['safety_cases']}`",
        f"- Topic-navigation cases: `{summary['topic_navigation_cases']}`",
        f"- Learning-path cases: `{summary['learning_path_cases']}`",
        "",
        "## Cases",
        "",
    ]
    for item in results:
        status = "PASS" if item["pass"] else "FAIL"
        lines.extend(
            [
                f"### {item['id']} [{status}]",
                "",
                f"- Query: {item['query']}",
                f"- Retrieved IDs: {', '.join(item['retrieved_ids']) if item['retrieved_ids'] else 'none'}",
                f"- Top titles: {' / '.join(item['top_titles']) if item['top_titles'] else 'none'}",
                f"- Navigation intent: {item['navigation_intent'] or 'n/a'}",
                f"- Navigation matches: {', '.join(item['navigation_matches']) if item['navigation_matches'] else 'n/a'}",
                f"- Retrieval pass: `{item['retrieval_pass']}`",
                f"- No non-teaching evidence: `{item['no_non_teaching']}`",
                f"- Evidence ready: `{item['evidence_ready']}`",
                f"- Visual review pass: `{item['visual_review_pass']}`",
                f"- Topic navigation pass: `{item['topic_navigation_pass']}`",
                f"- Learning path pass: `{item['learning_path_pass']}`",
                f"- Answer requirements: {', '.join(item['answer_requirements'])}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    knowledge = load_knowledge()
    results = [evaluate_case(case, knowledge) for case in golden["cases"]]
    summary = {
        "total": len(results),
        "passed": sum(item["pass"] for item in results),
        "failed": sum(not item["pass"] for item in results),
        "practice_plan_cases": sum(item.get("requires_practice_plan", False) for item in results),
        "safety_cases": sum(bool(item.get("requires_safety_rule")) for item in results),
        "topic_navigation_cases": sum(
            bool(item.get("requires_topic_navigation")) for item in results
        ),
        "learning_path_cases": sum(bool(item.get("requires_learning_path")) for item in results),
    }
    REPORT.write_text(render_report(summary, results), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed"]:
        for item in results:
            if not item["pass"]:
                print(f"FAIL {item['id']}: {item['retrieved_ids']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
