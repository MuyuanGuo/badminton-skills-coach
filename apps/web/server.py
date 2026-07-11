#!/usr/bin/env python3
import argparse
import json
import mimetypes
import os
import subprocess
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
SEARCH = ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "search_knowledge.py"
NAVIGATE = ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "navigate_topics.py"

ANSWER_SECTIONS = {
    "diagnosis": ["诊断", "刘辉相关原则", "纠正提示", "练习方法", "证据来源", "置信边界"],
    "learning_path": ["主题定位", "学习顺序", "每阶段目标", "代表证据", "下一步检索词", "边界"],
    "topic_navigation": ["主题定位", "学习顺序", "每阶段目标", "代表证据", "下一步检索词", "边界"],
    "practice_plan": ["今日 15 分钟", "3 天修正", "2 周巩固", "自测标准", "常见错误", "暂停或复核信号", "来源证据"],
    "boundary": ["边界说明", "安全替代", "证据边界"],
}

LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_RESPONSES_URL = os.getenv("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")


def run_json(command):
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def llm_available():
    return bool(os.getenv("OPENAI_API_KEY"))


def infer_mode(query, requested_mode):
    if requested_mode and requested_mode != "auto":
        return requested_mode
    text = query.replace(" ", "")
    if any(term in text for term in ["疼", "痛", "受伤", "膝盖", "肩", "腰"]):
        return "boundary"
    if any(term in text for term in ["系统学", "学习路径", "顺序", "路线", "怎么学"]):
        return "learning_path"
    if any(term in text for term in ["知识图谱", "主题", "结构", "哪几块", "分哪", "模块"]):
        return "topic_navigation"
    if any(term in text for term in ["计划", "三天", "两周", "练习"]):
        return "practice_plan"
    return "diagnosis"


def evidence_from(video):
    note = video.get("teaching_note") or {}
    items = []
    for key in ["principles", "key_evidence", "visual_review_evidence"]:
        for item in note.get(key) or []:
            if isinstance(item, dict):
                timestamp = item.get("timestamp") or "未标注"
                text = item.get("text") or ""
            else:
                timestamp = "未标注"
                text = str(item)
            if text:
                items.append({"timestamp": timestamp, "text": text})
    if not items and note.get("problem"):
        items.append({"timestamp": "未标注", "text": note["problem"]})
    return items[:3]


def compact_source(video):
    return {
        "video_id": video["video_id"],
        "title": video["title"],
        "url": video["url"],
        "category": video["category"],
        "confidence": video["confidence"],
        "score": video["score"],
        "evidence": evidence_from(video),
    }


def strongest_text(sources, field):
    for source in sources:
        note = source.get("teaching_note") or {}
        value = note.get(field)
        if isinstance(value, list) and value:
            return value
        if isinstance(value, str) and value:
            return [value]
    return []


def build_diagnosis(query, sources):
    first = sources[0] if sources else {}
    note = first.get("teaching_note") or {}
    principles = strongest_text(sources, "principles")
    cues = strongest_text(sources, "training_cues") or strongest_text(sources, "action_cues")
    errors = strongest_text(sources, "common_errors") or strongest_text(sources, "error_evidence")
    diagnosis = note.get("problem") or note.get("topic") or "需要结合来球场景、击球点和动作目标判断。"
    return {
        "诊断": diagnosis,
        "刘辉相关原则": [item["text"] if isinstance(item, dict) else str(item) for item in principles[:3]],
        "纠正提示": [str(item) for item in cues[:3]],
        "练习方法": [
            "用低压力来球重复 10 分钟，只保留一个动作 cue。",
            "每 5 球自查一次：击球点、拍面和下一拍衔接是否稳定。",
        ],
        "证据来源": [compact_source(item) for item in sources[:3]],
        "置信边界": "这是基于已索引教学证据的判断；如果要判断你的个人动作，需要正侧面视频复核。",
        "常见错误": [str(item) for item in errors[:4]],
    }


def build_learning_path(navigation, sources):
    matches = navigation.get("matches", [])
    primary = matches[0] if matches else {}
    return {
        "主题定位": f"{primary.get('category', '未匹配')} / {primary.get('subtopic', '未匹配')}",
        "学习顺序": navigation.get("learning_path", []),
        "每阶段目标": [item.get("goal") for item in navigation.get("learning_path", []) if item.get("goal")],
        "代表证据": [compact_source(item) for item in sources[:3]],
        "下一步检索词": navigation.get("suggested_search_queries", [])[:3],
        "边界": "主题图谱用于确定学习分支；具体动作建议仍以检索到的视频证据为准。",
    }


def build_practice_plan(query, sources):
    diagnosis = build_diagnosis(query, sources)
    return {
        "今日 15 分钟": [
            "3 分钟热身和空拍，确认无疼痛。",
            "6 分钟单点 cue 练习，只改一个问题。",
            "4 分钟加入轻微移动或来球压力。",
            "2 分钟记录成功标准。"
        ],
        "3 天修正": [
            "第 1 天：只做动作定位和慢速稳定。",
            "第 2 天：加入连续来球，保持同一 cue。",
            "第 3 天：加入轻对抗，观察动作是否变形。"
        ],
        "2 周巩固": [
            "第 1 周控制速度，优先稳定。",
            "第 2 周加入线路、节奏和对抗压力。"
        ],
        "自测标准": "连续 10 球中至少 7 球达到目标落点或动作标准，且没有失衡和疼痛。",
        "常见错误": diagnosis.get("常见错误", [])[:4],
        "暂停或复核信号": "出现疼痛、反复失衡、动作越练越僵时暂停，并用视频复核。",
        "来源证据": diagnosis["证据来源"],
    }


