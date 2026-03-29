# Design System — VodTool

## Product Context
- **What this is:** Desktop app that maps narrative beats (hook, build, peak, resolution) on stream VOD timelines
- **Who it's for:** Twitch streamers and their editors who need to cut highlights faster
- **Space/industry:** Streaming tools, VOD editing — peers: Eklipse, StreamLadder, Streamlabs Highlighter
- **Project type:** Tauri desktop app (Svelte frontend, Rust backend)

## Aesthetic Direction
- **Direction:** Industrial/Utilitarian — a tool that sits next to OBS and Discord, not next to Eklipse and StreamLadder
- **Decoration level:** Minimal — typography and whitespace do all the work. Hairline rules (1px #222) as dividers. No boxes, no cards, no containers.
- **Mood:** Terminal-native. Precise, functional, quiet. The UI doesn't try to be exciting — the content (beat data) is the excitement. The app should feel like it belongs in the same OS layer as OBS, Discord, and VS Code.
- **Anti-patterns:** No purple gradients, no 3-column icon grids with icons in colored circles, no centered-everything layouts, no bubbly border-radius, no decorative blobs, no "terminal-styled" imitations (giant monospace titles, breathing borders, typewriter animations on static text)

## Typography
- **All text:** JetBrains Mono — excellent legibility at 13px, tabular-nums support, free, cross-platform (Monaco is macOS-only)
- **Fallback:** Monaco, "Cascadia Code", "Fira Code", "Courier New", monospace
- **Loading:** Google Fonts CDN `https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap`
- **Scale:**
  - 18px — page title (used sparingly, max 1 per screen)
  - 15px — section headers
  - 13px — body, default, all interactive text
  - 11px — metadata, timestamps, labels, secondary info
- **Rules:** No sans-serif layer. One family. No letter-spacing manipulation. No font sizes above 18px for UI chrome. Size hierarchy is minimal by design.

## Color
- **Approach:** Restrained — one accent + neutrals + semantic signals
- **Background:** #0A0A0A — near-black
- **Surface:** #111111 — elevated panels, input backgrounds
- **Surface hover:** #161616
- **Border:** #222222 — hairline dividers
- **Text primary:** #C9C9C9
- **Text bright:** #FFFFFF — titles, emphasis
- **Text muted:** #555555 — secondary info, inactive states
- **Text dim:** #444444 — completed/past items, disabled
- **Accent:** #6B8AFF — interactive elements, focus rings, primary buttons, progress bars, active states
- **Semantic:**
  - Success: #4ADE80 — positive states, completed steps
  - Warning: #FFB830 — high-intensity, caution
  - Error: #FF3B3B — failures, destructive actions
  - Info: #4A9EFF — neutral informational
- **Dark mode:** Default. This is a dark-first app.
- **Light mode:** Background #F4F4F0, surface #EAEAE6, accent #4A6ADF (toned blue). Light mode is secondary — support it but don't optimize for it.

## Spacing
- **Base unit:** 4px
- **Density:** Compact — this is a tool, not a reading experience
- **Scale:** 2xs(2) xs(4) sm(8) md(16) lg(24) xl(32) 2xl(48) 3xl(64)

## Layout
- **Approach:** Grid-disciplined, left-aligned
- **No centering** of content blocks — everything flows from the left edge
- **No cards or containers** — content fills the window naturally, separated by whitespace and hairline rules
- **Max content width:** None enforced in the desktop app (fill the window)
- **Border radius:** sm: 2px (badges, inputs), md: 4px (panels, larger elements). No large radius. No pill shapes.
- **Actions:** Inline text buttons (`browse`, `[cancel]`, `dismiss`) — not styled components

## Motion
- **Approach:** Minimal-functional
- **Allowed:** Cursor blink, spinner animation, progress bar transitions, opacity transitions on hover/focus
- **Not allowed:** Entrance animations, scroll-driven effects, typewriter on static text, breathing/pulsing on UI chrome, parallax, decorative motion
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out)
- **Duration:** micro(50-100ms) short(150-200ms) — no medium or long durations needed

## Processing UI
- Output accumulates line by line like real CLI output
- Completed steps dim to #444 (text-dim)
- Active step stays at #C9C9C9 (text primary)
- Spinner uses braille characters (⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏), not decorative loading indicators
- Wait messages rotate in #555 (text-muted), 12px

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-29 | Initial design system created | Created by /design-consultation based on competitive research (Eklipse, StreamLadder, Streamlabs) and outside voices (Codex + Claude subagent) |
| 2026-03-29 | Chose #6B8AFF soft blue over #39FF14 green | Green was too flashy — doesn't fit "sits next to OBS and Discord." Blue is familiar to gamers (Discord, VS Code) without being generic |
| 2026-03-29 | Single monospace family (JetBrains Mono) | Pure monospace signals "serious tool." No sans-serif layer needed — VodTool has no long prose |
| 2026-03-29 | Beat timeline-as-waveform noted as direction to explore | Signal lane concept (vertical beat markers on horizontal timeline) is promising but needs its own UX exploration — not a design system specification |
