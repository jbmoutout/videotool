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
    download_pct?: number;
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
  let pipelineRunning = $state(false);
  const quality = "worst";

  interface ProjectInfo {
    project_id: string;
    source_filename: string;
    title: string | null;
    channel: string | null;
    created_at: string;
    has_beats: boolean;
    project_dir: string;
  }

  let projects = $state<ProjectInfo[]>([]);

  async function loadProjects() {
    try {
      const all = await invoke<ProjectInfo[]>("list_projects");
      projects = all.filter((p) => p.has_beats);
    } catch {
      projects = [];
    }
  }

  loadProjects();

  async function openProject(projectDir: string) {
    try {
      const port = await invoke<number>("start_viewer_server", { projectDir });
      const origin = encodeURIComponent(window.location.origin);
      window.location.href = `http://127.0.0.1:${port}/?origin=${origin}`;
    } catch (err) {
      errorMsg = String(err);
    }
  }

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

  // ── smooth progress bar ───────────────────────────────────────────────────────

  let targetPct = $state(0);
  let displayPct = $state(0);
  let lastStep = $state(0);

  $effect(() => {
    if (screen === "processing") {
      const iv = setInterval(() => {
        if (displayPct < targetPct) {
          const increment = targetPct >= 90 ? 5 : 2;
          displayPct = Math.min(displayPct + increment, targetPct);
        } else if (displayPct < 99) {
          // Slow crawl between real events (steps 2 & 3 have no sub-events)
          const step = progress?.step ?? 0;
          const total = progress?.total ?? 3;
          const cap = Math.min(Math.round(((step + 1) / total) * 100) - 2, 99);
          if (displayPct < cap) {
            displayPct = Math.min(displayPct + 0.3, cap);
          }
        }
      }, 300);
      return () => clearInterval(iv);
    } else {
      displayPct = 0;
      targetPct = 0;
    }
  });

  // ── rotating wait messages ────────────────────────────────────────────────────

  const WAIT_MSGS: Record<number, string[]> = {
    2: [
      "Transcribing audio…",
      "Running speech-to-text…",
      "Decoding speech…",
      "Aligning transcript…",
      "Processing audio stream…",
    ],
    3: [
      "Detecting narrative beats…",
      "Analyzing structure…",
      "Identifying key moments…",
      "Segmenting story arcs…",
      "Mapping hook to resolution…",
    ],
  };

  let waitMsgIdx = $state(0);
  let currentWaitMsg = $state("");

  $effect(() => {
    if (screen === "processing") {
      // Only rotate messages for steps 2 and 3 (step 1 gets real-time messages)
      const iv = setInterval(() => {
        const step = progress?.step ?? 1;
        if (step >= 2 && WAIT_MSGS[step]) {
          const msgs = WAIT_MSGS[step];
          waitMsgIdx = (waitMsgIdx + 1) % msgs.length;
          currentWaitMsg = msgs[waitMsgIdx];
        }
      }, 4000);
      currentWaitMsg = "starting...";
      return () => clearInterval(iv);
    }
  });

  // ── event listeners ───────────────────────────────────────────────────────────

  let unlisteners: UnlistenFn[] = [];

  function registerListeners() {
    Promise.all([
      listen<ProgressMsg>("pipeline-progress", (e) => {
        progress = e.payload;

        // Download sub-events: real-time download %
        if (e.payload.download_pct != null) {
          // download_pct 0-100 maps to 0% → (1/total)*100% of the overall bar
          const stepCeil = Math.round((1 / e.payload.total) * 100);
          targetPct = Math.max(targetPct, Math.round((e.payload.download_pct / 100) * stepCeil));
          currentWaitMsg = e.payload.download_pct >= 100
            ? e.payload.msg
            : `downloading video: ${e.payload.download_pct}%`;
          return;
        }

        // Step changed — update log, progress bar, wait message
        if (e.payload.step !== lastStep) {
          lastStep = e.payload.step;
          const entry = `[${e.payload.step}/${e.payload.total}] ${e.payload.msg}`;
          if (processLog.at(-1) !== entry) {
            processLog = [...processLog, entry];
          }
          targetPct = Math.round(e.payload.pct * 100);
          waitMsgIdx = 0;
          if (WAIT_MSGS[e.payload.step]) {
            currentWaitMsg = WAIT_MSGS[e.payload.step][0];
          }
        } else {
          // Same step, sub-status update (e.g. "extracting audio...")
          currentWaitMsg = e.payload.msg;
        }
      }),
      listen<DoneMsg>("pipeline-done", async (e) => {
        targetPct = 100;
        try {
          const port = await invoke<number>("start_viewer_server", {
            projectDir: e.payload.project_dir,
          });
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
        pipelineRunning = false;
      }),
      listen<string>("pipeline-error", (e) => {
        errorMsg = typeof e.payload === "string" ? e.payload : "Unknown error";
        screen = "import";
        pipelineRunning = false;
      }),
      listen("pipeline-exit", () => {
        // Safety net: if subprocess ended but no done/error event reached us,
        // unstick the processing screen.
        if (screen === "processing") {
          errorMsg = errorMsg ?? "Pipeline ended unexpectedly";
          screen = "import";
        }
        pipelineRunning = false;
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
    if (pipelineRunning) return;
    pipelineRunning = true;
    errorMsg = null;
    progress = null;
    processLog = [];
    targetPct = 0;
    displayPct = 0;
    lastStep = 0;
    waitMsgIdx = 0;
    videoFileName = videoPath.split("/").pop() ?? videoPath;
    screen = "processing";
    try {
      await invoke("start_pipeline", { videoPath, quality });
    } catch (err) {
      errorMsg = String(err);
      screen = "import";
      pipelineRunning = false;
    }
  }

  function handleUrlSubmit() {
    const url = urlInput.trim();
    if (!url) return;
    if (!url.startsWith("/") && !url.startsWith("~") && !/^[a-zA-Z]:/.test(url) && !url.includes("twitch.tv")) {
      errorMsg = "Enter a Twitch VOD URL or a local file path";
      return;
    }
    videoFileName = url;
    startPipeline(url);
  }

  getCurrentWindow().onDragDropEvent((e) => {
    if (e.payload.type === "over") {
      dragOver = true;
    } else if (e.payload.type === "drop") {
      dragOver = false;
      const path = e.payload.paths?.[0];
      if (path && !pipelineRunning) startPipeline(path);
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
    pipelineRunning = false;
  }
</script>

<!-- ── Import ──────────────────────────────────────────────────────────────────── -->
{#if screen === "import"}
  <main class="screen" class:drag-over={dragOver}>
    <p class="title">VideoTool</p>
    <p class="">Paste a VOD link or add a video file. Let VideoTool map out your stream in minutes</p>

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

    <hr class="divider" />

    <p class="flow-line">vod url or file <span class="flow-sep">→</span> extract audio <span class="flow-sep">→</span> transcribe <span class="flow-sep">→</span> detect beats <span class="flow-sep">→</span> topic map <span class="flow-check">✓</span></p>

    {#if projects.length > 0}
      <hr class="divider" />
      <p class="dim">recent projects</p>
      {#each projects as proj}
        <button class="project-link" onclick={() => openProject(proj.project_dir)}>
          - {#if proj.channel}<span class="project-channel">{proj.channel}</span> {/if}{proj.title ?? proj.source_filename} <span class="dim">— {proj.created_at.slice(0, 10)}</span>
        </button>
      {/each}
    {/if}
  </main>

<!-- ── Processing ─────────────────────────────────────────────────────────────── -->
{:else if screen === "processing"}
  <main class="screen">
    <p class="title">VideoTool</p>
    <p class="dim">{videoFileName}</p>

    <div class="log">
      {#if processLog.length === 0}
        <p class="log-line">loading...</p>
      {:else}
        {#each processLog as line, i}
          <p class="log-line" class:dim={i < processLog.length - 1}>{line}</p>
        {/each}
      {/if}
      <span class="spinner-line">
        <span class="spinner">{FRAMES[spinnerIdx]}</span>
        <span class="wait-msg">{currentWaitMsg}</span>
      </span>
    </div>

    <div class="progress-track">
      <div class="progress-fill" style="width: {displayPct}%"></div>
    </div>
    <p class="dim pct">{Math.round(displayPct)}%</p>

    <div><button class="inline-btn" onclick={cancelPipeline}>[cancel]</button></div>

    
  </main>
{/if}

<style>
  :global(*, *::before, *::after) { box-sizing: border-box; margin: 0; padding: 0; }
  :global(body) {
    font-family: Monaco, "Cascadia Code", "Fira Code", "Courier New", monospace;
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

  /* ── flow line ──────────────────────────────────────────────────── */
  .divider { border: none; border-top: 1px solid #222; margin: 24px 0 16px 0; }
  .flow-line { color: #555; }
  .flow-sep { color: #444; }
  .flow-check { color: #4ADE80; }

  /* ── project links ─────────────────────────────────────────────── */
  .project-link {
    font-family: inherit;
    font-size: 13px;
    color: #888;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    text-align: left;
    display: block;
    line-height: 1.6;
  }
  .project-link:hover { color: #c9c9c9; }
  .project-channel { color: #555; margin-right: 0.5rem; }

  /* ── processing ──────────────────────────────────────────────────── */
  .log { margin-top: 1rem; margin-bottom: 1rem; display: flex; flex-direction: column; gap: 0.1rem; }
  .log-line { color: #c9c9c9; }
  .log-line.dim { color: #444; }

  .spinner-line { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.1rem; }
  .spinner { color: #888; }
  .wait-msg { color: #555; font-size: 12px; }

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
    transition: width 0.2s ease;
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
