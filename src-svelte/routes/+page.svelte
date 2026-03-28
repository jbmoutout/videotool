<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { open as openDialog } from "@tauri-apps/plugin-dialog";
  import { onMount, onDestroy } from "svelte";
  import { fly } from "svelte/transition";

  // ── types ────────────────────────────────────────────────────────────────────

  type Screen = "import" | "processing" | "results";

  interface ProgressMsg {
    step: number;
    total: number;
    pct: number;
    msg: string;
  }

  interface DoneMsg {
    done: boolean;
    project_dir: string;
    topic_count: number;
  }

  interface ErrorMsg {
    error: string;
    step: number;
  }

  interface Topic {
    topic_id: string;
    label: string;
    summary: string;
    duration_label: string;
    chunk_count: number;
  }

  // ── state ─────────────────────────────────────────────────────────────────────

  let screen = $state<Screen>("import");
  let dragOver = $state(false);
  let progress = $state<ProgressMsg | null>(null);
  let errorMsg = $state<string | null>(null);
  let topics = $state<Topic[]>([]);
  let projectDir = $state<string>("");
  let videoFileName = $state<string>("");

  // ── animation state ───────────────────────────────────────────────────────────

  const TITLE = "VODTOOL";
  let titleChars = $state("");
  let taglineVisible = $state(false);

  const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
  let spinnerIdx = $state(0);

  let displayMsg = $state("");
  let copiedId = $state<string | null>(null);

  // ── event listeners (cleaned up on destroy) ───────────────────────────────────

  let unlisteners: UnlistenFn[] = [];

  function registerListeners() {
    Promise.all([
      listen<ProgressMsg>("pipeline-progress", (e) => {
        progress = e.payload;
      }),
      listen<DoneMsg>("pipeline-done", async (e) => {
        projectDir = e.payload.project_dir;
        try {
          topics = await invoke<Topic[]>("load_topics", {
            projectDir: e.payload.project_dir,
          });
        } catch (err) {
          topics = [];
          errorMsg = String(err);
        }
        screen = "results";
      }),
      listen<ErrorMsg>("pipeline-error-msg", (e) => {
        errorMsg = e.payload.error;
        screen = "import";
      }),
      listen<string>("pipeline-error", (e) => {
        errorMsg = typeof e.payload === "string" ? e.payload : "Unknown error";
        screen = "import";
      }),
    ]).then((fns) => {
      unlisteners = fns;
    });
  }

  registerListeners();

  // ── title typewriter (import screen, runs once on mount) ──────────────────────

  onMount(() => {
    let i = 0;
    let taglineTimer: ReturnType<typeof setTimeout> | null = null;
    const iv = setInterval(() => {
      titleChars = TITLE.slice(0, ++i);
      if (i === TITLE.length) {
        clearInterval(iv);
        taglineTimer = setTimeout(() => {
          taglineVisible = true;
        }, 300);
      }
    }, 50);
    return () => {
      clearInterval(iv);
      if (taglineTimer) clearTimeout(taglineTimer);
    };
  });

  onDestroy(() => {
    unlisteners.forEach((fn) => fn());
  });

  // ── braille spinner (processing screen) ───────────────────────────────────────

  $effect(() => {
    if (screen === "processing") {
      const iv = setInterval(() => {
        spinnerIdx = (spinnerIdx + 1) % SPINNER_FRAMES.length;
      }, 80);
      return () => clearInterval(iv);
    }
  });

  // ── step message typewriter ───────────────────────────────────────────────────

  $effect(() => {
    const target = progress?.msg ?? "";
    let i = 0;
    displayMsg = "";
    if (!target) return;
    const iv = setInterval(() => {
      displayMsg = target.slice(0, ++i);
      if (i === target.length) clearInterval(iv);
    }, 20);
    return () => clearInterval(iv);
  });

  // ── handlers ──────────────────────────────────────────────────────────────────

  async function startPipeline(videoPath: string) {
    errorMsg = null;
    progress = null;
    videoFileName = videoPath.split("/").pop() ?? videoPath;
    screen = "processing";
    try {
      await invoke("start_pipeline", { videoPath });
    } catch (err) {
      errorMsg = String(err);
      screen = "import";
    }
  }

  // Tauri native drag-drop — provides real filesystem paths.
  getCurrentWindow().onDragDropEvent((e) => {
    if (e.payload.type === "over") {
      dragOver = true;
    } else if (e.payload.type === "drop") {
      dragOver = false;
      const path = e.payload.paths?.[0];
      if (path) startPipeline(path);
    } else {
      dragOver = false;
    }
  });

  async function browseFile() {
    const path = await openDialog({
      multiple: false,
      filters: [{ name: "Video", extensions: ["mp4", "mov", "mkv", "avi", "webm", "ts"] }],
    });
    if (typeof path === "string" && path) startPipeline(path);
  }

  async function cancelPipeline() {
    await invoke("cancel_pipeline");
    screen = "import";
    progress = null;
  }

  function reset() {
    screen = "import";
    topics = [];
    projectDir = "";
    videoFileName = "";
    progress = null;
    errorMsg = null;
  }

  async function copyTimestamp(topic: Topic) {
    await navigator.clipboard.writeText(topic.duration_label);
    copiedId = topic.topic_id;
    setTimeout(() => {
      copiedId = null;
    }, 1500);
  }

  // ── derived ───────────────────────────────────────────────────────────────────

  const progressPct = $derived(progress ? Math.round(progress.pct * 100) : 0);
  const progressStep = $derived(progress ? `${progress.step}/${progress.total}` : "");
