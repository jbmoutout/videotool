import test from "node:test";
import assert from "node:assert/strict";

import worker from "../src/worker.js";

function createKv(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    async get(key) {
      return store.has(key) ? store.get(key) : null;
    },
    async put(key, value) {
      store.set(key, value);
    },
  };
}

test("proxy routes fail closed when PROXY_AUTH_TOKEN is missing", async () => {
  const response = await worker.fetch(
    new Request("https://example.com/groq/audio/transcriptions", { method: "POST" }),
    {
      GROQ_API_KEY: "test-key",
      RATE_LIMITS: createKv(),
    },
  );

  assert.equal(response.status, 500);
  assert.match(await response.text(), /PROXY_AUTH_TOKEN not configured/);
});

test("stats rejects days outside the allowed range", async () => {
  const response = await worker.fetch(
    new Request("https://example.com/stats?days=31"),
    { RATE_LIMITS: createKv() },
  );

  assert.equal(response.status, 400);
  assert.match(await response.text(), /days must be an integer between 1 and 30/);
});

test("share upload also fails closed when PROXY_AUTH_TOKEN is missing", async () => {
  const payload = JSON.stringify({ beats: [] });
  const response = await worker.fetch(
    new Request("https://example.com/api/share", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
    }),
    { RATE_LIMITS: createKv() },
  );

  assert.equal(response.status, 500);
  assert.match(await response.text(), /PROXY_AUTH_TOKEN not configured/);
});

test("share upload enforces the payload cap without trusting Content-Length", async () => {
  const response = await worker.fetch(
    new Request("https://example.com/api/share", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Proxy-Token": "secret-token",
      },
      body: JSON.stringify({ beats: "x".repeat(2 * 1024 * 1024) }),
    }),
    {
      PROXY_AUTH_TOKEN: "secret-token",
      RATE_LIMITS: createKv(),
    },
  );

  assert.equal(response.status, 413);
  assert.match(await response.text(), /Payload too large/);
});

test("successful share uploads return full-length opaque IDs", async () => {
  const response = await worker.fetch(
    new Request("https://example.com/api/share", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Proxy-Token": "secret-token",
      },
      body: JSON.stringify({ beats: [] }),
    }),
    {
      PROXY_AUTH_TOKEN: "secret-token",
      RATE_LIMITS: createKv(),
    },
  );

  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.match(payload.id, /^[a-f0-9]{32}$/);
  assert.match(payload.url, /\/v\/[a-f0-9]{32}$/);
});

test("share viewer rejects malformed IDs", async () => {
  const response = await worker.fetch(
    new Request("https://example.com/v/not-a-real-share-id"),
    {
      RATE_LIMITS: createKv(),
    },
  );

  assert.equal(response.status, 404);
  assert.equal(await response.text(), "Not found");
});

test("share viewer responses include security headers", async () => {
  const shareId = "0123456789abcdef0123456789abcdef";
  const record = {
    beats: [{ topic_id: "topic_0000", topic_label: "Intro", beats: [] }],
    title: "Demo",
    channel: "Channel",
    twitch_video_id: "12345",
  };

  const response = await worker.fetch(
    new Request(`https://example.com/v/${shareId}`),
    {
      RATE_LIMITS: createKv({ [`share:${shareId}`]: JSON.stringify(record) }),
    },
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Type"), "text/html; charset=utf-8");
  assert.match(response.headers.get("Content-Security-Policy"), /frame-ancestors 'none'/);
  assert.equal(response.headers.get("Referrer-Policy"), "no-referrer");
  assert.equal(response.headers.get("X-Content-Type-Options"), "nosniff");

  const html = await response.text();
  assert.match(html, /Demo/);
  assert.match(html, /player\.twitch\.tv/);
});

test("share debug JSON route requires proxy auth", async () => {
  const shareId = "0123456789abcdef0123456789abcdef";
  const response = await worker.fetch(
    new Request(`https://example.com/api/share/${shareId}`),
    {
      PROXY_AUTH_TOKEN: "secret-token",
      RATE_LIMITS: createKv({ [`share:${shareId}`]: JSON.stringify({ beats: [] }) }),
    },
  );

  assert.equal(response.status, 401);
  assert.match(await response.text(), /Unauthorized/);
});
