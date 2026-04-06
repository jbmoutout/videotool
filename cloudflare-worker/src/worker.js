/**
 * VideoTool API Proxy — Cloudflare Worker
 *
 * Header-injection reverse proxy for Groq (transcription) and Anthropic (beats).
 * Adds API keys from secrets and forwards requests. Streams request/response bodies
 * without buffering — supports large audio file uploads to Groq.
 *
 * Deploy: wrangler deploy
 * Secrets: wrangler secret put GROQ_API_KEY && wrangler secret put ANTHROPIC_API_KEY && wrangler secret put PROXY_AUTH_TOKEN
 */

// Public CORS is only needed for the landing site's analytics/stats pages.
// Sensitive proxy/share endpoints are intentionally not cross-origin accessible.
const PUBLIC_CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const MAX_SHARE_BYTES = 1024 * 1024;
const SHARE_ID_LENGTH = 32;
const SHARE_TTL_SECONDS = 90 * 86400;
const STATS_MAX_DAYS = 30;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: isPublicCorsPath(path) ? PUBLIC_CORS_HEADERS : {},
      });
    }

    // ── Event tracking (before rate limiter) ───────────────────────
    if (path === "/track") {
      if (!env.RATE_LIMITS) {
        return publicJsonResponse({ error: "KV not configured" }, 500);
      }
      const event = url.searchParams.get("event");
      const allowed = ["page_view", "download_mac_arm", "download_mac_x64", "download_win"];
      if (!event || !allowed.includes(event)) {
        return publicJsonResponse({ error: "Invalid event" }, 400);
      }
      const today = new Date().toISOString().slice(0, 10);
      const key = `stats:${event}:${today}`;
      const count = parseInt(await env.RATE_LIMITS.get(key) || "0", 10);
      await env.RATE_LIMITS.put(key, String(count + 1), { expirationTtl: SHARE_TTL_SECONDS });
      return publicJsonResponse({ ok: true });
    }

    // ── Stats dashboard ───────────────────────────────────────────
    if (path === "/stats") {
      if (!env.RATE_LIMITS) {
        return publicJsonResponse({ error: "KV not configured" }, 500);
      }
      const rawDays = parseInt(url.searchParams.get("days") || "7", 10);
      if (Number.isNaN(rawDays) || rawDays < 1 || rawDays > STATS_MAX_DAYS) {
        return publicJsonResponse(
          { error: `days must be an integer between 1 and ${STATS_MAX_DAYS}` },
          400,
        );
      }
      const days = rawDays;
      const events = ["page_view", "download_mac_arm", "download_mac_x64", "download_win", "api_groq", "api_anthropic"];
      const stats = {};
      for (let i = 0; i < days; i++) {
        const d = new Date();
        d.setDate(d.getDate() - i);
        const date = d.toISOString().slice(0, 10);
        stats[date] = {};
        for (const event of events) {
          const val = await env.RATE_LIMITS.get(`stats:${event}:${date}`);
          if (val) stats[date][event] = parseInt(val, 10);
        }
      }
      return publicJsonResponse(stats);
    }

    // Authenticate proxy requests with a shared token (stored as CF secret).
    if (path.startsWith("/groq/") || path.startsWith("/anthropic/")) {
      const authError = requireProxyAuth(request, env);
      if (authError) {
        return authError;
      }
    }

    if (path.startsWith("/groq/") || path.startsWith("/anthropic/")) {
      const rateLimitError = await enforceRateLimit(env, request, {
        bucket: "proxy",
        limit: parseInt(env.RATE_LIMIT_PER_DAY || "10", 10),
        windowSeconds: 86400,
        message: "Daily limit reached. Try again tomorrow.",
      });
      if (rateLimitError) {
        return rateLimitError;
      }
    }

    // ── Groq proxy ─────────────────────────────────────────────────
    if (path.startsWith("/groq/")) {
      if (!env.GROQ_API_KEY) {
        return jsonResponse({ error: "GROQ_API_KEY not configured" }, 500);
      }

      // Track API usage
      if (env.RATE_LIMITS) {
        const today = new Date().toISOString().slice(0, 10);
        const key = `stats:api_groq:${today}`;
        const count = parseInt(await env.RATE_LIMITS.get(key) || "0", 10);
        await env.RATE_LIMITS.put(key, String(count + 1), { expirationTtl: SHARE_TTL_SECONDS });
      }

      const groqPath = path.replace("/groq", "");
      const groqUrl = `https://api.groq.com/openai/v1${groqPath}${url.search}`;

      const headers = new Headers(request.headers);
      headers.set("Authorization", `Bearer ${env.GROQ_API_KEY}`);
      headers.delete("host");

      const response = await fetch(groqUrl, {
        method: request.method,
        headers,
        body: request.body,
      });

      return response;
    }

    // ── Anthropic proxy ────────────────────────────────────────────
    if (path.startsWith("/anthropic/")) {
      if (!env.ANTHROPIC_API_KEY) {
        return jsonResponse({ error: "ANTHROPIC_API_KEY not configured" }, 500);
      }

      // Track API usage
      if (env.RATE_LIMITS) {
        const today = new Date().toISOString().slice(0, 10);
        const key = `stats:api_anthropic:${today}`;
        const count = parseInt(await env.RATE_LIMITS.get(key) || "0", 10);
        await env.RATE_LIMITS.put(key, String(count + 1), { expirationTtl: SHARE_TTL_SECONDS });
      }

      const anthropicPath = path.replace("/anthropic", "");
      const anthropicUrl = `https://api.anthropic.com${anthropicPath}${url.search}`;

      const headers = new Headers(request.headers);
      headers.set("x-api-key", env.ANTHROPIC_API_KEY);
      headers.set("anthropic-version", "2023-06-01");
      headers.delete("host");

      const response = await fetch(anthropicUrl, {
        method: request.method,
        headers,
        body: request.body,
      });

      return response;
    }

    // ── Share: upload beats ──────────────────────────────────────────
    if (path === "/api/share" && request.method === "POST") {
      if (!env.RATE_LIMITS) {
        return jsonResponse({ error: "KV not configured" }, 500);
      }
      const authError = requireProxyAuth(request, env);
      if (authError) {
        return authError;
      }
      const rateLimitError = await enforceRateLimit(env, request, {
        bucket: "share-write",
        limit: parseInt(env.SHARE_WRITE_LIMIT_PER_HOUR || "20", 10),
        windowSeconds: 3600,
        message: "Share upload limit reached. Try again later.",
      });
      if (rateLimitError) {
        return rateLimitError;
      }
      try {
        const contentLength = parseInt(request.headers.get("Content-Length") || "0", 10);
        if (contentLength > MAX_SHARE_BYTES) {
          return jsonResponse({ error: "Payload too large (max 1MB)" }, 413);
        }
        const body = await readJsonBodyLimited(request, MAX_SHARE_BYTES);
        if (!body.beats || !Array.isArray(body.beats)) {
          return jsonResponse({ error: "Missing or invalid beats array" }, 400);
        }
        const id = await generateUniqueShareId(env);
        // Sanitize twitch_video_id to digits only (Twitch IDs are numeric)
        let twitchId = null;
        if (body.twitch_video_id && /^\d+$/.test(String(body.twitch_video_id))) {
          twitchId = String(body.twitch_video_id);
        }
        const record = {
          beats: body.beats,
          title: String(body.title || "Untitled").slice(0, 500),
          channel: body.channel ? String(body.channel).slice(0, 100) : null,
          twitch_video_id: twitchId,
          duration_seconds: typeof body.duration_seconds === "number" ? body.duration_seconds : null,
          created_at: new Date().toISOString(),
        };
        await env.RATE_LIMITS.put(`share:${id}`, JSON.stringify(record), {
          expirationTtl: SHARE_TTL_SECONDS,
        });
        const baseUrl = new URL(request.url);
        const viewerUrl = `${baseUrl.protocol}//${baseUrl.host}/v/${id}`;
        return jsonResponse({ id, url: viewerUrl });
      } catch (err) {
        if (err instanceof Error && err.message === "PAYLOAD_TOO_LARGE") {
          return jsonResponse({ error: "Payload too large (max 1MB)" }, 413);
        }
        if (err instanceof Error && err.message === "SHARE_ID_COLLISION") {
          return jsonResponse({ error: "Failed to allocate share ID" }, 503);
        }
        return jsonResponse({ error: "Invalid JSON body" }, 400);
      }
    }

    // ── Share: raw JSON (debug) ───────────────────────────────────────
    if (path.startsWith("/api/share/") && request.method === "GET") {
      if (!env.RATE_LIMITS) {
        return jsonResponse({ error: "KV not configured" }, 500);
      }
      const authError = requireProxyAuth(request, env);
      if (authError) {
        return authError;
      }
      const id = path.replace("/api/share/", "");
      if (!isValidShareId(id)) {
        return jsonResponse({ error: "Invalid share ID" }, 400);
      }
      const data = await env.RATE_LIMITS.get(`share:${id}`);
      if (!data) {
        return jsonResponse({ error: "Not found" }, 404);
      }
      return jsonResponse(JSON.parse(data));
    }

    // ── Share: serve web viewer ───────────────────────────────────────
    if (path.startsWith("/v/")) {
      if (!env.RATE_LIMITS) {
        return jsonResponse({ error: "KV not configured" }, 500);
      }
      const rateLimitError = await enforceRateLimit(env, request, {
        bucket: "share-read",
        limit: parseInt(env.SHARE_READ_LIMIT_PER_HOUR || "240", 10),
        windowSeconds: 3600,
        message: "Share view limit reached. Try again later.",
      });
      if (rateLimitError) {
        return rateLimitError;
      }
      const id = path.replace("/v/", "");
      if (!isValidShareId(id)) {
        return new Response("Not found", { status: 404, headers: { "Content-Type": "text/plain" } });
      }
      const data = await env.RATE_LIMITS.get(`share:${id}`);
      if (!data) {
        return new Response("Not found", { status: 404, headers: { "Content-Type": "text/plain" } });
      }
      const record = JSON.parse(data);
      const hostname = new URL(request.url).hostname;
      const html = buildViewerHtml(record, hostname);
      return new Response(html, {
        status: 200,
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Content-Security-Policy": buildViewerCsp(),
          "Referrer-Policy": "no-referrer",
          "X-Content-Type-Options": "nosniff",
        },
      });
    }

    // ── Health check ───────────────────────────────────────────────
    if (path === "/" || path === "/health") {
      return jsonResponse({ status: "ok", service: "vodtool-api" }); // matches deployed CF worker name
    }

    return jsonResponse({ error: "Not found" }, 404);
  },
};

