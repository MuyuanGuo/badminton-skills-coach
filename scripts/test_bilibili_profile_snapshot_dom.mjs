#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(
  new URL("./bilibili_profile_snapshot_dom.js", import.meta.url),
  "utf8",
);

assert.match(source, /EXPECTED_PROFILE_ID = "1423436652"/);
assert.match(source, /card_text/);
assert.equal(source.includes('meta[name="description"]'), false);
assert.match(source, /SEO description/);

const context = { window: {}, location: { pathname: "/wrong-profile" } };
vm.createContext(context);
vm.runInContext(source, context);
await assert.rejects(
  () => context.window.__collectBilibiliProfileSnapshot(),
  /Wrong Bilibili profile/,
);

console.log("Bilibili profile snapshot DOM collector checks passed");
