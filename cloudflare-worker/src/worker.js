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

// NOTE: CORS is permissive by design — this is a public API proxy for VideoTool
// desktop/web clients. Auth token + rate limiting are the abuse controls.
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, x-api-key, anthropic-version, X-Proxy-Token",
};

export default {
  async fetch(request, env) {
    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    // Authenticate proxy requests with a shared token (stored as CF secret).
    // Health check is excluded so monitoring works without credentials.
    if (path.startsWith("/groq/") || path.startsWith("/anthropic/")) {
      if (env.PROXY_AUTH_TOKEN) {
        const token = request.headers.get("X-Proxy-Token");
        if (token !== env.PROXY_AUTH_TOKEN) {
          return jsonResponse({ error: "Unauthorized" }, 401);
        }
      }
    }

    // Simple IP-based rate limiting via KV (if bound) — otherwise skip
    if (env.RATE_LIMITS) {
      const ip = request.headers.get("cf-connecting-ip") || "unknown";
      const today = new Date().toISOString().slice(0, 10);
      const key = `ratelimit:${ip}:${today}`;
      const count = parseInt(await env.RATE_LIMITS.get(key) || "0", 10);
      const limit = parseInt(env.RATE_LIMIT_PER_DAY || "10", 10);

      if (count >= limit) {
        return jsonResponse({ error: "Daily limit reached. Try again tomorrow." }, 429);
      }

      // Count both Groq (transcription) and Anthropic (beat detection) requests
      if (path.startsWith("/groq/") || path.startsWith("/anthropic/")) {
        await env.RATE_LIMITS.put(key, String(count + 1), { expirationTtl: 86400 });
      }
    }

    // ── Event tracking ────────────────────────────────────────────
    if (path === "/track") {
      if (!env.RATE_LIMITS) {
        return jsonResponse({ error: "KV not configured" }, 500);
      }
      const event = url.searchParams.get("event");
      const allowed = ["page_view", "download_mac_arm", "download_mac_x64", "download_win"];
      if (!event || !allowed.includes(event)) {
        return jsonResponse({ error: "Invalid event" }, 400);
      }
      const today = new Date().toISOString().slice(0, 10);
      const key = `stats:${event}:${today}`;
      const count = parseInt(await env.RATE_LIMITS.get(key) || "0", 10);
      await env.RATE_LIMITS.put(key, String(count + 1), { expirationTtl: 90 * 86400 });
      return jsonResponse({ ok: true });
    }

    // ── Stats dashboard ───────────────────────────────────────────
    if (path === "/stats") {
      if (!env.RATE_LIMITS) {
        return jsonResponse({ error: "KV not configured" }, 500);
      }
      const days = parseInt(url.searchParams.get("days") || "7", 10);
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
      return jsonResponse(stats);
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
        await env.RATE_LIMITS.put(key, String(count + 1), { expirationTtl: 90 * 86400 });
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

      return addCorsHeaders(response);
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
        await env.RATE_LIMITS.put(key, String(count + 1), { expirationTtl: 90 * 86400 });
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

      return addCorsHeaders(response);
    }

    // ── Health check ───────────────────────────────────────────────
    if (path === "/" || path === "/health") {
      return jsonResponse({ status: "ok", service: "vodtool-api" }); // matches deployed CF worker name
    }

    return jsonResponse({ error: "Not found" }, 404);
  },
};

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...CORS_HEADERS },
  });
}

function addCorsHeaders(response) {
  const newResponse = new Response(response.body, response);
  for (const [key, value] of Object.entries(CORS_HEADERS)) {
    newResponse.headers.set(key, value);
  }
  return newResponse;
}