function isPublicCorsPath(path) {
  return path === "/track" || path === "/stats";
}

function jsonResponse(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...extraHeaders },
  });
}

function publicJsonResponse(data, status = 200) {
  return jsonResponse(data, status, PUBLIC_CORS_HEADERS);
}

function requireProxyAuth(request, env) {
  if (!env.PROXY_AUTH_TOKEN) {
    return jsonResponse({ error: "PROXY_AUTH_TOKEN not configured" }, 500);
  }
  const token = request.headers.get("X-Proxy-Token");
  if (token !== env.PROXY_AUTH_TOKEN) {
    return jsonResponse({ error: "Unauthorized" }, 401);
  }
  return null;
}

async function enforceRateLimit(env, request, { bucket, limit, windowSeconds, message }) {
  if (!env.RATE_LIMITS) {
    return null;
  }
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const window = Math.floor(Date.now() / (windowSeconds * 1000));
  const key = `ratelimit:${bucket}:${ip}:${window}`;
  const count = parseInt(await env.RATE_LIMITS.get(key) || "0", 10);
  if (count >= limit) {
    return jsonResponse({ error: message }, 429);
  }
  await env.RATE_LIMITS.put(key, String(count + 1), {
    expirationTtl: windowSeconds + 60,
  });
  return null;
}

