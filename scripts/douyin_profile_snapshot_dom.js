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
  const DEFAULT_PROFILE_ID = "MS4wLjABAAAArown2iD4dOZU015mQhaFt43bhkyhMu6c-SOUrTlmSqA";

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function profileIdFromUrl(url) {
    const match = String(url || "").match(/\/user\/([^/?#]+)/);
    return match ? match[1] : "";
  }

  function findProfileFeedRoot() {
    return document.querySelector(
      '[data-e2e="user-post-list"], .profile-feed, main ul, main',
    );
  }

  function isProfileFeedAnchor(anchor, feedRoot) {
    const href = anchor.href || anchor.getAttribute("href") || "";
    if (href.includes("source=Baiduspider")) return false;
    if (anchor.closest("footer, .user-page-footer")) return false;
    const listItem = anchor.closest("li");
    return Boolean(listItem && feedRoot && feedRoot.contains(anchor));
  }

  function findVideoLinks(feedRoot) {
    const anchors = Array.from(document.querySelectorAll('a[href*="/video/"]'));
    const byId = new Map();

    for (const anchor of anchors) {
      if (!isProfileFeedAnchor(anchor, feedRoot)) continue;
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

  function mergeVideos(target, videos) {
    for (const video of videos) {
      const existing = target.get(video.video_id);
      if (!existing) {
        target.set(video.video_id, video);
        continue;
      }
      if (!existing.title && video.title) existing.title = video.title;
      if (video.raw_text.length > existing.raw_text.length) {
        existing.raw_text = video.raw_text;
      }
    }
  }

  function scrollToPosition(container, top) {
    if (container === document.documentElement || container === document.body) {
      window.scrollTo(0, top);
      return;
    }
    if (typeof container.scrollTo === "function") {
      container.scrollTo(0, top);
    } else {
      container.scrollTop = top;
    }
  }

  async function collectDouyinProfileSnapshot(options = {}) {
    const scrollRounds = Number.isFinite(options.scrollRounds) ? options.scrollRounds : 80;
    const settleMs = Number.isFinite(options.settleMs) ? options.settleMs : 1000;
    const stableThreshold = Number.isFinite(options.stableRounds) ? options.stableRounds : 5;
    const expectedProfileId = options.expectedProfileId || DEFAULT_PROFILE_ID;
    const profileUrl = window.location.href;
    const observedProfileId = profileIdFromUrl(profileUrl);
    if (observedProfileId !== expectedProfileId) {
      throw new Error(
        `Wrong Douyin profile: expected ${expectedProfileId}, observed ${observedProfileId || "missing"}`,
      );
    }
    const feedRoot = findProfileFeedRoot();
    if (!feedRoot) throw new Error("Douyin profile feed root was not found");
    const scrollContainer = document.querySelector(".route-scroll-container")
      || document.scrollingElement
      || document.documentElement;
    const collected = new Map();

    scrollToPosition(scrollContainer, 0);
    await sleep(settleMs);
    mergeVideos(collected, findVideoLinks(feedRoot));

    let lastCount = collected.size;
    let stableRounds = 0;
    let roundsCompleted = 0;
    for (let round = 0; round < scrollRounds; round += 1) {
      const scrollHeight = scrollContainer.scrollHeight || document.documentElement.scrollHeight;
      scrollToPosition(scrollContainer, scrollHeight);
      await sleep(settleMs);
      mergeVideos(collected, findVideoLinks(feedRoot));
      roundsCompleted = round + 1;
      const count = collected.size;
      if (count <= lastCount) {
        stableRounds += 1;
      } else {
        stableRounds = 0;
      }
      lastCount = count;
      if (stableRounds >= stableThreshold) break;
    }

    const videos = Array.from(collected.values());
    return {
      collector_version: 2,
      profile_url: profileUrl,
      profile_id: observedProfileId,
      collected_at: new Date().toISOString(),
      collected_unique_links: videos.length,
      scroll_rounds_completed: roundsCompleted,
      stable_rounds: stableRounds,
      collection_complete: stableRounds >= stableThreshold,
      videos,
    };
  }

  window.__collectDouyinProfileSnapshot = collectDouyinProfileSnapshot;
})();
