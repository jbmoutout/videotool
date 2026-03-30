# PyInstaller spec for bundling videotool CLI into a standalone binary.
# Used by Tauri to include videotool inside the DMG via tauri.conf.json `externalBin`.
#
# Build:
#   source .venv/bin/activate
#   pyinstaller videotool.spec
#
# Output: dist/videotool  (single binary, uses API providers — no local ML deps)

import sys
from pathlib import Path

block_cipher = None

# Entry point: the videotool CLI
a = Analysis(
    ["src/videotool/cli.py"],
    pathex=[str(Path("src").resolve())],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Commands used by Tauri app (beats pipeline)
        "videotool.commands.ingest",
        "videotool.commands.transcribe",
        "videotool.commands.llm_beats",
        # Other commands loaded dynamically via typer
        "videotool.commands.chunks",
        "videotool.commands.compare_llm",
        "videotool.commands.cutplan",
        "videotool.commands.diarize_review",
        "videotool.commands.embed",
        "videotool.commands.explain_chunk",
        "videotool.commands.export",
        "videotool.commands.inspect_topic",
        "videotool.commands.label_topics",
        "videotool.commands.list_topics",
        "videotool.commands.llm_topics",
        "videotool.commands.merge_topics",
        "videotool.commands.segment_topics",
        "videotool.commands.show_topics",
        "videotool.commands.topics",
        # API clients
        "anthropic",
        "openai",
        # Twitch downloader (streamlink API + plugin)
        "streamlink",
        "streamlink.plugins.twitch",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ML deps not needed — Tauri app uses API providers, not local models
        "torch",
        "torchvision",
        "torchaudio",
        "pyannote",
        "whisper",
        "sentence_transformers",
        "sklearn",
        "scipy",
        "numpy",
        "matplotlib",
        "pandas",
        "IPython",
        "notebook",
        "pytest",
        "black",
        "ruff",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="videotool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # CLI tool — needs stdout/stderr
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # None = native arch (arm64 on M-series, x86_64 on Intel)
    codesign_identity=None,
    entitlements_file=None,
)
