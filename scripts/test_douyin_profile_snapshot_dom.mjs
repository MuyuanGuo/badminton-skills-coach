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
}

function profileAnchor(videoId, text) {
  const ul = new FakeElement("ul", { class: "profile-feed" });
  const li = new FakeElement("li", {}, text, ul);
  const div = new FakeElement("div", {}, text, li);
  return new FakeElement(
    "a",
    { href: `https://www.douyin.com/video/${videoId}` },
    text,
    div,
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

const anchors = [
  profileAnchor(
    "7661940775983482097",
    "1.2万 网前框架 #羽毛球 #刘辉羽毛球 #羽毛球教学",
  ),
  footerAnchor("7579314130383234937", "社区回应94岁老人在楼道打地铺"),
  genericRecommendationAnchor("7319487299002092836", "FConline一月份排位赛 #游戏日常"),
];

const context = {
  window: {
    location: { href: "https://www.douyin.com/user/MS4wLjABAAAArown2iD4dOZU015mQhaFt43bhkyhMu6c-SOUrTlmSqA" },
    scrollTo() {},
  },
  document: {
    documentElement: { scrollHeight: 1000 },
    querySelectorAll(selector) {
      assert.equal(selector, 'a[href*="/video/"]');
      return anchors;
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
  scrollRounds: 0,
  settleMs: 0,
});

assert.equal(snapshot.collected_unique_links, 1);
assert.equal(snapshot.videos[0].video_id, "7661940775983482097");
assert.equal(snapshot.videos[0].title, "1.2万 网前框架 #羽毛球 #刘辉羽毛球 #羽毛球教学");
assert.ok(!snapshot.videos.some((item) => item.video_id === "7579314130383234937"));
assert.ok(!snapshot.videos.some((item) => item.video_id === "7319487299002092836"));

console.log(JSON.stringify({ status: "ok", videos: snapshot.collected_unique_links }));
