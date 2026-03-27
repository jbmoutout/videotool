# PyInstaller spec for bundling vodtool CLI into a standalone binary.
# Used by Tauri to include vodtool inside the DMG via tauri.conf.json `externalBin`.
#
# Build:
#   source .venv/bin/activate
#   pyinstaller vodtool.spec
#
# Output: dist/vodtool  (single binary, ~80-120MB on macOS)

import sys
from pathlib import Path

block_cipher = None

# Entry point: the vodtool CLI
a = Analysis(
    ["src/vodtool/cli.py"],
    pathex=[str(Path("src").resolve())],
    binaries=[],
    datas=[],
    hiddenimports=[
        # vodtool commands — all loaded dynamically via typer
        "vodtool.commands.chunks",
        "vodtool.commands.compare_llm",
        "vodtool.commands.cutplan",
        "vodtool.commands.diarize",
        "vodtool.commands.diarize_review",
        "vodtool.commands.embed",
        "vodtool.commands.explain_chunk",
        "vodtool.commands.export",
        "vodtool.commands.ingest",
        "vodtool.commands.inspect_topic",
        "vodtool.commands.label_topics",
        "vodtool.commands.list_topics",
        "vodtool.commands.llm_topics",
        "vodtool.commands.merge_topics",
        "vodtool.commands.segment_topics",
        "vodtool.commands.show_topics",
        "vodtool.commands.topics",
        "vodtool.commands.transcribe",
        # Optional LLM deps — present at runtime if installed
        "anthropic",
        "openai",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy ML deps not needed for the pipeline — reduce binary size
        "torch",
        "torchvision",
        "torchaudio",
        "pyannote",
        "matplotlib",
        "IPython",
        "notebook",
        "pytest",
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
    name="vodtool",
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
