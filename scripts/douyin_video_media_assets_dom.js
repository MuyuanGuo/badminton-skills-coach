/*
Collect media assets from a loaded Douyin video detail page.

Run this in an authenticated browser session after the video page has loaded:

  await window.__collectDouyinVideoMediaAssets({ waitMs: 3000 })

Save the returned JSON to `data/tmp/<video_id>-media-assets.json`, then run:

  python3 scripts/prepare_douyin_media_batch.py \
    --input data/tmp/<video_id>-media-assets.json \
    --batch batch-049
*/

(function () {
  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function normalizeUrl(value) {
    return String(value || "").replace(/&amp;/g, "&");
  }

  function assetKind(url, name) {
    const text = `${url} ${name || ""}`;
    if (/media-audio|mp4a|audio/i.test(text)) return "audio";
    if (
      /media-video|avc1|h264|video|douyinvod|idouyinvod|zjcdn|zzcdn|volccdn|bytefcdn|tos-cn/i.test(text)
    ) return "video";
    return "other";
  }

  function collectFromDom() {
    const assets = [];
    const blobStreams = [];
    const seenBlobStreams = new Set();
    const videos = Array.from(document.querySelectorAll("video"))
      .map((video, index) => ({
        video,
        index,
        score:
          (video.currentSrc ? 100 : 0) +
          (video.readyState >= 2 ? 20 : 0) +
          (!video.paused ? 10 : 0) +
          Math.min(9, Math.round((video.clientWidth * video.clientHeight) / 100000)),
      }))
      .sort((left, right) => right.score - left.score || left.index - right.index);
    for (const { video, index, score } of videos) {
      for (const url of [video.currentSrc, video.src]) {
        if (String(url || "").startsWith("blob:")) {
          if (!seenBlobStreams.has(String(url))) {
            seenBlobStreams.add(String(url));
            blobStreams.push({ element_index: index, url: String(url) });
          }
          continue;
        }
        if (url) assets.push({
          kind: "video",
          source: "video",
          url: normalizeUrl(url),
          priority: score,
          element_index: index,
        });
      }
      for (const source of Array.from(video.querySelectorAll("source"))) {
        const url = source.src || source.getAttribute("src");
        if (url) assets.push({
          kind: "video",
          source: "source",
          url: normalizeUrl(url),
          priority: score - 1,
          element_index: index,
        });
      }
    }
    return { assets, blobStreams };
  }

  function collectFromPerformance() {
    if (!globalThis.performance?.getEntriesByType) return [];
    return performance.getEntriesByType("resource")
      .map((entry) => {
        const url = normalizeUrl(entry.name);
        const name = url.split("?")[0].split("/").filter(Boolean).pop() || "";
        return {
          kind: assetKind(url, name),
          source: entry.initiatorType || "resource",
          name,
          url,
          transferSize: entry.transferSize || 0,
          startTime: entry.startTime || 0,
          priority: 0,
        };
      })
      .filter((asset) => asset.kind !== "other");
  }

  async function collectDouyinVideoMediaAssets(options = {}) {
    const waitMs = Number.isFinite(options.waitMs) ? options.waitMs : 3000;
    await sleep(waitMs);
    const pageUrl = window.location.href;
    const videoId = (pageUrl.match(/\/video\/(\d+)/) || [])[1] || "";
    const title = document.title.replace(/\s*-\s*抖音\s*$/, "").trim();
    const dom = collectFromDom();
    const performanceAssets = collectFromPerformance();
    const assets = [...dom.assets, ...performanceAssets]
      .filter((asset) => /^https?:/.test(asset.url));
    const seen = new Set();
    const uniqueAssets = assets.filter((asset) => {
      if (seen.has(asset.url)) return false;
      seen.add(asset.url);
      return true;
    }).sort((left, right) =>
      (right.priority || 0) - (left.priority || 0) ||
      (right.startTime || 0) - (left.startTime || 0)
    );
    const preferredAudio = uniqueAssets.find((asset) => asset.kind === "audio") || null;
    const preferredVideo = uniqueAssets.find((asset) => asset.kind === "video") || null;
    const warnings = [];
    if (dom.blobStreams.length && !preferredVideo) {
      warnings.push(
        "The active player uses a blob/MediaSource stream, but no downloadable HTTPS video resource was observed.",
      );
    }
    if (!uniqueAssets.length) {
      warnings.push(
        "No downloadable media asset was found. Run this collector in the browser DevTools console after playback starts.",
      );
    }
    return {
      collector_version: 2,
      video_id: videoId,
      page_url: pageUrl,
      title,
      collected_at: new Date().toISOString(),
      collection_status: uniqueAssets.length ? "ready" : "no_downloadable_media",
      diagnostics: {
        video_element_count: document.querySelectorAll("video").length,
        blob_stream_count: dom.blobStreams.length,
        performance_media_count: performanceAssets.length,
      },
      warnings,
      assets: uniqueAssets,
      preferred_audio: preferredAudio,
      preferred_video: preferredVideo,
    };
  }

  window.__collectDouyinVideoMediaAssets = collectDouyinVideoMediaAssets;
})();
