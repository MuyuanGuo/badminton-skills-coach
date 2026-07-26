/*
Collect Bilibili profile video-card metadata from the loaded 大G羽毛球 space.

This intentionally collects card-local text only. Do not replace it with the
video page's SEO description: Bilibili appends uploader biography and related
video titles, which contaminates origin classification.

  await window.__collectBilibiliProfileSnapshot({ scrollRounds: 80 })
*/

(function () {
  const EXPECTED_PROFILE_ID = "1423436652";

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalizeText = (value) => String(value || "").replace(/\s+/g, " ").trim();

  function collectCards() {
    const videos = new Map();
    for (const anchor of document.querySelectorAll('a[href*="/video/BV"]')) {
      const match = String(anchor.href || "").match(/\/video\/(BV[0-9A-Za-z]{10})/);
      if (!match) continue;
      const bvid = match[1];
      const card = anchor.closest(
        ".small-item, .video-card, .bili-video-card, article, li",
      ) || anchor;
      const titleNode = card.querySelector(
        "[title], .title, .bili-video-card__info--tit, h3",
      );
      const title = normalizeText(
        titleNode?.getAttribute("title") || titleNode?.textContent || anchor.title,
      );
      if (!title) continue;
      const current = videos.get(bvid);
      const cardText = normalizeText(card.textContent || title);
      if (!current || cardText.length > current.card_text.length) {
        videos.set(bvid, {
          bvid,
          url: `https://www.bilibili.com/video/${bvid}/`,
          title,
          card_text: cardText,
          uploader_profile_id: EXPECTED_PROFILE_ID,
        });
      }
    }
    return videos;
  }

  async function collect(options = {}) {
    const profileId = String(location.pathname).split("/").filter(Boolean)[0] || "";
    if (profileId !== EXPECTED_PROFILE_ID) {
      throw new Error(`Wrong Bilibili profile: ${profileId || "missing"}`);
    }
    const rounds = Number.isFinite(options.scrollRounds) ? options.scrollRounds : 80;
    const settleMs = Number.isFinite(options.settleMs) ? options.settleMs : 900;
    const stableTarget = Number.isFinite(options.stableRounds) ? options.stableRounds : 5;
    const all = new Map();
    let stableRounds = 0;
    let previousSize = 0;
    for (let round = 0; round < rounds && stableRounds < stableTarget; round += 1) {
      for (const [id, item] of collectCards()) all.set(id, item);
      stableRounds = all.size === previousSize ? stableRounds + 1 : 0;
      previousSize = all.size;
      window.scrollTo(0, document.documentElement.scrollHeight);
      await sleep(settleMs);
    }
    for (const [id, item] of collectCards()) all.set(id, item);
    const videos = Array.from(all.values());
    return {
      collector_version: 1,
      snapshot_scope: "incremental_recent_profile_observation",
      full_profile_archive: false,
      profile_url: `https://space.bilibili.com/${EXPECTED_PROFILE_ID}`,
      profile_id: EXPECTED_PROFILE_ID,
      collected_at: new Date().toISOString(),
      collected_unique_links: videos.length,
      scroll_stabilized: stableRounds >= stableTarget,
      videos,
    };
  }

  window.__collectBilibiliProfileSnapshot = collect;
})();
