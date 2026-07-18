#!/usr/bin/env node
import assert from "node:assert/strict";

import {
  completeCookieFingerprint,
  isDouyinCookie,
  netscapeCookieText,
} from "./export_douyin_cookies_cdp.mjs";

const cookies = [
  {
    domain: ".douyin.com",
    name: "ttwid",
    value: "anonymous-value",
    path: "/",
    secure: true,
    expires: 12345.9,
  },
  {
    domain: "www.douyin.com",
    name: "s_v_web_id",
    value: "safe\tvalue\n",
    path: "/video",
    secure: false,
    expires: 0,
  },
  {
    domain: ".example.com",
    name: "unrelated",
    value: "must-not-be-exported",
    path: "/",
  },
];

assert.equal(isDouyinCookie(cookies[0]), true);
assert.equal(isDouyinCookie(cookies[2]), false);
const text = netscapeCookieText(cookies);
assert.ok(text.startsWith("# Netscape HTTP Cookie File\n"));
assert.ok(text.includes(".douyin.com\tTRUE\t/\tTRUE\t12345\tttwid\tanonymous-value"));
assert.ok(text.includes("www.douyin.com\tFALSE\t/video\tFALSE\t0\ts_v_web_id\tsafevalue"));
assert.ok(!text.includes("example.com"));
assert.ok(!text.includes("must-not-be-exported"));

const requiredNames = [
  "UIFID",
  "__ac_nonce",
  "__ac_signature",
  "odin_tt",
  "s_v_web_id",
  "ttwid",
];
const completeCookies = requiredNames.map((name) => ({
  domain: ".douyin.com",
  name,
  value: "value",
}));
for (let index = completeCookies.length; index < 20; index += 1) {
  completeCookies.push({
    domain: ".douyin.com",
    name: `support_${index}`,
    value: "value",
  });
}
assert.equal(completeCookieFingerprint(completeCookies.slice(0, 19)), null);
assert.ok(completeCookieFingerprint(completeCookies));
assert.equal(
  completeCookieFingerprint(completeCookies.filter((cookie) => cookie.name !== "__ac_signature")),
  null,
);

console.log(JSON.stringify({ status: "ok", exported: 2 }));
