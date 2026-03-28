<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { open as openDialog } from "@tauri-apps/plugin-dialog";
  import { onDestroy } from "svelte";

  // ── types ────────────────────────────────────────────────────────────────────

  type Screen = "import" | "processing";

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
    beat_count: number;
  }

  interface ErrorMsg {
    error: string;
    step: number;
  }

  // ── state ─────────────────────────────────────────────────────────────────────

  let screen = $state<Screen>("import");
  let dragOver = $state(false);
  let progress = $state<ProgressMsg | null>(null);
  let errorMsg = $state<string | null>(null);
  let videoFileName = $state<string>("");
  let processLog = $state<string[]>([]);
  let urlInput = $state("");

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
        // Pipeline complete — start the viewer server and navigate to it
        try {
          const port = await invoke<number>("start_viewer_server", {
            projectDir: e.payload.project_dir,
          });
          // Navigate the webview to the viewer served by our HTTP server
          const origin = encodeURIComponent(window.location.origin);
          window.location.href = `http://127.0.0.1:${port}/?origin=${origin}`;
        } catch (err) {
          errorMsg = String(err);
          screen = "import";
        }
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

  function handleUrlSubmit() {
    const url = urlInput.trim();
    if (!url) return;
    videoFileName = url;
    startPipeline(url);
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

  const progressPct = $derived(progress ? Math.round(progress.pct * 100) : 0);
</script>

<!-- ── Import ──────────────────────────────────────────────────────────────────── -->
{#if screen === "import"}
  <main class="screen" class:drag-over={dragOver}>
    <p class="title">VideoTool</p>
    <p class="">Narrative beat detection for stream VODs</p>

    {#if errorMsg}
      <p class="error-line">✗ {errorMsg} <button class="inline-btn" onclick={() => (errorMsg = null)}>dismiss</button></p>
    {/if}

    <div class="import-body">
      <div class="url-row">
        <input
          type="text"
          class="url-input"
          placeholder="paste twitch vod url..."
          bind:value={urlInput}
          onkeydown={(e) => { if (e.key === "Enter") handleUrlSubmit(); }}
        />
        <button class="go-btn" onclick={handleUrlSubmit}>go</button>
      </div>
      <p class="hint dim">or drop a video file here · <button class="browse-btn" onclick={browseFile}>browse</button></p>
    </div>
  </main>

<!-- ── Processing ─────────────────────────────────────────────────────────────── -->
{:else if screen === "processing"}
  <main class="screen">
    <p class="title">VideoTool</p>
    <p class="dim">{videoFileName}</p>

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
  .title { color: #fff; margin-bottom: 0.4rem; }
  .dim { color: #555; }

  /* ── import ──────────────────────────────────────────────────────── */
  .import-body { margin-top: 1rem; display: flex; flex-direction: column; gap: 0.5rem; }
  .hint { color: #888; }

  .url-row { display: flex; gap: 0.5rem; max-width: 500px; }
  .url-input {
    flex: 1;
    font-family: inherit;
    font-size: 13px;
    color: #c9c9c9;
    background: #111;
    border: 1px solid #333;
    padding: 0.4rem 0.6rem;
    outline: none;
  }
  .url-input:focus { border-color: #555; }
  .url-input::placeholder { color: #444; }
  .go-btn {
    font-family: inherit;
    font-size: 13px;
    color: #888;
    background: none;
    border: 1px solid #333;
    padding: 0.4rem 0.8rem;
    cursor: pointer;
  }
  .go-btn:hover { color: #c9c9c9; border-color: #666; }

  .browse-btn {
    font-family: inherit;
    font-size: 13px;
    color: #888;
    background: none;
    border: none;
    border-bottom: 1px solid #444;
    cursor: pointer;
    padding: 0;
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

  .error-line {
    color: #c05050;
    margin-bottom: 0.5rem;
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
  }
</style>
