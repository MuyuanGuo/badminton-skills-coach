"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const urlToken = new URLSearchParams(window.location.search).get("token") || "";
const app = {
  token: urlToken || sessionStorage.getItem("v3-review-session-token") || "",
  csrf: "",
  session: null,
  playback: [],
  lastPlaybackTime: null,
  draftTimer: null,
  toastTimer: null,
  confirmAction: null,
};

if (urlToken) {
  sessionStorage.setItem("v3-review-session-token", urlToken);
  history.replaceState({}, "", window.location.pathname);
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("is-error", error);
  element.classList.add("is-visible");
  clearTimeout(app.toastTimer);
  app.toastTimer = setTimeout(() => element.classList.remove("is-visible"), 3600);
}

async function api(path, options = {}) {
  const headers = { "X-Review-Token": app.token, ...(options.headers || {}) };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    headers["X-CSRF-Token"] = app.csrf;
  }
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function formatTime(milliseconds) {
  const seconds = Math.max(0, Math.floor(Number(milliseconds || 0) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function lines(value) {
  return String(value || "").split("\n").map((item) => item.trim()).filter(Boolean);
}

function parseReviewTimestamp(value) {
  const normalized = String(value || "").trim();
  if (/^\d+$/.test(normalized)) {
    const milliseconds = Number(normalized);
    if (Number.isSafeInteger(milliseconds)) return milliseconds;
    throw new Error(`视觉时间点超出安全范围：${normalized}`);
  }
  const match = normalized.match(/^(\d+):([0-5]\d)(?:\.(\d{1,3}))?$/);
  if (!match) throw new Error(`无法识别视觉时间点：${normalized}`);
  const milliseconds = String(match[3] || "").padEnd(3, "0");
  const timestamp = (Number(match[1]) * 60 + Number(match[2])) * 1000 + Number(milliseconds || 0);
  if (Number.isSafeInteger(timestamp)) return timestamp;
  throw new Error(`视觉时间点超出安全范围：${normalized}`);
}

function collectVisualTimestamps() {
  const timestamps = String($("#event-visual-timestamps").value || "")
    .split(/[\s,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map(parseReviewTimestamp);
  return [...new Set(timestamps)].sort((left, right) => left - right);
}

function head(entityType, entityId = null) {
  const matches = app.session.heads.filter((item) => item.entity_type === entityType);
  if (entityId) return matches.find((item) => item.entity_id === entityId) || null;
  return matches.at(-1) || null;
}

function transcriptHead() {
  return head("transcript", app.session.transcript_entity_id);
}

function dependencyKeys(item, entityType) {
  return (item?.payload?.dependencies || [])
    .filter((dependency) => dependency.entity_type === entityType)
    .map((dependency) => dependency.entity_id);
}

function eventHeads() {
  return app.session.heads.filter((item) => (
    item.entity_type === "teaching_event"
    && dependencyKeys(item, "transcript").includes(app.session.transcript_entity_id)
  ));
}

function eventHead() {
  const selected = $("#event-id").value;
  const matches = eventHeads();
  return matches.find((item) => item.entity_id === selected) || matches.at(-1) || null;
}

function claimHeads() {
  const eventIds = new Set(eventHeads().map((item) => item.entity_id));
  return app.session.heads.filter((item) => {
    if (item.entity_type !== "semantic_claim") return false;
    const dependencies = dependencyKeys(item, "teaching_event");
    return dependencies.length > 0 && dependencies.every((entityId) => eventIds.has(entityId));
  });
}

function claimHead() {
  const selected = $("#claim-id").value;
  const matches = claimHeads();
  return matches.find((item) => item.entity_id === selected) || matches.at(-1) || null;
}

function expectedFields(current) {
  return {
    expected_revision: current ? current.revision : 0,
    expected_base_fingerprint: current ? current.content_fingerprint : "",
  };
}

function reviewer() {
  const value = $("#reviewer-id").value.trim();
  if (!value) throw new Error("先填写审核者身份。");
  localStorage.setItem("v3-reviewer-id", value);
  return value;
}

function setView(name) {
  $$(".view-tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.view === name));
  $$(".view").forEach((view) => {
    const active = view.id === `view-${name}`;
    view.classList.toggle("is-active", active);
    view.hidden = !active;
  });
}

function mergeCoverage(intervals) {
  const duration = app.session.candidate.media.duration_ms;
  const sorted = intervals
    .map(([start, end]) => [Math.max(0, Math.round(start)), Math.min(duration, Math.round(end))])
    .filter(([start, end]) => end > start)
    .sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const interval of sorted) {
    const previous = merged.at(-1);
    if (!previous || interval[0] > previous[1] + 350) merged.push(interval);
    else previous[1] = Math.max(previous[1], interval[1]);
  }
  return merged;
}

function coverageObjects() {
  return mergeCoverage(app.playback).map(([start_ms, end_ms]) => ({ start_ms, end_ms }));
}

function coverageRatio() {
  if (!app.session) return 0;
  const duration = app.session.candidate.media.duration_ms;
  if (!duration) return 1;
  const covered = mergeCoverage(app.playback).reduce((total, [start, end]) => total + end - start, 0);
  return Math.min(1, covered / duration);
}

function renderCoverage() {
  if (!app.session) return;
  const ratio = coverageRatio();
  const percent = Math.floor(ratio * 100);
  $("#coverage-percent").textContent = `${percent}%`;
  $("#playback-fill").style.width = `${ratio * 100}%`;
  const video = $("#source-video");
  $("#playback-time").textContent = `${formatTime(video.currentTime * 1000)} / ${formatTime(app.session.candidate.media.duration_ms)}`;
}

function playbackSetup() {
  const video = $("#source-video");
  if (!video.dataset.ready) {
    video.src = `/api/media?token=${encodeURIComponent(app.token)}`;
    video.dataset.ready = "true";
    video.addEventListener("play", () => { app.lastPlaybackTime = video.currentTime * 1000; });
    video.addEventListener("seeking", () => { app.lastPlaybackTime = null; });
    video.addEventListener("seeked", () => { app.lastPlaybackTime = video.currentTime * 1000; });
    video.addEventListener("timeupdate", () => {
      const current = video.currentTime * 1000;
      if (!video.seeking && !video.paused && app.lastPlaybackTime !== null) {
        const delta = current - app.lastPlaybackTime;
        if (delta > 0 && delta <= 1600) app.playback.push([app.lastPlaybackTime, current]);
      }
      app.lastPlaybackTime = current;
      app.playback = mergeCoverage(app.playback);
      renderCoverage();
      scheduleDraft();
    });
    video.addEventListener("ended", () => {
      const duration = app.session.candidate.media.duration_ms;
      app.playback.push([Math.max(0, duration - 1200), duration]);
      app.playback = mergeCoverage(app.playback);
      renderCoverage();
      scheduleDraft();
    });
  }
}

function savedTranscriptDraft() {
  return app.session.transcript_draft ? app.session.transcript_draft.draft : null;
}

function makeOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function renderSegments() {
  const list = $("#segment-list");
  list.replaceChildren();
  const current = transcriptHead();
  const editable = current && current.state === "in_review";
  const draft = savedTranscriptDraft();
  const byId = new Map((draft?.decisions || []).map((item) => [item.segment_id, item]));
  for (const segment of app.session.candidate.candidate.segments) {
    const decision = byId.get(segment.segment_id) || {};
    const row = document.createElement("article");
    row.className = `segment-row${segment.risk_flags.length ? " has-risk" : ""}`;
    row.dataset.segmentId = segment.segment_id;

    const time = document.createElement("div");
    time.className = "time-cell";
    const play = document.createElement("button");
    play.type = "button";
    play.textContent = `▶ ${formatTime(segment.start_ms)}`;
    play.addEventListener("click", () => {
      const video = $("#source-video");
      video.currentTime = segment.start_ms / 1000;
      video.play().catch((error) => toast(error.message, true));
    });
    const times = document.createElement("div");
    times.className = "time-inputs";
    for (const [kind, value] of [["start", decision.start_ms ?? segment.start_ms], ["end", decision.end_ms ?? segment.end_ms]]) {
      const input = document.createElement("input");
      input.className = `${kind}-ms`;
      input.inputMode = "numeric";
      input.value = value;
      input.disabled = !editable;
      input.setAttribute("aria-label", `${kind === "start" ? "开始" : "结束"}毫秒`);
      times.append(input);
    }
    time.append(play, times);

    const raw = document.createElement("div");
    raw.className = "text-cell";
    raw.textContent = segment.raw_text;

    const suggested = document.createElement("div");
    suggested.className = "text-cell";
    const suggestionText = document.createElement("div");
    suggestionText.className = "suggestion-text";
    suggestionText.textContent = segment.suggested_text;
    suggested.append(suggestionText);
    if (segment.suggestion_reason) {
      const reason = document.createElement("small");
      reason.textContent = segment.suggestion_reason;
      suggested.append(reason);
    }
    if (segment.risk_flags.length) {
      const flags = document.createElement("div");
      flags.className = "risk-flags";
      for (const flag of segment.risk_flags) {
        const badge = document.createElement("span");
        badge.textContent = flag;
        flags.append(badge);
      }
      suggested.append(flags);
    }

    const response = document.createElement("div");
    response.className = "decision-cell";
    const select = document.createElement("select");
    select.className = "decision";
    select.disabled = !editable;
    select.append(
      makeOption("", "选择你的决定…"),
      makeOption("keep_raw", "保留原始 ASR"),
      makeOption("accept_suggestion", "接受机器建议"),
      makeOption("human_corrected", "我已人工改写"),
      makeOption("remove_false_positive", "删除误识别")
    );
    select.value = decision.decision || "";
    const text = document.createElement("textarea");
    text.className = "human-text";
    text.rows = 2;
    text.disabled = !editable;
    text.value = decision.text || decision.reason || "";
    const updateTextMode = () => {
      const needsText = ["human_corrected", "remove_false_positive"].includes(select.value);
      text.hidden = !needsText;
      text.placeholder = select.value === "remove_false_positive" ? "说明为什么是误识别" : "输入你听看核对后的文字";
    };
    select.addEventListener("change", () => { updateTextMode(); scheduleDraft(); });
    text.addEventListener("input", scheduleDraft);
    $$("input", times).forEach((input) => input.addEventListener("input", scheduleDraft));
    updateTextMode();
    response.append(select, text);
    row.append(time, raw, suggested, response);
    list.append(row);
  }
}

function addInsertion(value = {}) {
  const row = document.createElement("div");
  row.className = "insertion-row";
  const fields = [
    ["start_ms", "开始 ms"], ["end_ms", "结束 ms"], ["text", "补录文字"], ["reason", "发现依据"],
  ];
  for (const [name, placeholder] of fields) {
    const input = document.createElement("input");
    input.className = name;
    input.placeholder = placeholder;
    input.value = value[name] ?? "";
    input.addEventListener("input", scheduleDraft);
    row.append(input);
  }
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "button button-quiet";
  remove.textContent = "移除";
  remove.addEventListener("click", () => { row.remove(); scheduleDraft(); });
  row.append(remove);
  $("#insertion-list").append(row);
}

function renderInsertions() {
  $("#insertion-list").replaceChildren();
  for (const insertion of savedTranscriptDraft()?.insertions || []) addInsertion(insertion);
}

function collectDecisions(requireComplete = false) {
  return $$(".segment-row").map((row) => {
    const decision = $(".decision", row).value;
    if (requireComplete && !decision) throw new Error("每一个原始片段都必须选择决定。");
    const result = {
      segment_id: row.dataset.segmentId,
      decision,
      start_ms: Number($(".start-ms", row).value),
      end_ms: Number($(".end-ms", row).value),
    };
    if (decision === "human_corrected") result.text = $(".human-text", row).value.trim();
    if (decision === "remove_false_positive") result.reason = $(".human-text", row).value.trim();
    return result;
  });
}

function collectInsertions() {
  return $$(".insertion-row").map((row) => ({
    start_ms: Number($(".start_ms", row).value),
    end_ms: Number($(".end_ms", row).value),
    text: $(".text", row).value.trim(),
    reason: $(".reason", row).value.trim(),
  }));
}

function collectTranscriptDraft() {
  return {
    decisions: collectDecisions(false),
    insertions: collectInsertions(),
    playback_coverage: coverageObjects(),
    checks: {
      segments_complete: $("#segments-complete").checked,
      missing_speech_resolved: $("#missing-resolved").checked,
      false_positive_speech_resolved: $("#false-positive-resolved").checked,
      timing_resolved: $("#timing-resolved").checked,
    },
  };
}

function scheduleDraft() {
  clearTimeout(app.draftTimer);
  const current = transcriptHead();
  if (!current || current.state !== "in_review") return;
  app.draftTimer = setTimeout(async () => {
    try {
      await api("/api/drafts", {
        method: "POST",
        body: {
          entity_type: "transcript",
          entity_id: app.session.transcript_entity_id,
          base_revision: current.revision,
          draft: collectTranscriptDraft(),
        },
      });
    } catch (error) {
      toast(`草稿未保存：${error.message}`, true);
    }
  }, 700);
}

function hydrateDraftChecks() {
  const draft = savedTranscriptDraft();
  app.playback = (draft?.playback_coverage || []).map((item) => [item.start_ms, item.end_ms]);
  $("#segments-complete").checked = Boolean(draft?.checks?.segments_complete);
  $("#missing-resolved").checked = Boolean(draft?.checks?.missing_speech_resolved);
  $("#false-positive-resolved").checked = Boolean(draft?.checks?.false_positive_speech_resolved);
  $("#timing-resolved").checked = Boolean(draft?.checks?.timing_resolved);
  renderCoverage();
}

function formalContent() {
  const current = transcriptHead();
  return current?.state === "source_verified" ? current.payload.content : null;
}

function renderEventForm() {
  const transcript = transcriptHead();
  const unlocked = transcript?.state === "source_verified";
  const current = eventHead();
  $("#event-id").value = "";
  $("#event-start").value = "";
  $("#event-end").value = "";
  $("#event-modality").value = "language";
  $("#event-boundary").value = "";
  $("#event-visual").value = "";
  $("#event-value").value = "";
  $("#event-focus").value = "";
  $("#event-visual-timestamps").value = "";
  const mediaReview = app.session.media_review || {};
  $("#event-visual-basis").value = mediaReview.visual_basis_default || "source_page";
  $("#event-state").textContent = current?.state || (unlocked ? "ready" : "locked");
  $("#event-form").querySelectorAll("input, textarea, select, button").forEach((item) => { item.disabled = !unlocked; });
  const container = $("#event-segments");
  container.replaceChildren();
  if (!unlocked) {
    container.textContent = "正式转写通过后开放。";
    return;
  }
  const content = transcript.payload.content;
  for (const segment of content.segments) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = segment.segment_id;
    checkbox.addEventListener("change", updateEventRangeFromSegments);
    const timestamp = document.createElement("code");
    timestamp.textContent = `${formatTime(segment.start_ms)}–${formatTime(segment.end_ms)}`;
    const text = document.createElement("span");
    text.textContent = segment.text;
    label.append(checkbox, timestamp, text);
    container.append(label);
  }
  if (current) {
    $("#event-id").value = current.entity_id;
    const value = current.payload.content;
    $("#event-start").value = value.start_ms;
    $("#event-end").value = value.end_ms;
    $("#event-modality").value = value.modality;
    $("#event-boundary").value = value.evidence_boundary;
    $("#event-visual").value = value.evidence_window.visual_observation || "";
    const visualReview = value.evidence_window.visual_review || {};
    $("#event-visual-basis").value = visualReview.review_basis || (mediaReview.visual_basis_default || "source_page");
    $("#event-visual-timestamps").value = (visualReview.timestamps_ms || []).join("\n");
    $("#event-value").value = value.viewing_value || "";
    $("#event-focus").value = value.watch_focus || "";
    const selected = new Set(value.evidence_window.segment_ids || []);
    $$("input[type=checkbox]", container).forEach((item) => { item.checked = selected.has(item.value); });
  } else {
    selectAllEventSegments();
  }
  $("#save-event-draft").disabled = !unlocked || Boolean(current);
  $("#verify-event").disabled = !current || current.state !== "draft";
  updateVisualReviewControls();
}

function updateVisualReviewControls() {
  const mediaKind = app.session.media_review?.kind || "unknown";
  const localMediaOption = $('#event-visual-basis option[value="local_media"]');
  localMediaOption.disabled = mediaKind !== "video";
  if (localMediaOption.disabled && $("#event-visual-basis").value === "local_media") {
    $("#event-visual-basis").value = "source_page";
  }
  const enabled = ["visual", "multimodal"].includes($("#event-modality").value);
  $("#event-visual-review").hidden = !enabled;
  if (!enabled) return;
  const basis = $("#event-visual-basis").value;
  if (basis === "source_page") {
    $("#event-visual-basis-note").textContent = "画面核对将绑定当前来源页面和这些时间点；保存前请确认页面确为同一来源视频。";
  } else if (mediaKind === "video") {
    $("#event-visual-basis-note").textContent = "画面核对将绑定当前本地视频的 SHA-256 和这些时间点。";
  } else {
    $("#event-visual-basis-note").textContent = "当前本地媒体不含可核对画面，不能作为视觉依据。";
  }
}

function selectAllEventSegments() {
  $$("#event-segments input[type=checkbox]").forEach((item) => { item.checked = true; });
  updateEventRangeFromSegments();
}

function updateEventRangeFromSegments() {
  const formal = formalContent();
  if (!formal) return;
  const selected = new Set($$("#event-segments input:checked").map((item) => item.value));
  const segments = formal.segments.filter((item) => selected.has(item.segment_id));
  if (segments.length) {
    $("#event-start").value = Math.min(...segments.map((item) => item.start_ms));
    $("#event-end").value = Math.max(...segments.map((item) => item.end_ms));
  }
}

function collectEventContent() {
  const content = {
    start_ms: Number($("#event-start").value),
    end_ms: Number($("#event-end").value),
    modality: $("#event-modality").value,
    segment_ids: $$("#event-segments input:checked").map((item) => item.value),
    evidence_boundary: $("#event-boundary").value.trim(),
    visual_observation: $("#event-visual").value.trim(),
    viewing_value: $("#event-value").value.trim(),
    watch_focus: $("#event-focus").value.trim(),
  };
  if (["visual", "multimodal"].includes(content.modality)) {
    content.visual_review_basis = $("#event-visual-basis").value;
    content.visual_timestamps_ms = collectVisualTimestamps();
  }
  return content;
}

function renderClaimForm() {
  const events = eventHeads().filter((item) => item.state === "source_verified");
  const unlocked = events.length > 0;
  const current = claimHead();
  $("#claim-id").value = "";
  $("#claim-topic").value = "";
  $("#claim-key").value = "";
  $("#claim-symptoms").value = "";
  $("#claim-applicability").value = "";
  $("#claim-mechanism").value = "";
  $("#claim-correction").value = "";
  $("#claim-exclusions").value = "";
  $("#claim-confidence").value = "low";
  $("#claim-training").value = "";
  $("#claim-aliases").value = "";
  $("#claim-state").textContent = current?.state || (unlocked ? "ready" : "locked");
  const supports = $("#claim-supports");
  supports.replaceChildren();
  if (!unlocked) supports.textContent = "来源事实通过后开放。";
  for (const event of events) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = event.entity_id;
    const time = document.createElement("code");
    time.textContent = `${formatTime(event.payload.content.start_ms)}–${formatTime(event.payload.content.end_ms)}`;
    const boundary = document.createElement("span");
    boundary.textContent = event.payload.content.evidence_boundary;
    label.append(checkbox, time, boundary);
    supports.append(label);
  }
  if (current) {
    $("#claim-id").value = current.entity_id;
    const value = current.payload.content;
    $("#claim-topic").value = value.topic || "";
    $("#claim-symptoms").value = (value.symptoms || []).join("\n");
    $("#claim-applicability").value = (value.applicability || []).join("\n");
    $("#claim-mechanism").value = value.mechanism || "";
    $("#claim-correction").value = value.correction_direction || "";
    $("#claim-exclusions").value = (value.exclusions || []).join("\n");
    $("#claim-confidence").value = value.confidence || "low";
    $("#claim-training").value = value.training_method || "";
    $("#claim-aliases").value = (value.aliases || []).join("\n");
    const selected = new Set(value.support_event_ids || []);
    $$("input[type=checkbox]", supports).forEach((item) => { item.checked = selected.has(item.value); });
  }
  const fixed = current && ["source_verified", "domain_approved", "published"].includes(current.state);
  $$("#claim-form input:not([type=hidden]), #claim-form textarea, #claim-form select").forEach((item) => { item.disabled = !unlocked || fixed; });
  $$("#claim-supports input").forEach((item) => { item.disabled = !unlocked || fixed; });
  $("#save-claim-draft").disabled = !unlocked || Boolean(current);
  $("#source-verify-claim").disabled = !current || current.state !== "draft";
  $("#domain-approve-claim").disabled = !current || current.state !== "source_verified";
  $("#publish-claim").disabled = !current || current.state !== "domain_approved";
}

function collectClaimContent() {
  return {
    topic: $("#claim-topic").value.trim(),
    semantic_key: $("#claim-key").value.trim(),
    symptoms: lines($("#claim-symptoms").value),
    applicability: lines($("#claim-applicability").value),
    mechanism: $("#claim-mechanism").value.trim(),
    correction_direction: $("#claim-correction").value.trim(),
    exclusions: lines($("#claim-exclusions").value),
    confidence: $("#claim-confidence").value,
    training_method: $("#claim-training").value.trim(),
    aliases: lines($("#claim-aliases").value),
    support_event_ids: $$("#claim-supports input:checked").map((item) => item.value),
  };
}

function renderHistory() {
  const container = $("#history-list");
  container.replaceChildren();
  if (!app.session.events.length) {
    container.textContent = "账本还没有事件。先创建候选，再逐级审核。";
    return;
  }
  [...app.session.events].reverse().forEach((event) => {
    const item = document.createElement("article");
    item.className = "history-item";
    const state = document.createElement("code");
    state.textContent = `${event.from_state} → ${event.to_state}`;
    const identity = document.createElement("div");
    const action = document.createElement("strong");
    action.textContent = `${event.entity_type} / ${event.action}`;
    const id = document.createElement("code");
    id.textContent = `${event.entity_id}\n${event.event_id}`;
    identity.append(action, id);
    const meta = document.createElement("div");
    const time = document.createElement("time");
    time.textContent = event.occurred_at;
    const who = document.createElement("code");
    who.textContent = event.reviewer_id;
    meta.append(time, document.createElement("br"), who);
    item.append(state, identity, meta);
    container.append(item);
  });
}

function renderSpine() {
  const transcript = transcriptHead();
  const event = eventHead();
  const claim = claimHead();
  const done = new Set(["candidate"]);
  let current = "corrected";
  let stale = false;
  if (transcript?.state === "in_review") current = "corrected";
  if (transcript?.state === "source_verified") {
    done.add("corrected"); done.add("complete"); current = "event";
  }
  if (transcript?.state === "stale") stale = true;
  if (event?.state === "source_verified") {
    done.add("event"); current = "claim";
  }
  if (event?.state === "stale") stale = true;
  if (claim?.state === "domain_approved") {
    done.add("claim"); current = "published";
  }
  if (claim?.state === "published") {
    done.add("claim"); done.add("published"); current = "";
  }
  if (claim?.state === "stale") stale = true;
  $$("#evidence-spine li").forEach((item) => {
    item.classList.toggle("is-done", done.has(item.dataset.stage));
    item.classList.toggle("is-current", item.dataset.stage === current);
    item.classList.toggle("is-stale", stale && item.dataset.stage === current);
  });
}

function applyControlStates() {
  const transcript = transcriptHead();
  $("#begin-review").disabled = transcript?.state !== "candidate";
  $("#preview-transcript").disabled = transcript?.state !== "in_review";
  $("#verify-transcript").disabled = transcript?.state !== "in_review";
  const editable = transcript?.state === "in_review";
  $$("#completeness-title ~ * input, .check-stack input").forEach((item) => { item.disabled = !editable; });
  $("#add-insertion").disabled = !editable;
}

function renderSession() {
  const candidate = app.session.candidate;
  $("#source-kicker").textContent = `${candidate.source.platform} / real candidate / unapproved`;
  $("#source-title").textContent = candidate.source.title;
  $("#media-hash").textContent = candidate.media.sha256.slice(0, 12);
  $("#source-status").textContent = candidate.evidence_status;
  $("#source-id").textContent = candidate.source.source_id;
  $("#source-duration").textContent = `${formatTime(candidate.media.duration_ms)} / ${candidate.media.duration_ms} ms`;
  $("#source-link").href = candidate.source.canonical_url;
  playbackSetup();
  renderSegments();
  renderInsertions();
  hydrateDraftChecks();
  renderEventForm();
  renderClaimForm();
  renderHistory();
  renderSpine();
  applyControlStates();
}

async function loadSession() {
  if (!app.token) throw new Error("缺少本地会话令牌。请使用终端输出的完整地址。 ");
  app.session = await api("/api/session");
  app.csrf = app.session.csrf_token;
  renderSession();
}

function confirmFormal(title, copy, impact, action) {
  reviewer();
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-copy").textContent = copy;
  $("#confirm-impact").textContent = impact;
  $("#confirm-human").checked = false;
  $("#confirm-submit").disabled = true;
  app.confirmAction = action;
  dialog.showModal();
}

async function refreshAfter(message) {
  await loadSession();
  toast(message);
}

async function beginReview() {
  const current = transcriptHead();
  confirmFormal(
    "开始人工审核",
    "这个动作只确认由你开始逐段核对，不会批准转写或主张。",
    "写入一条 in_review 事件；之后的编辑会自动保存为可恢复草稿。",
    async () => {
      await api("/api/transcript/begin", {
        method: "POST",
        body: { reviewer_id: reviewer(), human_confirmation: true, ...expectedFields(current) },
      });
      await refreshAfter("人工审核已开始。候选仍不是回答证据。");
    }
  );
}

async function previewTranscript() {
  const result = await api("/api/transcript/preview", {
    method: "POST",
    body: { decisions: collectDecisions(true), insertions: collectInsertions() },
  });
  $("#projection-result").textContent = `投影 ${result.formal_projection.formal_projection_sha256} · ${result.formal_projection.segments.length} 段 · 尚未批准`;
  toast("正式投影结构有效，但完整性门禁尚未执行。");
}

async function verifyTranscript() {
  const current = transcriptHead();
  const decisions = collectDecisions(true);
  const checks = {
    segments_complete: $("#segments-complete").checked,
    missing_speech_resolved: $("#missing-resolved").checked,
    false_positive_speech_resolved: $("#false-positive-resolved").checked,
    timing_resolved: $("#timing-resolved").checked,
  };
  if (Object.values(checks).some((value) => !value)) throw new Error("四项完整性确认必须全部勾选。");
  if (coverageRatio() < 0.999) throw new Error("原视频尚未完整自然播放，不能确认正式转写。");
  confirmFormal(
    "确认正式转写",
    "你正在确认每段文字、漏句、误识别、时间边界，并证明已完整播放对应原视频。",
    "这只批准来源文字事实，不批准任何羽毛球技术结论。之后修改文字或时间会使下游证据失效。",
    async () => {
      const body = {
        reviewer_id: reviewer(), human_confirmation: true, ...expectedFields(current),
        decisions, insertions: collectInsertions(),
        attestation: {
          review_basis: "local_media",
          full_media_reviewed: true,
          playback_coverage: coverageObjects(),
          segments_complete: checks.segments_complete,
          missing_speech_resolved: checks.missing_speech_resolved,
          false_positive_speech_resolved: checks.false_positive_speech_resolved,
          timing_resolved: checks.timing_resolved,
          no_usable_speech_confirmed: false,
        },
      };
      const result = await api("/api/transcript/verify", { method: "POST", body });
      await refreshAfter(`正式转写已确认：${result.compiled.formal_projection.formal_projection_sha256.slice(0, 12)}…`);
    }
  );
}

async function transitionEvent(action) {
  const current = eventHead();
  const body = {
    entity_type: "teaching_event",
    entity_id: $("#event-id").value,
    action,
    content: collectEventContent(),
    ...expectedFields(current),
  };
  if (action === "create_draft") {
    const result = await api("/api/entities/transition", { method: "POST", body });
    $("#event-id").value = result.head.entity_id;
    await refreshAfter("事件候选已保存；它还不是来源事实。");
    return;
  }
  confirmFormal(
    "确认来源事实",
    "你正在确认所选时间窗口确实说出或展示了表单中的内容。",
    "这会批准 teaching event，但仍不会批准由它归纳出的羽毛球领域主张。",
    async () => {
      await api("/api/entities/transition", {
        method: "POST",
        body: { ...body, reviewer_id: reviewer(), human_confirmation: true },
      });
      await refreshAfter("教学事件已完成来源核对。");
    }
  );
}

async function transitionClaim(action) {
  const current = claimHead();
  const labels = {
    source_verify: ["确认来源支持", "确认支持事件确实足以支撑这条主张的来源事实。", "这不会批准羽毛球归纳本身。"],
    domain_approve: ["批准领域判断", "确认这条归纳在所写适用条件和排除边界内是正确的羽毛球判断。", "这是领域质量门；自动系统不能替你执行。"],
    publish: ["批准进入 publication", "确认当前主张可进入净化后的 shadow publication。", "完整转写和审核身份不会公开；当前仍不会切换稳定 v2 Skill。"],
  };
  const body = {
    entity_type: "semantic_claim",
    entity_id: $("#claim-id").value,
    action,
    content: collectClaimContent(),
    ...expectedFields(current),
  };
  if (action === "create_draft") {
    const result = await api("/api/entities/transition", { method: "POST", body });
    $("#claim-id").value = result.head.entity_id;
    await refreshAfter("主张候选已保存；它还不能进入回答。");
    return;
  }
  const [title, copy, impact] = labels[action];
  confirmFormal(title, copy, impact, async () => {
    await api("/api/entities/transition", {
      method: "POST",
      body: { ...body, reviewer_id: reviewer(), human_confirmation: true },
    });
    await refreshAfter(`${title}已写入 append-only 账本。`);
  });
}

function bindEvents() {
  $$(".view-tab").forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.view)));
  $("#add-insertion").addEventListener("click", () => addInsertion());
  $("#begin-review").addEventListener("click", () => beginReview().catch((error) => toast(error.message, true)));
  $("#preview-transcript").addEventListener("click", () => previewTranscript().catch((error) => toast(error.message, true)));
  $("#verify-transcript").addEventListener("click", () => verifyTranscript().catch((error) => toast(error.message, true)));
  $("#event-modality").addEventListener("change", updateVisualReviewControls);
  $("#event-visual-basis").addEventListener("change", updateVisualReviewControls);
  $$(".check-stack input").forEach((item) => item.addEventListener("change", scheduleDraft));
  $("#save-event-draft").addEventListener("click", () => transitionEvent("create_draft").catch((error) => toast(error.message, true)));
  $("#verify-event").addEventListener("click", () => transitionEvent("source_verify").catch((error) => toast(error.message, true)));
  $("#save-claim-draft").addEventListener("click", () => transitionClaim("create_draft").catch((error) => toast(error.message, true)));
  $("#source-verify-claim").addEventListener("click", () => transitionClaim("source_verify").catch((error) => toast(error.message, true)));
  $("#domain-approve-claim").addEventListener("click", () => transitionClaim("domain_approve").catch((error) => toast(error.message, true)));
  $("#publish-claim").addEventListener("click", () => transitionClaim("publish").catch((error) => toast(error.message, true)));
  $("#refresh-session").addEventListener("click", () => loadSession().then(() => toast("已读取最新账本。")) .catch((error) => toast(error.message, true)));
  $("#preview-publication").addEventListener("click", async () => {
    try {
      const publication = await api("/api/publication-preview");
      const preview = $("#publication-preview");
      preview.textContent = JSON.stringify(publication, null, 2);
      preview.hidden = !preview.hidden;
    } catch (error) { toast(error.message, true); }
  });
  $("#confirm-human").addEventListener("change", (event) => { $("#confirm-submit").disabled = !event.target.checked; });
  $("#confirm-submit").addEventListener("click", async () => {
    const action = app.confirmAction;
    if (!action || !$("#confirm-human").checked) return;
    $("#confirm-submit").disabled = true;
    try {
      await action();
      $("#confirm-dialog").close();
    } catch (error) {
      toast(error.message, true);
      $("#confirm-submit").disabled = false;
    } finally {
      app.confirmAction = null;
      $("#confirm-human").checked = false;
    }
  });
  document.addEventListener("keydown", (event) => {
    const tag = document.activeElement?.tagName;
    if (["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(tag)) return;
    const video = $("#source-video");
    if (event.code === "Space") {
      event.preventDefault();
      if (video.paused) video.play().catch((error) => toast(error.message, true)); else video.pause();
    } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      video.currentTime = Math.max(0, Math.min(video.duration || Infinity, video.currentTime + (event.key === "ArrowLeft" ? -2 : 2)));
    }
  });
}

bindEvents();
$("#reviewer-id").value = localStorage.getItem("v3-reviewer-id") || "";
loadSession().catch((error) => toast(error.message, true));
