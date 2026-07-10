#!/usr/bin/env python3
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOPIC_INDEX = ROOT / "data" / "knowledge" / "topic_index.json"
KNOWLEDGE_BASE = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
OUTPUT_DIR = ROOT / "output"
DRAWIO_OUTPUT = OUTPUT_DIR / "liuhui-full-knowledge-map.drawio"
MERMAID_OUTPUT = OUTPUT_DIR / "liuhui-knowledge-map.mmd"
HTML_OUTPUT = OUTPUT_DIR / "liuhui-knowledge-map.html"
SUMMARY_OUTPUT = ROOT / "data" / "knowledge" / "knowledge_graph_summary.json"


def shorten(text, length=48):
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= length else text[: length - 1] + "…"


def node_id(prefix, value):
    slug = re.sub(r"[^0-9A-Za-z]+", "-", value).strip("-").lower()
    if not slug:
        slug = str(abs(hash(value)))
    return f"{prefix}-{slug[:40]}"


def load_graph():
    index = json.loads(TOPIC_INDEX.read_text(encoding="utf-8"))
    knowledge = json.loads(KNOWLEDGE_BASE.read_text(encoding="utf-8"))
    video_lookup = {video["video_id"]: video for video in knowledge["videos"]}
    categories = []
    for category in index["categories"]:
        subtopics = []
        for subtopic in category["subtopics"]:
            reps = []
            for video in subtopic["representative_videos"][:3]:
                source_video = video_lookup.get(video["video_id"], {})
                reps.append(
                    {
                        "video_id": video["video_id"],
                        "title": shorten(video["title"], 54),
                        "url": video["url"],
                        "confidence": video["confidence"],
                        "category": video["category"],
                        "duration_seconds": source_video.get("duration_seconds"),
                        "score": video["score"],
                    }
                )
            subtopics.append(
                {
                    "name": subtopic["name"],
                    "keywords": subtopic["keywords"],
                    "video_count": subtopic["video_count"],
                    "ready_count": subtopic["ready_count"],
                    "representative_videos": reps,
                }
            )
        categories.append(
            {
                "name": category["name"],
                "description": category["description"],
                "video_count": category["video_count"],
                "subtopics": subtopics,
            }
        )
    return {
        "version": "knowledge-graph-v1",
        "source": str(TOPIC_INDEX.relative_to(ROOT)),
        "scope": index["scope"],
        "source_updated_at": index["source_updated_at"],
        "video_count": index["video_count"],
        "indexable_video_count": index["indexable_video_count"],
        "assigned_video_count": index["assigned_video_count"],
        "multi_topic_video_count": index["multi_topic_video_count"],
        "categories": categories,
    }


def add_vertex(root, cell_id, label, x, y, width, height, style, link=None):
    attrs = {
        "id": cell_id,
        "value": label,
        "style": style,
        "vertex": "1",
        "parent": "1",
    }
    if link:
        attrs["link"] = link
    cell = ET.SubElement(root, "mxCell", **attrs)
    ET.SubElement(
        cell,
        "mxGeometry",
        x=str(x),
        y=str(y),
        width=str(width),
        height=str(height),
        **{"as": "geometry"},
    )


def add_edge(root, cell_id, source, target):
    cell = ET.SubElement(
        root,
        "mxCell",
        id=cell_id,
        style=(
            "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;"
            "jettySize=auto;html=1;strokeColor=#7A8A86;strokeWidth=2;"
        ),
        edge="1",
        parent="1",
        source=source,
        target=target,
    )
    ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})