</script>

<!-- ── Import screen ──────────────────────────────────────────────────────────── -->
{#if screen === "import"}
  <main class="screen import-screen">
    <h1 class="logo-title">{titleChars}</h1>
    <p class="tagline" class:visible={taglineVisible}>drop a stream. get topics.</p>

    {#if errorMsg}
      <div class="error-banner">
        <span aria-hidden="true" class="error-icon">✗</span>
        {errorMsg}
        <button class="dismiss" onclick={() => (errorMsg = null)}>×</button>
      </div>
    {/if}

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="drop-zone"
      class:drag-over={dragOver}
      role="region"
      aria-label="Video drop zone — drag a video file here or press Enter to browse"
      tabindex="0"
      onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") browseFile(); }}
    >
      <span class="drop-icon" aria-hidden="true">▶</span>
      <p class="drop-label">Drop video here</p>
      <p class="drop-sub">or</p>
      <button class="file-btn" onclick={browseFile}>Browse file</button>
    </div>
  </main>

<!-- ── Processing screen ─────────────────────────────────────────────────────── -->
{:else if screen === "processing"}
  <main class="screen processing-screen">
    <h1 class="logo-title">VODTOOL</h1>
    {#if videoFileName}
      <p class="processing-file">processing: {videoFileName}</p>
    {/if}

    <div class="progress-block">
      <div class="spinner-line">
        <span class="spinner">{SPINNER_FRAMES[spinnerIdx]}</span>
        <span class="progress-msg">{displayMsg}</span>
        <span class="progress-step">{progressStep}</span>
      </div>
      <div class="progress-bar-track">
        <div class="progress-bar-fill" style="width: {progressPct}%"></div>
      </div>
    </div>

    <button class="cancel-btn" onclick={cancelPipeline}>Cancel</button>
  </main>

<!-- ── Results screen ────────────────────────────────────────────────────────── -->
{:else if screen === "results"}
  <main class="screen results-screen">
    <header class="results-header">
      <h1 class="logo-title">VODTOOL</h1>
      <button class="back-btn" onclick={reset}>← new video</button>
    </header>

    {#if errorMsg}
      <div class="error-banner">
        <span aria-hidden="true" class="error-icon">✗</span>
        {errorMsg}
        <button class="dismiss" onclick={() => (errorMsg = null)}>×</button>
      </div>
    {:else}
      <p class="results-meta">{videoFileName ? `${videoFileName} — ` : ""}{topics.length} topics found</p>
    {/if}

    {#if topics.length === 0 && !errorMsg}
      <div class="empty-state">
        <p class="empty-msg">no topics found.</p>
        <p class="empty-sub">try a different file or a longer recording.</p>
      </div>
    {:else if topics.length > 0}
      <ul class="topic-list">
        {#each topics as topic, i (topic.topic_id)}
          <li class="topic-card" in:fly={{ y: 6, duration: 200, delay: i * 60 }}>
            <div class="topic-top">
              <span class="topic-num">{String(i + 1).padStart(2, "0")}</span>
              <span class="topic-duration">{topic.duration_label}</span>
              <button
                class="copy-btn"
                onclick={() => copyTimestamp(topic)}
                aria-label="Copy timestamp for {topic.label}"
              >{copiedId === topic.topic_id ? "copied!" : "copy ↗"}</button>
            </div>
            <p class="topic-label">{topic.label}</p>
            <p class="topic-summary">{topic.summary}</p>
          </li>
        {/each}
      </ul>
    {/if}
  </main>
{/if}

<style>
  /* ── reset & base ─────────────────────────────────────────────────── */
  :global(*, *::before, *::after) { box-sizing: border-box; margin: 0; padding: 0; }
  :global(body) {
    font-family: "Courier New", Courier, monospace;
    background: #0a0a0a;
    color: #e0e0e0;
    min-height: 100vh;
  }

  .screen {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2rem 1.5rem;
  }

  /* ── logo ─────────────────────────────────────────────────────────── */
  .logo-title {
    font-size: 2.4rem;
    font-weight: 700;
    letter-spacing: 0.25em;
    color: #fff;
    text-transform: uppercase;
    margin-bottom: 0.3rem;
  }
  .logo-title::after {
    content: "_";
    animation: blink 1s step-end infinite;
    color: #555;
  }

  /* ── import screen ───────────────────────────────────────────────── */
  .import-screen { justify-content: center; gap: 1.2rem; }

  .tagline {
    font-size: 0.85rem;
    letter-spacing: 0.15em;
    color: #666;
    text-transform: lowercase;
    margin-bottom: 1.5rem;
    opacity: 0;
    transition: opacity 0.3s;
  }
  .tagline.visible { opacity: 1; }

  .error-banner {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: #1a0a0a;
    border: 1px solid #5a1a1a;
    color: #e06060;
    padding: 0.6rem 1rem;
    font-size: 0.85rem;
    max-width: 480px;
    width: 100%;
  }
  .error-icon { color: #e06060; }
  .dismiss {
    margin-left: auto;
    background: none;
    border: none;
    color: #e06060;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
  }

  .drop-zone {
    border: 2px dashed #333;
    padding: 3rem 2rem;
    max-width: 480px;
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.6rem;
    cursor: default;
    transition: border-color 0.15s, background 0.15s;
    animation: breathe 3s ease-in-out infinite;
    outline: none;
  }
  .drop-zone:focus-visible { box-shadow: 0 0 0 1px #666; }
  .drop-zone.drag-over {
    border-color: #e0e0e0;
    background: #111;
    animation: none;
  }
  .drop-icon { font-size: 2.5rem; color: #444; }
  .drop-label { font-size: 1rem; color: #aaa; letter-spacing: 0.05em; }
  .drop-sub { font-size: 0.75rem; color: #444; }

  .file-btn {
    display: inline-block;
    border: 1px solid #444;
    padding: 0.45rem 1.1rem;
    font-family: inherit;
    font-size: 0.85rem;
    letter-spacing: 0.08em;
    color: #ccc;
    cursor: pointer;
    background: none;
    transition: border-color 0.15s, color 0.15s;
  }
  .file-btn:hover { border-color: #e0e0e0; color: #fff; }

  /* ── processing screen ───────────────────────────────────────────── */
  .processing-screen { justify-content: center; gap: 1.5rem; }

  .processing-file {
    font-size: 0.8rem;
    color: #555;
    letter-spacing: 0.08em;
    margin-top: -0.8rem;
  }

  .progress-block {
    max-width: 480px;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .spinner-line {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
    color: #888;
    letter-spacing: 0.04em;
    min-height: 1.2em;
  }
  .spinner { color: #aaa; }
  .progress-msg { flex: 1; }
  .progress-step { color: #555; font-size: 0.75rem; white-space: nowrap; }

  .progress-bar-track {
    width: 100%;
    height: 4px;
    background: #222;
  }
  .progress-bar-fill {
    height: 100%;
    background: #e0e0e0;
    transition: width 0.3s ease;
  }

  .cancel-btn {
    font-family: inherit;
    font-size: 0.8rem;
    letter-spacing: 0.1em;
    color: #555;
    background: none;
    border: 1px solid #333;
    padding: 0.4rem 1rem;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }
  .cancel-btn:hover { color: #ccc; border-color: #666; }

  /* ── results screen ──────────────────────────────────────────────── */
  .results-screen { align-items: stretch; max-width: 640px; margin: 0 auto; gap: 1rem; }

  .results-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }
  .back-btn {
    font-family: inherit;
    font-size: 0.8rem;
    color: #555;
    background: none;
    border: none;
    cursor: pointer;
    letter-spacing: 0.05em;
    transition: color 0.15s;
  }
  .back-btn:hover { color: #ccc; }

  .results-meta { font-size: 0.8rem; color: #444; letter-spacing: 0.08em; }

  .empty-state {
    padding: 2rem 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .empty-msg { font-size: 0.9rem; color: #666; }
  .empty-sub { font-size: 0.8rem; color: #444; }

  .topic-list { list-style: none; display: flex; flex-direction: column; gap: 0.6rem; }

  .topic-card {
    border: 1px solid #222;
    padding: 0.9rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    transition: border-color 0.15s;
  }
  .topic-card:hover { border-color: #444; }

  .topic-top {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .topic-num { font-size: 0.7rem; color: #444; letter-spacing: 0.1em; }
  .topic-duration { font-size: 0.75rem; color: #555; flex: 1; }
  .copy-btn {
    font-family: inherit;
    font-size: 0.75rem;
    color: #555;
    background: none;
    border: none;
    cursor: pointer;
    letter-spacing: 0.05em;
    padding: 0;
    transition: color 0.15s;
  }
  .copy-btn:hover { color: #ccc; }
  .topic-label { font-size: 1rem; color: #e0e0e0; font-weight: 600; }
  .topic-summary { font-size: 0.82rem; color: #888; line-height: 1.4; }

  /* ── animations ──────────────────────────────────────────────────── */
  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }
  @keyframes breathe {
    0%, 100% { border-color: #222; }
    50% { border-color: #444; }
  }
</style>
