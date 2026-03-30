/**
 * VideoTool API Proxy — Cloudflare Worker
 *
 * Header-injection reverse proxy for Groq (transcription) and Anthropic (beats).
 * Adds API keys from secrets and forwards requests. Streams request/response bodies
 * without buffering — supports large audio file uploads to Groq.
 *
 * Deploy: wrangler deploy
 * Secrets: wrangler secret put GROQ_API_KEY && wrangler secret put ANTHROPIC_API_KEY
 */

// NOTE: CORS is permissive by design — this is a public API proxy for VideoTool
// desktop/web clients. Rate limiting (RATE_LIMIT_PER_DAY) is the primary abuse control.
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, x-api-key, anthropic-version",
};

export default {
  async fetch(request, env) {
    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const path = url.pathname;

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

    // ── Groq proxy ─────────────────────────────────────────────────
    if (path.startsWith("/groq/")) {
      if (!env.GROQ_API_KEY) {
        return jsonResponse({ error: "GROQ_API_KEY not configured" }, 500);
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