def build_drawio(graph):
    diagram_file = ET.Element(
        "mxfile",
        host="app.diagrams.net",
        modified="2026-07-10T00:00:00.000Z",
        agent="Codex",
        version="24.7.17",
    )
    diagram = ET.SubElement(diagram_file, "diagram", id="liuhui-full", name="全量教学知识图谱")
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        dx="2400",
        dy="2600",
        grid="1",
        gridSize="10",
        guides="1",
        tooltips="1",
        connect="1",
        arrows="1",
        fold="1",
        page="1",
        pageScale="1",
        pageWidth="3200",
        pageHeight="2600",
        math="0",
        shadow="0",
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    add_vertex(
        root,
        "skill",
        (
            "刘辉羽毛球 Skill<br>"
            f"<b>{graph['indexable_video_count']} 条教学证据</b><br>"
            f"{len(graph['categories'])} 个主题大类 · {graph['assigned_video_count']} 条已入主题索引"
        ),
        1360,
        80,
        440,
        120,
        (
            "rounded=1;whiteSpace=wrap;html=1;fillColor=#123B36;fontColor=#FFFFFF;"
            "strokeColor=#0C2B27;strokeWidth=3;fontSize=18;fontStyle=1;arcSize=8;"
        ),
    )

    palette = [
        ("#DCEFEA", "#176B5B"),
        ("#F7E6DE", "#B85C38"),
        ("#E7EDF5", "#456A8A"),
        ("#F3EBCF", "#967326"),
        ("#E9E3F2", "#72578C"),
        ("#E2ECE4", "#4F7A43"),
        ("#F1E4E8", "#9A5968"),
        ("#E4EDF0", "#51727B"),
    ]
    edge_index = 1
    for category_index, category in enumerate(graph["categories"]):
        fill, stroke = palette[category_index % len(palette)]
        x = 60 + (category_index % 4) * 770
        y = 320 + (category_index // 4) * 1040
        category_id = f"category-{category_index}"
        add_vertex(
            root,
            category_id,
            f"<b>{html.escape(category['name'])}</b><br>{category['video_count']} 条 · {html.escape(category['description'])}",
            x,
            y,
            620,
            86,
            (
                f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
                "strokeWidth=2;fontSize=15;fontStyle=1;arcSize=6;"
            ),
        )
        add_edge(root, f"edge-{edge_index}", "skill", category_id)
        edge_index += 1

        for subtopic_index, subtopic in enumerate(category["subtopics"]):
            subtopic_id = f"subtopic-{category_index}-{subtopic_index}"
            sy = y + 135 + subtopic_index * 165
            add_vertex(
                root,
                subtopic_id,
                (
                    f"<b>{html.escape(subtopic['name'])}</b><br>"
                    f"{subtopic['video_count']} 条 · 关键词：{html.escape('、'.join(subtopic['keywords'][:4]))}"
                ),
                x,
                sy,
                300,
                82,
                (
                    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#AAB8B4;"
                    "strokeWidth=1.5;fontSize=12;align=left;spacingLeft=10;arcSize=5;"
                ),
            )
            add_edge(root, f"edge-{edge_index}", category_id, subtopic_id)
            edge_index += 1
            reps = subtopic["representative_videos"][:2]
            for video_index, video in enumerate(reps):
                video_id = f"video-{category_index}-{subtopic_index}-{video_index}"
                add_vertex(
                    root,
                    video_id,
                    (
                        f"{html.escape(video['title'])}<br>"
                        f"<font color='#52625E'>{video['confidence']} · score {video['score']}</font>"
                    ),
                    x + 330,
                    sy + video_index * 78 - 4,
                    290,
                    68,
                    (
                        "rounded=1;whiteSpace=wrap;html=1;fillColor=#F9FBFA;strokeColor=#CBD6D2;"
                        "strokeWidth=1;fontSize=11;align=left;spacingLeft=8;arcSize=5;"
                    ),
                    video["url"],
                )
                add_edge(root, f"edge-{edge_index}", subtopic_id, video_id)
                edge_index += 1

    ET.ElementTree(diagram_file).write(DRAWIO_OUTPUT, encoding="utf-8", xml_declaration=True)


def mermaid_label(text):
    return str(text).replace('"', "'")


def build_mermaid(graph):
    lines = [
        "flowchart LR",
        f'  root["刘辉羽毛球 Skill<br/>{graph["indexable_video_count"]} 条教学证据"]',
    ]
    for category_index, category in enumerate(graph["categories"]):
        category_id = f"c{category_index}"
        lines.append(f'  {category_id}["{mermaid_label(category["name"])}<br/>{category["video_count"]} 条"]')
        lines.append(f"  root --> {category_id}")
        for subtopic_index, subtopic in enumerate(category["subtopics"]):
            subtopic_id = f"s{category_index}_{subtopic_index}"
            lines.append(
                f'  {subtopic_id}["{mermaid_label(subtopic["name"])}<br/>{subtopic["video_count"]} 条"]'
            )
            lines.append(f"  {category_id} --> {subtopic_id}")
            if subtopic["representative_videos"]:
                video = subtopic["representative_videos"][0]
                video_id = f"v{category_index}_{subtopic_index}"
                lines.append(f'  {video_id}["{mermaid_label(shorten(video["title"], 28))}"]')
                lines.append(f"  {subtopic_id} -.代表视频.-> {video_id}")
    MERMAID_OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_html(graph):
    payload = json.dumps(graph, ensure_ascii=False)
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>刘辉羽毛球教学知识图谱</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f7f8f5;
      --fg: #1f2724;
      --muted: #5f6d68;
      --card: #ffffff;
      --line: #c9d3cf;
      --accent: #176b5b;
      --accent-soft: #dcefea;
      --warn: #9a5968;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #151917;
        --fg: #edf3ef;
        --muted: #a9b6b0;
        --card: #202723;
        --line: #3b4742;
        --accent: #7fd0bd;
        --accent-soft: #173b34;
        --warn: #e0a6b4;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--fg);
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 18px 42px; }}
    header {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 18px;
      align-items: end;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
    }}
    h1 {{ margin: 0 0 8px; font-size: 28px; font-weight: 600; letter-spacing: 0; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.6; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(96px, 1fr)); gap: 10px; }}
    .metric {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }}
    .metric strong {{ display: block; font-size: 22px; font-weight: 600; }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    input, select {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: var(--card);
      color: var(--fg);
      font: inherit;
    }}
    input {{ flex: 1 1 260px; }}
    select {{ flex: 0 1 190px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .category {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }}
    .category h2 {{ margin: 0 0 6px; font-size: 18px; font-weight: 600; }}
    .category .count {{ color: var(--accent); font-weight: 600; }}
    details {{
      margin-top: 10px;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }}
    summary {{ cursor: pointer; font-weight: 600; }}
    .submeta {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
    .videos {{ display: grid; gap: 8px; margin-top: 10px; }}
    .video {{
      display: block;
      text-decoration: none;
      color: var(--fg);
      background: color-mix(in srgb, var(--accent-soft) 42%, transparent);
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 9px;
    }}
    .video:hover {{ border-color: var(--accent); }}
    .badge {{
      display: inline-block;
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
    }}
    .empty {{
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 18px;
      color: var(--muted);
      text-align: center;
    }}
    @media (max-width: 760px) {{
      header {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(96px, 1fr)); }}
      h1 {{ font-size: 24px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>刘辉羽毛球教学知识图谱</h1>
        <p>按主题组织全量抖音教学证据，保留代表视频入口，后续网课章节可以继续挂到同一套主题树。</p>
      </div>
      <section class="metrics" aria-label="知识库统计">
        <div class="metric"><strong id="metric-videos"></strong><span>全量视频</span></div>
        <div class="metric"><strong id="metric-indexable"></strong><span>教学证据</span></div>
        <div class="metric"><strong id="metric-assigned"></strong><span>已入主题</span></div>
        <div class="metric"><strong id="metric-multi"></strong><span>跨主题</span></div>
      </section>
    </header>
    <section class="toolbar" aria-label="筛选知识图谱">
      <input id="search" type="search" placeholder="搜索主题、关键词或代表视频">
      <select id="category-filter" aria-label="主题筛选"></select>
    </section>
    <section id="graph" class="grid" aria-live="polite"></section>
  </main>
  <script>
    const graph = {payload};
    const search = document.getElementById("search");
    const categoryFilter = document.getElementById("category-filter");
    const graphEl = document.getElementById("graph");
    document.getElementById("metric-videos").textContent = graph.video_count;
    document.getElementById("metric-indexable").textContent = graph.indexable_video_count;
    document.getElementById("metric-assigned").textContent = graph.assigned_video_count;
    document.getElementById("metric-multi").textContent = graph.multi_topic_video_count;

    categoryFilter.innerHTML = ["全部主题", ...graph.categories.map(c => c.name)]
      .map(name => `<option value="${{name}}">${{name}}</option>`)
      .join("");

    function matches(item, query) {{
      if (!query) return true;
      return JSON.stringify(item).toLowerCase().includes(query.toLowerCase());
    }}

    function render() {{
      const query = search.value.trim();
      const selected = categoryFilter.value;
      const cards = [];
      for (const category of graph.categories) {{
        if (selected !== "全部主题" && category.name !== selected) continue;
        const subtopics = category.subtopics.filter(subtopic => matches({{category: category.name, subtopic}}, query));
        if (!subtopics.length && query) continue;
        const details = subtopics.map(subtopic => `
          <details open>
            <summary>${{subtopic.name}} <span class="count">${{subtopic.video_count}}</span></summary>
            <div class="submeta">关键词：${{subtopic.keywords.slice(0, 5).join("、")}}</div>
            <div class="videos">
              ${{subtopic.representative_videos.map(video => `
                <a class="video" href="${{video.url}}" target="_blank" rel="noreferrer">
                  ${{video.title}}
                  <span class="badge">${{video.confidence}} · score ${{video.score}}</span>
                </a>
              `).join("")}}
            </div>
          </details>
        `).join("");
        cards.push(`
          <article class="category">
            <h2>${{category.name}} <span class="count">${{category.video_count}}</span></h2>
            <p>${{category.description}}</p>
            ${{details}}
          </article>
        `);
      }}
      graphEl.innerHTML = cards.length ? cards.join("") : '<div class="empty">没有匹配的主题</div>';
    }}

    search.addEventListener("input", render);
    categoryFilter.addEventListener("change", render);
    render();
  </script>
</body>
</html>
"""
    HTML_OUTPUT.write_text(html_text, encoding="utf-8")


def main():
    graph = load_graph()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_OUTPUT.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_drawio(graph)
    build_mermaid(graph)
    build_html(graph)
    print(
        json.dumps(
            {
                "drawio": str(DRAWIO_OUTPUT.relative_to(ROOT)),
                "mermaid": str(MERMAID_OUTPUT.relative_to(ROOT)),
                "html": str(HTML_OUTPUT.relative_to(ROOT)),
                "categories": len(graph["categories"]),
                "indexable_videos": graph["indexable_video_count"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
