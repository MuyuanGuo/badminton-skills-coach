#!/usr/bin/env python3
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "knowledge" / "pilot_knowledge_base.json"
OUTPUT = ROOT / "output" / "liuhui-pilot-knowledge-map.drawio"

data = json.loads(SOURCE.read_text(encoding="utf-8"))
groups = defaultdict(list)
for video in data["videos"]:
    groups[video["category"]].append(video)

diagram_file = ET.Element(
    "mxfile",
    host="app.diagrams.net",
    modified="2026-07-09T00:00:00.000Z",
    agent="Codex",
    version="24.7.17",
)
diagram = ET.SubElement(diagram_file, "diagram", id="liuhui-pilot", name="首批25条教学知识")
model = ET.SubElement(
    diagram,
    "mxGraphModel",
    dx="1800",
    dy="2400",
    grid="1",
    gridSize="10",
    guides="1",
    tooltips="1",
    connect="1",
    arrows="1",
    fold="1",
    page="1",
    pageScale="1",
    pageWidth="2200",
    pageHeight="3600",
    math="0",
    shadow="0",
)
root = ET.SubElement(model, "root")
ET.SubElement(root, "mxCell", id="0")
ET.SubElement(root, "mxCell", id="1", parent="0")


def vertex(cell_id, label, x, y, width, height, style, link=None):
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


def edge(cell_id, source, target):
    cell = ET.SubElement(
        root,
        "mxCell",
        id=cell_id,
        style="edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;"
        "jettySize=auto;html=1;strokeColor=#7A8A86;strokeWidth=2;",
        edge="1",
        parent="1",
        source=source,
        target=target,
    )
    ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})


vertex(
    "center",
    "刘辉羽毛球<br><b>首批25条教学知识</b><br>23条可用 · 2条待视觉复核",
    820,
    1450,
    320,
    110,
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#123B36;fontColor=#FFFFFF;"
    "strokeColor=#0C2B27;strokeWidth=3;fontSize=17;fontStyle=1;arcSize=8;",
)

palette = [
    ("#DCEFEA", "#176B5B"),
    ("#F7E6DE", "#B85C38"),
    ("#E7EDF5", "#456A8A"),
    ("#F3EBCF", "#967326"),
    ("#E9E3F2", "#72578C"),
]

categories = sorted(groups)
left = categories[:5]
right = categories[5:]
category_positions = {}
for side, names in (("left", left), ("right", right)):
    for index, name in enumerate(names):
        x = 470 if side == "left" else 1190
        y = 260 + index * 580
        category_positions[name] = (side, x, y)

edge_index = 1
video_index = 1
for category_index, category in enumerate(categories):
    side, x, y = category_positions[category]
    fill, stroke = palette[category_index % len(palette)]
    category_id = f"category-{category_index}"
    vertex(
        category_id,
        f"<b>{category}</b><br>{len(groups[category])} 条",
        x,
        y,
        250,
        76,
        f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
        "strokeWidth=2;fontSize=15;fontStyle=1;arcSize=6;",
    )
    edge(f"edge-{edge_index}", "center", category_id)
    edge_index += 1

    videos = groups[category]
    for item_index, video in enumerate(videos):
        vx = 40 if side == "left" else 1510
        vy = y - 70 + item_index * 125
        status = "待视觉复核" if video["processing_status"] == "needs_visual_review" else "已转写"
        label = video["title"]
        if len(label) > 64:
            label = label[:64] + "…"
        video_id = f"video-{video_index}"
        vertex(
            video_id,
            f"<b>{label}</b><br><font color='#52625E'>{status} · {video['duration_seconds']:.0f}s</font>",
            vx,
            vy,
            360,
            94,
            "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#AAB8B4;"
            "strokeWidth=1.5;fontSize=12;align=left;spacingLeft=10;arcSize=5;",
            video["url"],
        )
        edge(f"edge-{edge_index}", category_id, video_id)
        edge_index += 1
        video_index += 1

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
ET.ElementTree(diagram_file).write(OUTPUT, encoding="utf-8", xml_declaration=True)
print(json.dumps({
    "output": str(OUTPUT),
    "categories": len(categories),
    "videos": len(data["videos"]),
}, ensure_ascii=False))
