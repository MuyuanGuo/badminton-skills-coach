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


def png_dimensions(path):
    content = path.read_bytes()
    if content[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG: {path}")
    return struct.unpack(">II", content[16:24])


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
        source = ROOT / ".github" / "assets" / "social-preview.png"
        site_copy = DOCS / "assets" / "social-preview.png"
        self.assertEqual(png_dimensions(source), (1280, 640))
        self.assertEqual(png_dimensions(site_copy), (1280, 640))
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


if __name__ == "__main__":
    unittest.main()
