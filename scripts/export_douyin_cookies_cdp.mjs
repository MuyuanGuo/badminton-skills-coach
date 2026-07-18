#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const REQUIRED_COOKIE_NAMES = new Set([
  "UIFID",
  "__ac_nonce",
  "__ac_signature",
  "odin_tt",
  "s_v_web_id",
  "ttwid",
]);
const MINIMUM_COOKIE_COUNT = 20;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function sanitizeCookieField(value) {
  return String(value ?? "").replace(/[\t\r\n]/g, "");
}

export function isDouyinCookie(cookie) {
  const domain = String(cookie?.domain ?? "").toLowerCase().replace(/^\./, "");
  return Boolean(cookie?.name) && (domain === "douyin.com" || domain.endsWith(".douyin.com"));
}

export function netscapeCookieText(cookies) {
  const rows = ["# Netscape HTTP Cookie File"];
  for (const cookie of cookies.filter(isDouyinCookie)) {
    const domain = sanitizeCookieField(cookie.domain);
    const includeSubdomains = domain.startsWith(".") ? "TRUE" : "FALSE";
    const expires = Math.max(0, Math.floor(Number(cookie.expires) || 0));
    rows.push([
      domain,
      includeSubdomains,
      sanitizeCookieField(cookie.path || "/"),
      cookie.secure ? "TRUE" : "FALSE",
      String(expires),
      sanitizeCookieField(cookie.name),
      sanitizeCookieField(cookie.value),
    ].join("\t"));
  }
  return `${rows.join("\n")}\n`;
}

export function completeCookieFingerprint(cookies) {
  const douyinCookies = cookies.filter(isDouyinCookie);
  const names = new Set(douyinCookies.map((cookie) => cookie.name));
  if (
    douyinCookies.length < MINIMUM_COOKIE_COUNT
    || ![...REQUIRED_COOKIE_NAMES].every((name) => names.has(name))
  ) {
    return null;
  }
  return [...names].sort().join("\n");
}

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!name?.startsWith("--") || value === undefined) {
      throw new Error(`Invalid argument near ${name || "end of command"}`);
    }
    args[name.slice(2)] = value;
  }
  for (const required of ["endpoint", "url", "output"]) {
    if (!args[required]) {
      throw new Error(`Missing --${required}`);
    }
  }
  return {
    ...args,
    timeoutSeconds: Number(args["timeout-seconds"] || 30),
  };
}

class CdpClient {
  constructor(endpoint) {
    if (typeof WebSocket !== "function") {
      throw new Error("Node.js 22 or newer is required for the built-in WebSocket client");
    }
    this.socket = new WebSocket(endpoint);
    this.nextId = 1;
    this.pending = new Map();
  }

  async connect(timeoutMilliseconds) {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP WebSocket connection timed out")), timeoutMilliseconds);
      this.socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      this.socket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("CDP WebSocket connection failed"));
      }, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (!message.id || !this.pending.has(message.id)) {
        return;
      }
      const { resolve, reject, timer } = this.pending.get(message.id);
      this.pending.delete(message.id);
      clearTimeout(timer);
      if (message.error) {
        reject(new Error(message.error.message || "CDP request failed"));
      } else {
        resolve(message.result || {});
      }
    });
  }

  request(method, params, timeoutMilliseconds = 5000) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP request timed out: ${method}`));
      }, timeoutMilliseconds);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.socket.close();
  }
}

export async function exportCookies({ endpoint, url, output, timeoutSeconds }) {
  if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0 || timeoutSeconds > 120) {
    throw new Error("--timeout-seconds must be between 1 and 120");
  }
  const client = new CdpClient(endpoint);
  const deadline = Date.now() + timeoutSeconds * 1000;
  let previousFingerprint = null;
  await client.connect(Math.min(10000, timeoutSeconds * 1000));
  try {
    while (Date.now() < deadline) {
      const result = await client.request("Storage.getCookies", { urls: [url] });
      const cookies = (result.cookies || []).filter(isDouyinCookie);
      const fingerprint = completeCookieFingerprint(cookies);
      if (fingerprint && fingerprint === previousFingerprint) {
        const outputPath = path.resolve(output);
        fs.mkdirSync(path.dirname(outputPath), { recursive: true });
        const temporaryPath = `${outputPath}.tmp-${process.pid}`;
        fs.writeFileSync(temporaryPath, netscapeCookieText(cookies), { encoding: "utf8", mode: 0o600 });
        fs.chmodSync(temporaryPath, 0o600);
        fs.renameSync(temporaryPath, outputPath);
        return { count: cookies.length, requiredCookiesPresent: true };
      }
      previousFingerprint = fingerprint;
      await delay(500);
    }
  } finally {
    client.close();
  }
  throw new Error("Douyin did not issue the required anonymous browser cookies before timeout");
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const result = await exportCookies(args);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
