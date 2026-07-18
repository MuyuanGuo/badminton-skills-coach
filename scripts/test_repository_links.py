#!/usr/bin/env python3
import re
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK_PATTERN = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
TEMPORARY_MEDIA_URL_PATTERN = re.compile(
    r"https://[^\s\"')>]*(?:zjcdn\.com|douyinvod\.com)[^\s\"')>]*",
    re.IGNORECASE,
)


class RepositoryLinkTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self):
        markdown_paths = [
            path
            for path in ROOT.rglob("*.md")
            if not any(part in {".git", ".venv", "data", "output"} for part in path.parts)
        ]
        broken = []
        for path in markdown_paths:
            text = path.read_text(encoding="utf-8")
            for target in MARKDOWN_LINK_PATTERN.findall(text):
                target = target.strip().strip("<>")
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                file_target = unquote(target.split("#", 1)[0])
                if file_target and not (path.parent / file_target).exists():
                    broken.append(f"{path.relative_to(ROOT)} -> {target}")
        self.assertEqual(broken, [])

    def test_tracked_text_never_contains_short_lived_media_urls(self):
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT
        ).decode().split("\0")
        tracked.extend(
            subprocess.check_output(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=ROOT,
            ).decode().split("\0")
        )
        leaks = []
        for relative in tracked:
            if not relative:
                continue
            path = ROOT / relative
            if not path.is_file() or path.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".zip",
            }:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if TEMPORARY_MEDIA_URL_PATTERN.search(text):
                leaks.append(relative)
        self.assertEqual(leaks, [])


if __name__ == "__main__":
    unittest.main()
