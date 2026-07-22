#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

class FakeElement {
  constructor(tagName, attrs = {}, text = "", parent = null) {
    this.tagName = tagName.toUpperCase();
    this.attrs = attrs;
    this.innerText = text;
    this.parentElement = parent;
    this.id = attrs.id || "";
    this.className = attrs.class || "";
    this.scrollHeight = attrs.scrollHeight || 0;
    this.scrollTop = 0;
  }

  get href() {
    return this.attrs.href || "";
  }

  getAttribute(name) {
    return this.attrs[name] || null;
  }

  closest(selector) {
    const selectors = selector.split(",").map((item) => item.trim());
    let current = this;
    while (current) {
      for (const part of selectors) {
        if (part.startsWith(".") && current.className.split(/\s+/).includes(part.slice(1))) {
          return current;
        }
        if (current.tagName.toLowerCase() === part.toLowerCase()) {
          return current;
        }
      }
      current = current.parentElement;
    }
    return null;
  }

  contains(candidate) {
    let current = candidate;
    while (current) {
      if (current === this) return true;
      current = current.parentElement;
    }
    return false;
  }
}

function profileAnchor(feedRoot, videoId, text) {
  const li = new FakeElement("li", {}, text, feedRoot);
  const div = new FakeElement("div", {}, text, li);
  return new FakeElement(
    "a",
    { href: `https://www.douyin.com/video/${videoId}` },
    text,
    div,
  );
}

function recommendationInList(videoId, text) {
  const sidebar = new FakeElement("aside", { class: "recommendations" });
  const li = new FakeElement("li", {}, text, sidebar);
  return new FakeElement(
    "a",
    { href: `https://www.douyin.com/video/${videoId}` },
    text,
    li,
  );
}

function footerAnchor(videoId, text) {
  const footer = new FakeElement("footer", { class: "user-page-footer" });
  const div = new FakeElement("div", {}, text, footer);
  const span = new FakeElement("span", {}, text, div);
  return new FakeElement(
    "a",
    { href: `https://www.douyin.com/video/${videoId}?source=Baiduspider` },
    text,
    span,
  );
}

function genericRecommendationAnchor(videoId, text) {
  const div = new FakeElement("div", {}, text);
  return new FakeElement(
    "a",
    { href: `https://www.douyin.com/video/${videoId}` },
    text,
    div,
  );
}

const feedRoot = new FakeElement("ul", { class: "profile-feed" });
const firstProfileAnchor = profileAnchor(
  feedRoot,
  "7661940775983482097",
  "1.2万 网前框架 #羽毛球 #刘辉羽毛球 #羽毛球教学",
);
const secondProfileAnchor = profileAnchor(
  feedRoot,
  "7661007346362449893",
  "新教学视频 #刘辉羽毛球 #羽毛球教学",
);
const excludedAnchors = [
  footerAnchor("7579314130383234937", "社区回应94岁老人在楼道打地铺"),
  genericRecommendationAnchor("7319487299002092836", "FConline一月份排位赛 #游戏日常"),
  recommendationInList("7319487299002092999", "侧边栏羽毛球推荐"),
];
let visibleAnchors = [firstProfileAnchor, ...excludedAnchors];
const scrollContainer = new FakeElement("div", { class: "route-scroll-container", scrollHeight: 2000 });
scrollContainer.scrollTo = (_left, top) => {
  scrollContainer.scrollTop = top;
  visibleAnchors = top > 0
    ? [secondProfileAnchor, ...excludedAnchors]
    : [firstProfileAnchor, ...excludedAnchors];
};

const context = {
  window: {
    location: { href: "https://www.douyin.com/user/MS4wLjABAAAArown2iD4dOZU015mQhaFt43bhkyhMu6c-SOUrTlmSqA" },
    scrollTo() {},
  },
  document: {
    documentElement: { scrollHeight: 1000 },
    body: new FakeElement("body"),
    scrollingElement: null,
    querySelector(selector) {
      if (selector === ".route-scroll-container") return scrollContainer;
      if (selector.includes('[data-e2e="user-post-list"]')) return feedRoot;
      return null;
    },
    querySelectorAll(selector) {
      assert.equal(selector, 'a[href*="/video/"]');
      return visibleAnchors;
    },
  },
  setTimeout,
  Date,
};
context.window.document = context.document;

const script = fs.readFileSync("scripts/douyin_profile_snapshot_dom.js", "utf8");
vm.createContext(context);
vm.runInContext(script, context);

const snapshot = await context.window.__collectDouyinProfileSnapshot({
  scrollRounds: 3,
  stableRounds: 1,
  settleMs: 0,
});

assert.equal(snapshot.collector_version, 3);
assert.equal(snapshot.snapshot_scope, "incremental_recent_profile_observation");
assert.equal(snapshot.full_profile_archive, false);
assert.equal(snapshot.collected_unique_links, 2);
assert.deepEqual(
  Array.from(snapshot.videos, (item) => item.video_id),
  ["7661940775983482097", "7661007346362449893"],
);
assert.ok(!snapshot.videos.some((item) => item.video_id === "7579314130383234937"));
assert.ok(!snapshot.videos.some((item) => item.video_id === "7319487299002092836"));
assert.ok(!snapshot.videos.some((item) => item.video_id === "7319487299002092999"));
assert.equal(snapshot.scroll_stabilized, true);
await assert.rejects(
  context.window.__collectDouyinProfileSnapshot({
    expectedProfileId: "wrong-profile",
    scrollRounds: 0,
    settleMs: 0,
  }),
  /Wrong Douyin profile/,
);

console.log(JSON.stringify({ status: "ok", videos: snapshot.collected_unique_links }));