def build_boundary(query, sources):
    if any(term in query for term in ["疼", "痛", "受伤", "膝盖", "肩", "腰"]):
        return {
            "边界说明": "不要把疼痛问题当作普通技术问题处理；这里不能提供医疗诊断。",
            "安全替代": "暂停诱发疼痛的动作，改做无痛范围内的轻量技术复盘或上肢空拍，并咨询医生或物理治疗师。",
            "证据边界": "羽毛球教学证据可用于动作原则，不足以判断你的损伤风险。",
            "证据来源": [compact_source(item) for item in sources[:2]],
        }
    return {
        "边界说明": "不能冒充刘辉本人，也不能暗示这些回答获得本人官方背书。",
        "安全替代": "可以用教练式、直接但不冒充身份的方式给出动作提醒。",
        "证据边界": "回答只代表基于已索引公开教学内容的整理。",
        "证据来源": [compact_source(item) for item in sources[:2]],
    }


def source_for_prompt(source):
    return {
        "video_id": source.get("video_id"),
        "title": source.get("title"),
        "url": source.get("url"),
        "category": source.get("category"),
        "confidence": source.get("confidence"),
        "score": source.get("score"),
        "teaching_note": source.get("teaching_note"),
    }


def parse_response_text(payload):
    if payload.get("output_text"):
        return payload["output_text"]
    chunks = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def synthesize_with_llm(query, answer_mode, template_answer, sources, navigation):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    prompt_payload = {
        "query": query,
        "mode": answer_mode,
        "required_sections": ANSWER_SECTIONS[answer_mode],
        "template_answer": template_answer,
        "navigation": navigation,
        "sources": [source_for_prompt(item) for item in sources[:5]],
    }
    system_prompt = (
        "你是一个羽毛球技术问答助手。必须基于给定证据回答，不能冒充刘辉本人，"
        "不能暗示官方授权或背书。回答使用简洁中文，按 required_sections 的顺序组织。"
        "每个证据支持的要点都要引用视频标题、时间戳或说明人工视觉复核、URL。"
        "如果证据不足，明确说明边界。疼痛或伤病问题不能医疗诊断，应建议暂停疼痛动作并咨询专业人士。"
    )
    request_payload = {
        "model": LLM_MODEL,
        "input": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "请根据以下 JSON 生成最终网页回答：\n"
                + json.dumps(prompt_payload, ensure_ascii=False, indent=2),
            },
        ],
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {error.code}: {detail}") from error
    text = parse_response_text(payload)
    if not text:
        raise RuntimeError("OpenAI API returned no answer text")
    return text


def answer_query(query, mode):
    answer_mode = infer_mode(query, mode)
    navigation = None
    if answer_mode in {"learning_path", "topic_navigation"}:
        navigation = run_json(["python3", str(NAVIGATE), query, "--limit", "5"])
        search_query = " ".join([query, *(navigation.get("suggested_search_queries") or [])[:1]])
    else:
        search_query = query
    search = run_json(["python3", str(SEARCH), search_query, "--limit", "5"])
    sources = search.get("results", [])

    if answer_mode == "learning_path" or answer_mode == "topic_navigation":
        answer = build_learning_path(navigation or {}, sources)
    elif answer_mode == "practice_plan":
        answer = build_practice_plan(query, sources)
    elif answer_mode == "boundary":
        answer = build_boundary(query, sources)
    else:
        answer = build_diagnosis(query, sources)

    answer_text = None
    generator = "template"
    llm_error = None
    try:
        answer_text = synthesize_with_llm(query, answer_mode, answer, sources, navigation)
        if answer_text:
            generator = "llm"
    except Exception as error:
        llm_error = str(error)

    return {
        "query": query,
        "mode": answer_mode,
        "generator": generator,
        "sections": ANSWER_SECTIONS[answer_mode],
        "answer_text": answer_text,
        "answer": answer,
        "navigation": navigation,
        "search": {
            "terms": search.get("terms", []),
            "results": [compact_source(item) for item in sources],
        },
        "llm": {
            "available": llm_available(),
            "model": LLM_MODEL if llm_available() else None,
            "error": llm_error,
        },
        "disclaimer": "非刘辉本人，不代表本人或机构官方背书；回答基于当前索引的公开教学知识库。",
    }


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.serve_static(send_body=True)

    def do_HEAD(self):
        self.serve_static(send_body=False)

    def serve_static(self, send_body):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json({"ok": True, "llm_available": llm_available()})
            return
        relative = "index.html" if path in {"/", ""} else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists():
            self.send_error(404)
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type = f"{content_type}; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if send_body:
            self.wfile.write(content)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/ask":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            query = str(payload.get("query", "")).strip()
            mode = str(payload.get("mode", "auto")).strip() or "auto"
            if not query:
                self.send_json({"error": "query is required"}, status=400)
                return
            self.send_json(answer_query(query, mode))
        except subprocess.CalledProcessError as error:
            self.send_json({"error": "backend command failed", "detail": error.stderr}, status=500)
        except Exception as error:
            self.send_json({"error": str(error)}, status=500)

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving Liu Hui badminton web MVP at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
