#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data" / "evaluation" / "acceptance_questions.json"
SEARCH = ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "search_knowledge.py"
NAVIGATE = ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "navigate_topics.py"
KNOWLEDGE = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
REPORT = ROOT / "output" / "skill_acceptance_review.md"


ANSWER_SECTIONS = {
    "diagnosis": ["诊断", "刘辉相关原则", "纠正提示", "练习方法", "证据来源", "置信边界"],
    "learning_path": ["主题定位", "学习顺序", "每阶段目标", "代表证据", "下一步检索词", "边界"],
    "topic_navigation": ["主题定位", "学习顺序", "每阶段目标", "代表证据", "下一步检索词", "边界"],
    "practice_plan": ["今日 15 分钟", "3 天修正", "2 周巩固", "自测标准", "常见错误", "暂停或复核信号", "来源证据"],
    "boundary": ["边界说明", "安全替代", "证据边界"],
}


def run_json(command):
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def load_knowledge():
    data = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    return {video["video_id"]: video for video in data["videos"]}


def evaluate_case(case, knowledge):
    search_payload = run_json(["python3", str(SEARCH), case["query"], "--limit", "5"])
    results = search_payload["results"]
    ids = [item["video_id"] for item in results]
    top_ids = ids[:3]
    expected = case.get("expected_any", [])
    retrieval_pass = True if not expected else any(video_id in top_ids for video_id in expected)
    no_non_teaching = all(
        knowledge[video_id]["processing_status"] not in {"not_teaching", "low_value"}
        for video_id in ids
    )
    visual_review_pass = True
    if case.get("requires_visual_reviewed"):
        visual_review_pass = any(
            knowledge[video_id]["confidence"] == "visual_reviewed"
            for video_id in top_ids
            if video_id in knowledge
        )

    navigation_payload = None
    navigation_pass = True
    if case["type"] in {"learning_path", "topic_navigation"}:
        navigation_payload = run_json(["python3", str(NAVIGATE), case["query"], "--limit", "5"])
        navigation_text = json.dumps(navigation_payload, ensure_ascii=False)
        navigation_pass = bool(navigation_payload["matches"]) and all(
            marker in navigation_text for marker in case.get("expected_navigation", [])
        )

    passed = retrieval_pass and no_non_teaching and visual_review_pass and navigation_pass
    return {
        **case,
        "retrieved_ids": ids,
        "top_titles": [item["title"] for item in results[:3]],
        "retrieval_pass": retrieval_pass,
        "no_non_teaching": no_non_teaching,
        "visual_review_pass": visual_review_pass,
        "navigation_intent": navigation_payload["intent"] if navigation_payload else None,
        "navigation_matches": [
            f"{item['category']} / {item['subtopic']}"
            for item in (navigation_payload or {}).get("matches", [])[:5]
        ],
        "navigation_pass": navigation_pass,
        "required_sections": ANSWER_SECTIONS[case["type"]],
        "passed": passed,
    }


def render(results):
    summary = {
        "total": len(results),
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "diagnosis": sum(item["type"] == "diagnosis" for item in results),
        "learning_path": sum(item["type"] == "learning_path" for item in results),
        "topic_navigation": sum(item["type"] == "topic_navigation" for item in results),
        "practice_plan": sum(item["type"] == "practice_plan" for item in results),
        "boundary": sum(item["type"] == "boundary" for item in results),
    }
    lines = [
        "# Skill Acceptance Review",
        "",
        "This report checks real-world prompts against retrieval, topic navigation, evidence filtering, and the answer shape expected from the skill.",
        "",
        "## Summary",
        "",
        f"- Total cases: `{summary['total']}`",
        f"- Passed: `{summary['passed']}`",
        f"- Failed: `{summary['failed']}`",
        f"- Diagnosis cases: `{summary['diagnosis']}`",
        f"- Learning-path cases: `{summary['learning_path']}`",
        f"- Topic-navigation cases: `{summary['topic_navigation']}`",
        f"- Practice-plan cases: `{summary['practice_plan']}`",
        f"- Boundary cases: `{summary['boundary']}`",
        "",
        "## Cases",
        "",
    ]
    for item in results:
        status = "PASS" if item["passed"] else "FAIL"
        lines.extend(
            [
                f"### {item['id']} [{status}]",
                "",
                f"- Type: `{item['type']}`",
                f"- Query: {item['query']}",
                f"- Retrieved IDs: {', '.join(item['retrieved_ids']) if item['retrieved_ids'] else 'none'}",
                f"- Top titles: {' / '.join(item['top_titles']) if item['top_titles'] else 'none'}",
                f"- Navigation intent: {item['navigation_intent'] or 'n/a'}",
                f"- Navigation matches: {', '.join(item['navigation_matches']) if item['navigation_matches'] else 'n/a'}",
                f"- Retrieval pass: `{item['retrieval_pass']}`",
                f"- No non-teaching evidence: `{item['no_non_teaching']}`",
                f"- Visual-review pass: `{item['visual_review_pass']}`",
                f"- Navigation pass: `{item['navigation_pass']}`",
                f"- Required answer sections: {', '.join(item['required_sections'])}",
                f"- Answer focus: {', '.join(item['answer_focus'])}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n", summary


def main():
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    knowledge = load_knowledge()
    results = [evaluate_case(case, knowledge) for case in cases]
    report, summary = render(results)
    REPORT.write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed"]:
        for item in results:
            if not item["passed"]:
                print(f"FAIL {item['id']}: {item['retrieved_ids']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