function isValidShareId(id) {
  return new RegExp(`^[a-f0-9]{${SHARE_ID_LENGTH}}$`).test(id);
}

async function generateUniqueShareId(env) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const id = crypto.randomUUID().replace(/-/g, "");
    const existing = await env.RATE_LIMITS.get(`share:${id}`);
    if (!existing) {
      return id;
    }
  }
  throw new Error("SHARE_ID_COLLISION");
}

async function readJsonBodyLimited(request, maxBytes) {
  if (!request.body) {
    throw new Error("INVALID_JSON");
  }
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    total += value.byteLength;
    if (total > maxBytes) {
      throw new Error("PAYLOAD_TOO_LARGE");
    }
    chunks.push(value);
  }

  const bodyBytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bodyBytes.set(chunk, offset);
    offset += chunk.byteLength;
  }

  try {
    return JSON.parse(new TextDecoder().decode(bodyBytes));
  } catch {
    throw new Error("INVALID_JSON");
  }
}

function buildViewerCsp() {
  return [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://player.twitch.tv",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "frame-src https://player.twitch.tv https://www.twitch.tv",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export {
  buildViewerCsp,
  enforceRateLimit,
  generateUniqueShareId,
  isValidShareId,
  readJsonBodyLimited,
  requireProxyAuth,
};

// ── Web viewer HTML template ──────────────────────────────────────

function escapeHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function buildViewerHtml(record, hostname) {
  const dataJson = JSON.stringify(record).replace(/<\//g, "<\\/");
  const title = escapeHtml(record.title || "Untitled");
  const channel = escapeHtml(record.channel || "");
  const topicCount = Array.isArray(record.beats) ? record.beats.length : 0;
  let beatCount = 0;
  if (Array.isArray(record.beats)) {
    for (const t of record.beats) {
      if (Array.isArray(t.beats)) beatCount += t.beats.length;
    }
  }
  const hasTwitch = !!record.twitch_video_id;

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VideoTool — ${title}</title>
<meta property="og:title" content="VideoTool — ${title}">
<meta property="og:description" content="${channel ? channel + " · " : ""}${topicCount} topics · ${beatCount} beats">
<meta property="og:type" content="website">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet">
${hasTwitch ? '<script src="https://player.twitch.tv/js/embed/v1.js"></scr' + 'ipt>' : ""}
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'JetBrains Mono', Monaco, 'Cascadia Code', 'Fira Code', 'Courier New', monospace; font-size: 13px; background: #0A0A0A; color: #C9C9C9; padding: 1rem; }

  .top-bar { display: flex; gap: 1rem; margin-bottom: 0.75rem; align-items: center; }
  .top-bar a { font-family: inherit; font-size: 12px; color: #555; text-decoration: none; }
  .top-bar a:hover { color: #C9C9C9; }
  .top-bar .status { color: #555; }
  .top-bar .title { color: #fff; font-weight: 500; }

  #twitch-embed { width: 100%; height: 240px; background: #000; margin-bottom: 0.5rem; }
  #twitch-embed iframe { width: 100%; height: 100%; }
  #no-video { display: flex; align-items: center; justify-content: flex-start; height: 60px; color: #444; font-size: 11px; margin-bottom: 0.5rem; }

  .timeline-toolbar { display: flex; align-items: center; gap: 0.4rem; padding: 0.25rem 0; }
  .timeline-toolbar button { font-family: inherit; font-size: 14px; width: 22px; height: 22px; line-height: 20px; text-align: center; color: #555; background: #111; border: 1px solid #222; border-radius: 2px; cursor: pointer; padding: 0; }
  .timeline-toolbar button:hover { color: #C9C9C9; border-color: #444; }
  .timeline-toolbar #zoom-label { font-size: 11px; color: #555; min-width: 2.2em; text-align: center; }
  .timeline-toolbar .zoom-hint { font-size: 10px; color: #333; margin-left: 0.4rem; }

  .timeline-wrap { display: flex; margin-bottom: 0.5rem; border: 1px solid #222; background: #111; }
  #timeline-labels { width: 240px; flex-shrink: 0; border-right: 1px solid #222; }
  .topic-label { height: 28px; display: flex; align-items: center; padding: 0 6px; font-size: 10px; color: #555; border-bottom: 1px solid #222; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  #timeline { flex: 1; overflow-x: auto; }
  #timeline-inner { position: relative; min-width: 100%; }
  .topic-row { position: relative; height: 28px; border-bottom: 1px solid #222; }
  .beat { position: absolute; top: 3px; height: 22px; border-radius: 2px; cursor: pointer; opacity: 0.85; transition: opacity 0.1s; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: 10px; line-height: 22px; padding: 0 4px; color: rgba(0,0,0,0.7); min-width: 2px; }
  .beat:hover { opacity: 1; z-index: 10; }

  .beat[data-type="highlight"]  { background: #c05050; }
  .beat[data-type="core"]       { background: #c0a030; }
  .beat[data-type="context"]    { background: #4080c0; }
  .beat[data-type="chat"]       { background: #8060c0; }
  .beat[data-type="transition"] { background: #40a060; }
  .beat[data-type="break"]      { background: #333333; }
  .beat[data-type="hook"]       { background: #c05050; }
  .beat[data-type="build"]      { background: #4080c0; }
  .beat[data-type="peak"]       { background: #c0a030; }
  .beat[data-type="resolution"] { background: #40a060; }

  #playhead { position: absolute; top: 0; bottom: 0; width: 1px; background: #fff; z-index: 20; pointer-events: none; }

  #hover-info { height: 2.4em; line-height: 2.4em; color: #555; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 0 0.25rem; }

  .legend { display: flex; gap: 1rem; margin-bottom: 0.5rem; flex-wrap: wrap; }
  .legend-item { display: flex; align-items: center; gap: 0.3rem; font-size: 11px; color: #555; }
  .legend-swatch { width: 12px; height: 12px; border-radius: 2px; }
</style>
</head>
<body>

<div class="top-bar">
  <a href="https://jbmoutout.github.io/videotool/">[videotool]</a>
  <span class="title">${title}</span>
  ${channel ? '<span class="status">' + channel + "</span>" : ""}
  <span id="status" class="status">loading...</span>
</div>

${hasTwitch ? '<div id="twitch-embed"></div>' : '<div id="no-video">no twitch VOD linked — timeline only</div>'}

<div class="legend">
  <div class="legend-item"><div class="legend-swatch" style="background:#c05050"></div>highlight</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#c0a030"></div>core</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#4080c0"></div>context</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#8060c0"></div>chat</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#40a060"></div>transition</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#333333"></div>break</div>
</div>

<div class="timeline-toolbar">
  <button id="zoom-out-btn">\u2212</button>
  <span id="zoom-label">1\u00d7</span>
  <button id="zoom-in-btn">+</button>
  <span class="zoom-hint">ctrl+scroll to zoom</span>
</div>
<div class="timeline-wrap">
  <div id="timeline-labels"></div>
  <div id="timeline">
    <div id="timeline-inner">
      <div id="playhead"></div>
    </div>
  </div>
</div>

<div id="hover-info">&nbsp;</div>

<script>
window.__SHARE_DATA = ${dataJson};
</script>
<script>
const data = window.__SHARE_DATA;
const timeline = document.getElementById("timeline");
const timelineInner = document.getElementById("timeline-inner");
const timelineLabels = document.getElementById("timeline-labels");
const playhead = document.getElementById("playhead");
const hoverInfo = document.getElementById("hover-info");
const statusEl = document.getElementById("status");

let duration = data.duration_seconds || 0;
let beats = data.beats || [];
let zoomLevel = 1;

// ── Player abstraction (Twitch or no-op) ──────────────────────────
const playerApi = {
  getCurrentTime: () => 0,
  seek: () => {},
  play: () => {},
  pause: () => {},
  isPaused: () => true,
  ready: false,
};

${hasTwitch ? `
// ── Twitch player (reads video ID from __SHARE_DATA, not template) ──
try {
  const _vid = data.twitch_video_id;
  const _host = window.location.hostname;
  if (typeof Twitch === "undefined") throw new Error("Twitch SDK not loaded");
  const twitchPlayer = new Twitch.Player("twitch-embed", {
    video: String(_vid),
    parent: [_host],
    width: "100%",
    height: 240,
    autoplay: false,
  });

  twitchPlayer.addEventListener(Twitch.Player.READY, () => {
    playerApi.ready = true;
    const d = twitchPlayer.getDuration();
    if (d > 0) duration = d;
    if (beats.length) render();
  });

  twitchPlayer.addEventListener(Twitch.Player.PLAY, () => {
    if (!rafId) updatePlayhead();
  });

  twitchPlayer.addEventListener(Twitch.Player.PAUSE, () => {
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    syncPlayhead();
  });

  twitchPlayer.addEventListener(Twitch.Player.SEEK, syncPlayhead);

  playerApi.getCurrentTime = () => twitchPlayer.getCurrentTime();
  playerApi.seek = (t) => twitchPlayer.seek(t);
  playerApi.play = () => twitchPlayer.play();
  playerApi.pause = () => twitchPlayer.pause();
  playerApi.isPaused = () => twitchPlayer.isPaused();
} catch (_e) {
  // Twitch embed failed (ad blocker, network error) — show timeline only
  const el = document.getElementById("twitch-embed");
  if (el) el.innerHTML = '<div style="color:#444;font-size:11px;padding:1rem">twitch player unavailable — timeline only</div>';
}
` : ""}

// ── Infer duration from beats if needed ───────────────────────────
if (!duration && beats.length) {
  let maxEnd = 0;
  for (const t of beats) {
    for (const b of t.beats) {
      if (b.end_s > maxEnd) maxEnd = b.end_s;
    }
  }
  duration = maxEnd;
}

statusEl.textContent = beats.length + " topics loaded";
if (beats.length) render();

// ── Rendering ─────────────────────────────────────────────────────
function getBaseW() { return timeline.clientWidth; }
function getContentW() { return getBaseW() * zoomLevel; }

function render() {
  timelineInner.querySelectorAll(".topic-row").forEach(el => el.remove());
  timelineLabels.innerHTML = "";
  if (!duration || !beats.length) return;

  const contentW = getContentW();
  timelineInner.style.width = contentW + "px";

  for (const topic of beats) {
    const label = document.createElement("div");
    label.className = "topic-label";
    label.textContent = topic.topic_label;
    label.title = topic.topic_label;
    timelineLabels.appendChild(label);

    const row = document.createElement("div");
    row.className = "topic-row";

    for (const b of topic.beats) {
      const el = document.createElement("div");
      el.className = "beat";
      el.dataset.type = b.type;
      const left = (b.start_s / duration) * contentW;
      const width = Math.max(2, ((b.end_s - b.start_s) / duration) * contentW);
      el.style.left = left + "px";
      el.style.width = width + "px";
      el.title = "[" + b.type + "] " + fmtTime(b.start_s) + "\\u2013" + fmtTime(b.end_s) + " (" + b.confidence + ")\\n" + b.label;
      el.textContent = b.label;

      el.addEventListener("click", () => {
        playerApi.seek(b.start_s);
        if (playerApi.isPaused() && playerApi.ready) playerApi.play();
      });
      el.addEventListener("mouseenter", () => {
        hoverInfo.textContent = "[" + b.type + "] " + fmtTime(b.start_s) + "\\u2013" + fmtTime(b.end_s) + " | " + b.label;
      });
      el.addEventListener("mouseleave", () => {
        hoverInfo.innerHTML = "&nbsp;";
      });

      row.appendChild(el);
    }
    timelineInner.appendChild(row);
  }
}

// ── Zoom controls ─────────────────────────────────────────────────
const zoomLabel = document.getElementById("zoom-label");
function setZoom(level) {
  const clamped = Math.max(1, Math.min(20, level));
  if (clamped === zoomLevel) return;
  zoomLevel = clamped;
  zoomLabel.textContent = zoomLevel.toFixed(1).replace(/\\.0$/, "") + "\\u00d7";
  if (beats.length) render();
  syncPlayhead();
}
document.getElementById("zoom-in-btn").addEventListener("click", () => setZoom(zoomLevel * 1.5));
document.getElementById("zoom-out-btn").addEventListener("click", () => setZoom(zoomLevel / 1.5));
timeline.addEventListener("wheel", (e) => {
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault();
    const scrollBefore = timeline.scrollLeft;
    const mouseX = e.clientX - timeline.getBoundingClientRect().left + scrollBefore;
    const oldZoom = zoomLevel;
    setZoom(zoomLevel * (e.deltaY < 0 ? 1.2 : 1 / 1.2));
    const ratio = zoomLevel / oldZoom;
    timeline.scrollLeft = mouseX * ratio - (e.clientX - timeline.getBoundingClientRect().left);
  }
}, { passive: false });

// ── Playhead sync ─────────────────────────────────────────────────
let rafId = null;
function updatePlayhead() {
  if (duration > 0) {
    playhead.style.left = ((playerApi.getCurrentTime() / duration) * getContentW()) + "px";
  }
  rafId = requestAnimationFrame(updatePlayhead);
}
function syncPlayhead() {
  if (duration > 0) {
    playhead.style.left = ((playerApi.getCurrentTime() / duration) * getContentW()) + "px";
  }
}

// ── Click-to-seek on timeline background ──────────────────────────
timeline.addEventListener("click", (e) => {
  if (e.target.classList.contains("beat")) return;
  const rect = timeline.getBoundingClientRect();
  const x = e.clientX - rect.left + timeline.scrollLeft;
  const pct = x / getContentW();
  playerApi.seek(pct * duration);
});

// ── Resize handling ───────────────────────────────────────────────
window.addEventListener("resize", () => { if (beats.length) render(); });

// ── Spacebar play/pause ───────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && e.target === document.body) {
    e.preventDefault();
    if (playerApi.isPaused()) playerApi.play(); else playerApi.pause();
  }
});

// ── Utils ─────────────────────────────────────────────────────────
function fmtTime(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return m + ":" + String(sec).padStart(2, "0");
}
</script>
</body>
</html>`;
}
