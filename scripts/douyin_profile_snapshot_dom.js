/*
Collect visible Douyin profile video links from a loaded browser page.

This file is intentionally browser-context JavaScript. It expects `window` and
`document`, and returns a plain object:

  await window.__collectDouyinProfileSnapshot({ scrollRounds: 8 })

Use it from an authenticated browser session on the creator profile page. The
repository monitor consumes the saved JSON through:

  python3 scripts/monitor_douyin_updates.py --snapshot data/tmp/douyin_profile_latest.json
*/

(function () {
  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function findVideoLinks() {
    const anchors = Array.from(document.querySelectorAll('a[href*="/video/"]'));
    const byId = new Map();

    for (const anchor of anchors) {
      const href = anchor.href || anchor.getAttribute("href") || "";
      const match = href.match(/\/video\/(\d+)/);
      if (!match) continue;

      const videoId = match[1];
      const container = anchor.closest("li, article, div") || anchor;
      const title = normalizeText(
        anchor.getAttribute("aria-label") ||
        anchor.getAttribute("title") ||
        anchor.innerText ||
        container.innerText
      );
      const rawText = normalizeText(container.innerText || title);

      if (!byId.has(videoId)) {
        byId.set(videoId, {
          video_id: videoId,
          url: `https://www.douyin.com/video/${videoId}`,
          title,
          raw_text: rawText || title,
          teaching_candidate: "unknown",
        });
      } else {
        const existing = byId.get(videoId);
        if (!existing.title && title) existing.title = title;
        if (rawText.length > existing.raw_text.length) existing.raw_text = rawText;
      }
    }

    return Array.from(byId.values());
  }

  async function collectDouyinProfileSnapshot(options = {}) {
    const scrollRounds = Number.isFinite(options.scrollRounds) ? options.scrollRounds : 8;
    const settleMs = Number.isFinite(options.settleMs) ? options.settleMs : 1200;
    const profileUrl = window.location.href;

    let lastCount = 0;
    let stableRounds = 0;
    for (let round = 0; round < scrollRounds; round += 1) {
      window.scrollTo(0, document.documentElement.scrollHeight);
      await sleep(settleMs);

      const count = findVideoLinks().length;
      if (count <= lastCount) {
        stableRounds += 1;
      } else {
        stableRounds = 0;
      }
      lastCount = count;
      if (stableRounds >= 2) break;
    }

    const videos = findVideoLinks();
    return {
      profile_url: profileUrl,
      collected_at: new Date().toISOString(),
      collected_unique_links: videos.length,
      videos,
    };
  }

  window.__collectDouyinProfileSnapshot = collectDouyinProfileSnapshot;
})();
