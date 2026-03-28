<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { open as openDialog } from "@tauri-apps/plugin-dialog";
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
  let videoFileName = $state<string>("");
  let processLog = $state<string[]>([]);

  // ── spinner ───────────────────────────────────────────────────────────────────

  const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
  let spinnerIdx = $state(0);

  $effect(() => {
    if (screen === "processing") {
      const iv = setInterval(() => {
        spinnerIdx = (spinnerIdx + 1) % FRAMES.length;
      }, 80);
      return () => clearInterval(iv);
    }
  });

  // ── copy state ────────────────────────────────────────────────────────────────

  let copiedId = $state<string | null>(null);

  // ── event listeners ───────────────────────────────────────────────────────────

  let unlisteners: UnlistenFn[] = [];

  function registerListeners() {
    Promise.all([
      listen<ProgressMsg>("pipeline-progress", (e) => {
        const entry = `[${e.payload.step}/${e.payload.total}] ${e.payload.msg}`;
        if (processLog.at(-1) !== entry) {
          processLog = [...processLog, entry];
        }
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

  onDestroy(() => {
    unlisteners.forEach((fn) => fn());
  });

  // ── handlers ──────────────────────────────────────────────────────────────────

  async function startPipeline(videoPath: string) {
    errorMsg = null;
    progress = null;
    processLog = [];
    videoFileName = videoPath.split("/").pop() ?? videoPath;
    screen = "processing";
    try {
      await invoke("start_pipeline", { videoPath });
    } catch (err) {
      errorMsg = String(err);
      screen = "import";
    }
  }

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
    processLog = [];
  }

  function reset() {
    screen = "import";
    topics = [];
    projectDir = "";
    videoFileName = "";
    progress = null;
    processLog = [];
    errorMsg = null;
  }

  async function copyTimestamp(topic: Topic) {
    await navigator.clipboard.writeText(topic.duration_label);
    copiedId = topic.topic_id;
    setTimeout(() => { copiedId = null; }, 1500);
  }

  const progressPct = $derived(progress ? Math.round(progress.pct * 100) : 0);
</script>

<!-- ── Import ──────────────────────────────────────────────────────────────────── -->
{#if screen === "import"}
  <main class="screen" class:drag-over={dragOver}>
    <p class="title">VideoTool</p>
    <p class="">Transcribe and segment your video by topic</p>

    {#if errorMsg}
      <p class="error-line">✗ {errorMsg} <button class="inline-btn" onclick={() => (errorMsg = null)}>dismiss</button></p>
    {/if}

    <div class="import-body">
      <p class="hint">drop a video file here</p>
      <p class="hint dim">or <button class="browse-btn" onclick={browseFile}>browse file</button></p>
    </div>
  </main>

<!-- ── Processing ─────────────────────────────────────────────────────────────── -->
{:else if screen === "processing"}
  <main class="screen">
    <p class="title">VideoTool</p>
    <p class="dim">Analyzing: {videoFileName}</p>

    <div class="log">
      {#if processLog.length === 0}
        <p class="log-line">loading...</p>
        <span class="spinner">{FRAMES[spinnerIdx]}</span>
      {:else}
        {#each processLog as line, i}
          <p class="log-line" class:dim={i < processLog.length - 1}>{line}</p>
        {/each}
        <span class="spinner">{FRAMES[spinnerIdx]}</span>
      {/if}
    </div>

    <div class="progress-track">
      <div class="progress-fill" style="width: {progressPct}%"></div>
    </div>
    <p class="dim pct">{progressPct}%</p>

    <div><button class="inline-btn" onclick={cancelPipeline}>[cancel]</button></div>
  </main>

<!-- ── Results ────────────────────────────────────────────────────────────────── -->
{:else if screen === "results"}
  <main class="screen">
    <p class="title">VideoTool</p>
    <p class="dim">{videoFileName} · {topics.length} topics</p>
    <div><button class="inline-btn" onclick={reset}>[new]</button></div>
  

    {#if errorMsg}
      <p class="error-line">✗ {errorMsg} <button class="inline-btn" onclick={() => (errorMsg = null)}>dismiss</button></p>
    {/if}

    {#if topics.length === 0 && !errorMsg}
      <p class="hint dim">no topics found. try a different file or a longer recording.</p>
    {:else}
      {#each topics as topic, i (topic.topic_id)}
        <div class="topic">
          <p class="topic-head">
            <span class="topic-num">{String(i + 1).padStart(2, "0")}</span>
            <span class="topic-dur dim">{topic.duration_label}</span>
            <span class="topic-label">{topic.label}</span>
            <button
              class="inline-btn copy"
              onclick={() => copyTimestamp(topic)}
              aria-label="Copy timestamp for {topic.label}"
            >{copiedId === topic.topic_id ? "copied!" : "copy ↗"}</button>
          </p>
          <p class="topic-summary dim">{topic.summary}</p>
        </div>
      {/each}
    {/if}
  </main>
{/if}

<style>
  :global(*, *::before, *::after) { box-sizing: border-box; margin: 0; padding: 0; }
  :global(body) {
    font-family: "Courier New", Courier, monospace;
    font-size: 13px;
    line-height: 1.6;
    background: #0e0e0e;
    color: #c9c9c9;
  }

  .screen {
    padding: 1.5rem 2rem;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    gap: 0;
  }
  .screen.drag-over { background: #161616; }

  /* ── header ──────────────────────────────────────────────────────── */
  .title { color: #fff; margin-bottom: 0.4rem; display: flex; align-items: baseline; gap: 0; }
  .sep { color: #444; }
  .dim { color: #555; }
  .rule { height: 1px; background: #1e1e1e; margin-bottom: 1.5rem; }

  /* ── import ──────────────────────────────────────────────────────── */
  .import-body { margin-top: 1rem; display: flex; flex-direction: column; gap: 0.25rem; }
  .hint { color: #888; }

  .cursor {
    color: #888;
    margin-top: 0.75rem;
    animation: blink 1s step-end infinite;
    display: inline-block;
  }

  .browse-btn {
    font-family: inherit;
    font-size: 13px;
    color: #888;
    background: none;
    border: none;
    border-bottom: 1px solid #444;
    cursor: pointer;
    padding: 0;
    transition: color 0.1s, border-color 0.1s;
  }
  .browse-btn:hover { color: #c9c9c9; border-color: #888; }

  /* ── processing ──────────────────────────────────────────────────── */
  .log { margin-top: 1rem; margin-bottom: 1rem; display: flex; flex-direction: column; gap: 0.1rem; }
  .log-line { color: #c9c9c9; }
  .log-line.dim { color: #444; }
  .spinner { color: #888; display: block; margin-top: 0.1rem; }

  .progress-track {
    width: 100%;
    max-width: 320px;
    height: 2px;
    background: #1e1e1e;
    margin-bottom: 0.3rem;
  }
  .progress-fill {
    height: 100%;
    background: #666;
    transition: width 0.3s ease;
  }
  .pct { margin-bottom: 1rem; }

  /* ── results ─────────────────────────────────────────────────────── */
  .topic {
    padding: 0.75rem 0;
    border-bottom: 1px solid #1a1a1a;
  }
  .topic-head {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    margin-bottom: 0.15rem;
  }
  .topic-num { color: #444; min-width: 2ch; }
  .topic-dur { min-width: 10ch; }
  .topic-label { color: #e0e0e0; flex: 1; }
  .topic-summary { padding-left: calc(2ch + 0.75rem + 10ch + 0.75rem); color: #555; font-size: 12px; }

  /* ── shared ──────────────────────────────────────────────────────── */
  .inline-btn {
    font-family: inherit;
    font-size: 12px;
    color: #555;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    transition: color 0.1s;
  }
  .inline-btn:hover { color: #c9c9c9; }
  .inline-btn.right { margin-left: auto; }
  .inline-btn.copy { white-space: nowrap; }

  .error-line {
    color: #c05050;
    margin-bottom: 1rem;
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
  }

  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }
</style>
