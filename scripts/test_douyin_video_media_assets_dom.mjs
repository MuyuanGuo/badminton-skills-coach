#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const VIDEO_ID = "7663523942439940453";
const VIDEO_URL = `https://www.douyin.com/video/${VIDEO_ID}`;
const MEDIA_HOST = "v3-dy-o." + "zjcdn.com";
const VIDEO_ASSET = `https://${MEDIA_HOST}/token/video/tos/cn/example/?mime_type=video_mp4`;
const AUDIO_ASSET = `https://${MEDIA_HOST}/token/video/tos/cn/example/media-audio-und-mp4a/`;
const collector = fs.readFileSync("scripts/douyin_video_media_assets_dom.js", "utf8");

function buildContext(resources) {
  const video = {
    currentSrc: "blob:https://www.douyin.com/player-stream",
    src: "blob:https://www.douyin.com/player-stream",
    readyState: 4,
    paused: false,
    clientWidth: 800,
    clientHeight: 450,
    querySelectorAll() { return []; },
  };
  const context = {
    window: { location: { href: VIDEO_URL } },
    document: {
      title: "多点位抽球应用 - 抖音",
      querySelectorAll(selector) {
        assert.equal(selector, "video");
        return [video];
      },
    },
    performance: {
      getEntriesByType(type) {
        assert.equal(type, "resource");
        return resources;
      },
    },
    setTimeout,
    Date,
    Promise,
  };
  context.window.document = context.document;
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(collector, context);
  return context;
}

const readyContext = buildContext([
  { name: AUDIO_ASSET, initiatorType: "fetch", transferSize: 10, startTime: 20 },
  { name: VIDEO_ASSET, initiatorType: "fetch", transferSize: 100, startTime: 30 },
]);
const ready = await readyContext.window.__collectDouyinVideoMediaAssets({ waitMs: 0 });
assert.equal(ready.collector_version, 2);
assert.equal(ready.video_id, VIDEO_ID);
assert.equal(ready.collection_status, "ready");
assert.equal(ready.preferred_video.url, VIDEO_ASSET);
assert.equal(ready.preferred_audio.url, AUDIO_ASSET);
assert.equal(ready.diagnostics.blob_stream_count, 1);
assert.equal(ready.diagnostics.performance_media_count, 2);

const blobOnlyContext = buildContext([]);
const blobOnly = await blobOnlyContext.window.__collectDouyinVideoMediaAssets({ waitMs: 0 });
assert.equal(blobOnly.collection_status, "no_downloadable_media");
assert.equal(blobOnly.assets.length, 0);
assert.ok(blobOnly.warnings.some((warning) => warning.includes("blob/MediaSource")));

console.log(JSON.stringify({ status: "ok", ready_assets: ready.assets.length }));
