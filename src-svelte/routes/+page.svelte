<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import { onDestroy } from "svelte";

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

  onDestroy(() => {
    unlisteners.forEach((fn) => fn());
  });

  // ── handlers ──────────────────────────────────────────────────────────────────

  async function startPipeline(videoPath: string) {
    errorMsg = null;
    progress = null;
    screen = "processing";
    try {
      await invoke("start_pipeline", { videoPath });
    } catch (err) {
      errorMsg = String(err);
      screen = "import";
    }
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    const file = e.dataTransfer?.files[0];
    if (file) startPipeline(file.path ?? (file as File & { path?: string }).path ?? "");
  }

  function handleFileInput(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) startPipeline((file as File & { path?: string }).path ?? "");
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
    progress = null;
    errorMsg = null;
  }

  // ── derived ───────────────────────────────────────────────────────────────────

  const progressPct = $derived(progress ? Math.round(progress.pct * 100) : 0);
  const progressMsg = $derived(progress?.msg ?? "Starting...");
  const progressStep = $derived(progress ? `${progress.step}/${progress.total}` : "");
</script>

<!-- ── Import screen ──────────────────────────────────────────────────────────── -->
{#if screen === "import"}
  <main class="screen import-screen">
    <h1 class="logo-title">VODTOOL</h1>
    <p class="tagline">drop a stream. get topics.</p>

    {#if errorMsg}
      <div class="error-banner">
        <span class="error-icon">✗</span>
        {errorMsg}
        <button class="dismiss" onclick={() => (errorMsg = null)}>×</button>
      </div>
    {/if}

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="drop-zone"
      class:drag-over={dragOver}
      ondragover={(e) => { e.preventDefault(); dragOver = true; }}
      ondragleave={() => (dragOver = false)}
      ondrop={handleDrop}
    >
      <span class="drop-icon">▶</span>
      <p class="drop-label">Drop video here</p>
      <p class="drop-sub">or</p>
      <label class="file-btn">
        Browse file
        <input type="file" accept="video/*,.mp4,.mov,.mkv,.avi,.webm" onchange={handleFileInput} />
      </label>
    </div>
  </main>

<!-- ── Processing screen ─────────────────────────────────────────────────────── -->
{:else if screen === "processing"}
  <main class="screen processing-screen">
    <h1 class="logo-title">VODTOOL</h1>

    <div class="progress-block">
      <div class="progress-bar-track">
        <div class="progress-bar-fill" style="width: {progressPct}%"></div>
      </div>
      <div class="progress-meta">
        <span class="progress-msg">{progressMsg}</span>
        <span class="progress-step">{progressStep}</span>
      </div>
    </div>

    <button class="cancel-btn" onclick={cancelPipeline}>Cancel</button>
  </main>

<!-- ── Results screen ────────────────────────────────────────────────────────── -->
{:else if screen === "results"}
  <main class="screen results-screen">
    <header class="results-header">
      <h1 class="logo-title">VODTOOL</h1>
      <button class="back-btn" onclick={reset}>← New video</button>
    </header>

    <p class="results-meta">{topics.length} topics found</p>

    <ul class="topic-list">
      {#each topics as topic (topic.topic_id)}
        <li class="topic-card">
          <div class="topic-top">
            <span class="topic-id">{topic.topic_id}</span>
            <span class="topic-duration">{topic.duration_label}</span>
          </div>
          <p class="topic-label">{topic.label}</p>
          <p class="topic-summary">{topic.summary}</p>
          <p class="topic-chunks">{topic.chunk_count} chunks</p>
        </li>
      {/each}
    </ul>
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

  /* ── import screen ───────────────────────────────────────────────── */
  .import-screen { justify-content: center; gap: 1.2rem; }

  .tagline {
    font-size: 0.85rem;
    letter-spacing: 0.15em;
    color: #666;
    text-transform: lowercase;
    margin-bottom: 1.5rem;
  }

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
  }
  .drop-zone.drag-over {
    border-color: #e0e0e0;
    background: #111;
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
    transition: border-color 0.15s, color 0.15s;
  }
  .file-btn:hover { border-color: #e0e0e0; color: #fff; }
  .file-btn input { display: none; }

  /* ── processing screen ───────────────────────────────────────────── */
  .processing-screen { justify-content: center; gap: 2rem; }

  .progress-block {
    max-width: 480px;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
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
  .progress-meta {
    display: flex;
    justify-content: space-between;
    font-size: 0.8rem;
    color: #666;
    letter-spacing: 0.05em;
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
    justify-content: space-between;
    align-items: center;
  }
  .topic-id { font-size: 0.7rem; color: #444; letter-spacing: 0.1em; }
  .topic-duration { font-size: 0.75rem; color: #555; }
  .topic-label { font-size: 1rem; color: #e0e0e0; font-weight: 600; }
  .topic-summary { font-size: 0.82rem; color: #888; line-height: 1.4; }
  .topic-chunks { font-size: 0.7rem; color: #444; margin-top: 0.2rem; }
</style>
