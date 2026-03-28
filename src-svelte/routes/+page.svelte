<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { convertFileSrc } from "@tauri-apps/api/core";
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
    beat_count: number;
  }

  interface ErrorMsg {
    error: string;
    step: number;
  }

  interface Beat {
    type: string;
    start_s: number;
    end_s: number;
    confidence: number;
    label: string;
  }

  interface BeatTopic {
    topic_id: string;
    topic_label: string;
    beats: Beat[];
  }

  interface BeatsResponse {
    beats: BeatTopic[];
    video_path: string | null;
    duration_seconds: number | null;
  }

  // ── state ─────────────────────────────────────────────────────────────────────

  let screen = $state<Screen>("import");
  let dragOver = $state(false);
  let progress = $state<ProgressMsg | null>(null);
  let errorMsg = $state<string | null>(null);
  let videoFileName = $state<string>("");
  let processLog = $state<string[]>([]);
  let urlInput = $state("");

  // ── beat timeline state ───────────────────────────────────────────────────────

  let beatTopics = $state<BeatTopic[]>([]);
  let videoSrc = $state<string>("");
  let videoDuration = $state(0);
  let hoverInfo = $state("");
  let playerRef = $state<HTMLVideoElement | null>(null);
  let timelineRef = $state<HTMLDivElement | null>(null);
  let playheadX = $state(0);
  const LABEL_W = 40;

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

  // ── playhead sync ─────────────────────────────────────────────────────────────

  $effect(() => {
    if (screen === "results" && playerRef && timelineRef && videoDuration > 0) {
      let animId: number;
      const update = () => {
        if (playerRef && timelineRef && videoDuration > 0) {
          const w = timelineRef.clientWidth;
          playheadX = LABEL_W + ((playerRef.currentTime / videoDuration) * (w - LABEL_W));
        }
        animId = requestAnimationFrame(update);
      };
      animId = requestAnimationFrame(update);
      return () => cancelAnimationFrame(animId);
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
        try {
          const resp = await invoke<BeatsResponse>("load_beats", {
            projectDir: e.payload.project_dir,
          });
          beatTopics = resp.beats;
          if (resp.video_path) {
            videoSrc = convertFileSrc(resp.video_path);
          }
          if (resp.duration_seconds) {
            videoDuration = resp.duration_seconds;
          }
        } catch (err) {
          beatTopics = [];
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
    beatTopics = [];
    videoSrc = "";
    videoDuration = 0;
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

  function reset() {
    screen = "import";
    beatTopics = [];
    videoSrc = "";
    videoDuration = 0;
    videoFileName = "";
    progress = null;
    processLog = [];
    errorMsg = null;
    urlInput = "";
    hoverInfo = "";
  }

  function seekTo(seconds: number) {
    if (playerRef) {
      playerRef.currentTime = seconds;
      if (playerRef.paused && playerRef.src) playerRef.play();
    }
  }

  function onTimelineClick(e: MouseEvent) {
    if (!timelineRef || videoDuration <= 0) return;
    if ((e.target as HTMLElement).classList.contains("beat")) return;
    const rect = timelineRef.getBoundingClientRect();
    const x = e.clientX - rect.left;
    if (x < LABEL_W) return;
    const pct = (x - LABEL_W) / (rect.width - LABEL_W);
    seekTo(pct * videoDuration);
  }

  function onVideoLoaded() {
    if (playerRef && playerRef.duration && isFinite(playerRef.duration)) {
      videoDuration = playerRef.duration;
    }
  }

  function fmtTime(s: number): string {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return m + ":" + String(sec).padStart(2, "0");
  }

  function beatLeft(beat: Beat, timelineW: number): number {
    return LABEL_W + ((beat.start_s / videoDuration) * (timelineW - LABEL_W));
  }

  function beatWidth(beat: Beat, timelineW: number): number {
    return Math.max(2, ((beat.end_s - beat.start_s) / videoDuration) * (timelineW - LABEL_W));
  }

  const progressPct = $derived(progress ? Math.round(progress.pct * 100) : 0);
</script>

<!-- ── Import ──────────────────────────────────────────────────────────────────── -->
{#if screen === "import"}
  <main class="screen" class:drag-over={dragOver}>
    <p class="title">VodTool</p>
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
    <p class="title">VodTool</p>
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

<!-- ── Results (Beat Timeline) ───────────────────────────────────────────────── -->
{:else if screen === "results"}
  <main class="screen results-screen">
    <div class="results-header">
      <p class="title">VodTool</p>
      <p class="dim">{videoFileName} · {beatTopics.length} topics</p>
      <button class="inline-btn" onclick={reset}>[new]</button>
    </div>

    {#if errorMsg}
      <p class="error-line">✗ {errorMsg} <button class="inline-btn" onclick={() => (errorMsg = null)}>dismiss</button></p>
    {/if}

    <!-- Video player -->
    {#if videoSrc}
      <video
        bind:this={playerRef}
        src={videoSrc}
        controls
        class="video-player"
        onloadedmetadata={onVideoLoaded}
      ></video>
    {/if}

    <!-- Legend -->
    <div class="legend">
      <div class="legend-item"><div class="legend-swatch hook"></div>hook</div>
      <div class="legend-item"><div class="legend-swatch build"></div>build</div>
      <div class="legend-item"><div class="legend-swatch peak"></div>peak</div>
      <div class="legend-item"><div class="legend-swatch resolution"></div>resolution</div>
    </div>

    <!-- Beat timeline -->
    {#if beatTopics.length > 0 && videoDuration > 0}
      <div class="timeline" bind:this={timelineRef} onclick={onTimelineClick}>
        <div class="playhead" style="left: {playheadX}px"></div>
        {#each beatTopics as topic}
          <div class="topic-row">
            <div class="topic-label-col" title={topic.topic_label}>{topic.topic_id}</div>
            {#each topic.beats as beat}
              <div
                class="beat beat-{beat.type}"
                style="left: {beatLeft(beat, timelineRef?.clientWidth ?? 800)}px; width: {beatWidth(beat, timelineRef?.clientWidth ?? 800)}px"
                title={`[${beat.type}] ${fmtTime(beat.start_s)}–${fmtTime(beat.end_s)} (${beat.confidence})\n${beat.label}`}
                onclick={() => seekTo(beat.start_s)}
                onmouseenter={() => { hoverInfo = `[${beat.type}] ${fmtTime(beat.start_s)}–${fmtTime(beat.end_s)} | ${beat.label}`; }}
                onmouseleave={() => { hoverInfo = ""; }}
                role="button"
                tabindex="0"
              >
                {beat.label}
              </div>
            {/each}
          </div>
        {/each}
      </div>
    {:else if beatTopics.length === 0 && !errorMsg}
      <p class="hint dim">no beats found. try a different file or a longer recording.</p>
    {/if}

    <!-- Hover info -->
    <div class="hover-info">{hoverInfo || "\u00A0"}</div>
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

  .results-screen {
    gap: 0.5rem;
  }

  /* ── header ──────────────────────────────────────────────────────── */
  .title { color: #fff; margin-bottom: 0.4rem; }
  .results-header { display: flex; align-items: baseline; gap: 0.75rem; flex-wrap: wrap; }
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

  /* ── results: video ─────────────────────────────────────────────── */
  .video-player {
    width: 100%;
    max-height: 45vh;
    background: #000;
    display: block;
  }

  /* ── results: legend ────────────────────────────────────────────── */
  .legend { display: flex; gap: 1rem; }
  .legend-item { display: flex; align-items: center; gap: 0.3rem; font-size: 11px; color: #666; }
  .legend-swatch { width: 12px; height: 12px; border-radius: 2px; }
  .legend-swatch.hook { background: #c05050; }
  .legend-swatch.build { background: #4080c0; }
  .legend-swatch.peak { background: #c0a030; }
  .legend-swatch.resolution { background: #40a060; }

  /* ── results: timeline ──────────────────────────────────────────── */
  .timeline {
    position: relative;
    width: 100%;
    overflow-x: auto;
    border: 1px solid #1e1e1e;
    background: #111;
  }

  .topic-row {
    position: relative;
    height: 28px;
    border-bottom: 1px solid #1a1a1a;
  }

  .topic-label-col {
    position: absolute;
    left: 0;
    top: 0;
    width: 40px;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    color: #555;
    z-index: 2;
    background: #111;
    border-right: 1px solid #1a1a1a;
  }

  .beat {
    position: absolute;
    top: 3px;
    height: 22px;
    border-radius: 2px;
    cursor: pointer;
    opacity: 0.85;
    transition: opacity 0.1s;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: 10px;
    line-height: 22px;
    padding: 0 4px;
    color: rgba(0,0,0,0.7);
    min-width: 2px;
  }
  .beat:hover { opacity: 1; z-index: 10; }

  .beat-hook { background: #c05050; }
  .beat-build { background: #4080c0; }
  .beat-peak { background: #c0a030; }
  .beat-resolution { background: #40a060; }

  .playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    background: #fff;
    z-index: 20;
    pointer-events: none;
  }

  .hover-info {
    height: 2.4em;
    line-height: 2.4em;
    color: #888;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 0 0.25rem;
  }

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
