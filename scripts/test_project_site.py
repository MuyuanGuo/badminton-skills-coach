#!/usr/bin/env python3
import hashlib
import struct
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []
        self.h1_count = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        for key in ("href", "src"):
            value = attributes.get(key)
            if value:
                self.targets.append(value)


def jpeg_dimensions(path):
    content = path.read_bytes()
    if not content.startswith(b"\xff\xd8"):
        raise ValueError(f"Not a JPEG: {path}")
    offset = 2
    start_of_frame_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while offset + 8 < len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        marker = content[offset]
        offset += 1
        if marker in {0x01, *range(0xD0, 0xDA)}:
            continue
        segment_length = struct.unpack(">H", content[offset : offset + 2])[0]
        if marker in start_of_frame_markers:
            height, width = struct.unpack(">HH", content[offset + 3 : offset + 7])
            return width, height
        offset += segment_length
    raise ValueError(f"JPEG dimensions not found: {path}")


class ProjectSiteTests(unittest.TestCase):
    def test_local_links_and_assets_resolve(self):
        for page in [DOCS / "index.html", DOCS / "en" / "index.html"]:
            parser = AssetParser()
            parser.feed(page.read_text(encoding="utf-8"))
            self.assertEqual(parser.h1_count, 1, page)
            for target in parser.targets:
                parsed = urlparse(target)
                if parsed.scheme or parsed.netloc or target.startswith(("#", "mailto:")):
                    continue
                relative = unquote(parsed.path)
                resolved = (page.parent / relative).resolve()
                self.assertTrue(resolved.exists(), f"{page}: {target}")

    def test_social_preview_is_current_and_synchronized(self):
        source = ROOT / ".github" / "assets" / "social-preview.jpg"
        site_copy = DOCS / "assets" / "social-preview.jpg"
        self.assertEqual(jpeg_dimensions(source), (1280, 640))
        self.assertEqual(jpeg_dimensions(site_copy), (1280, 640))
        self.assertLess(source.stat().st_size, 1024 * 1024)
        self.assertEqual(
            hashlib.sha256(source.read_bytes()).digest(),
            hashlib.sha256(site_copy.read_bytes()).digest(),
        )
        for page in [DOCS / "index.html", DOCS / "en" / "index.html"]:
            self.assertNotIn("359", page.read_text(encoding="utf-8"))

    def test_site_has_bilingual_metadata_and_release_links(self):
        chinese = (DOCS / "index.html").read_text(encoding="utf-8")
        english = (DOCS / "en" / "index.html").read_text(encoding="utf-8")
        self.assertIn('lang="zh-CN"', chinese)
        self.assertIn('hreflang="en"', chinese)
        self.assertIn('lang="en"', english)
        self.assertIn('hreflang="zh-CN"', english)
        self.assertIn("releases/latest", chinese)
        self.assertIn("releases/latest", english)
        self.assertIn("./evaluation/", chinese)
        self.assertIn("../evaluation/", english)


if __name__ == "__main__":
    unittest.main()
