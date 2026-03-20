# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a single-file Python 3 CLI tool (`encode.py`) for interactive video transcoding. It generates and queues FFmpeg commands for AV1 encoding with HDR/Dolby Vision support.

## Running the Tool

```bash
# Encode a video interactively
python3 encode.py <input.mkv>

# Append FFmpeg command to batch file instead of queuing
python3 encode.py <input.mkv> --print

# Create a 60-second test clip
python3 encode.py <input.mkv> --test
```

No installation or build step required — all imports are from the Python standard library.

## External Dependencies

The script expects these tools/paths to exist:

| Dependency | Path |
|---|---|
| FFmpeg (Jellyfin build) | `/usr/lib/jellyfin-ffmpeg/ffmpeg` |
| ffprobe | resolved via `shutil.which` |
| pueue | resolved via `shutil.which` (optional with `--print`) |
| Dolby Vision scanner | `/opt/dovi_convert/venv/bin/python` + `/opt/dovi_convert/dovi_convert.py` |
| Batch output file | `~/.bin/batch-encode.sh` |
| Default output directory | `/media/bluecon/video/encode/` |

These paths are hardcoded at the top of `encode.py` (lines 11–15) and must be adjusted for different environments.

## Architecture

The script is structured as a single linear flow with grouped helper functions:

1. **Probe phase** — `get_ffprobe_info()`, `get_hdr_info()`, `scan_dovi_profile()`: reads stream metadata and detects HDR/Dolby Vision profile
2. **Interactive configuration** — prompts for resolution, rate control mode (VBR vs CRF), audio stream selection, subtitle selection, and output filename
3. **Command generation** — builds SVT-AV1 FFmpeg command with Opus audio; handles Dolby Vision Profile 7 FEL/MEL detection to set correct flags via `get_dv_flags()`
4. **Output** — either appends to batch file (`--print`) or submits to pueue job queue via `submit_to_pueue()`

### Encoder defaults
- Codec: `libsvtav1`, preset 6, GOP 240, B-frames 2
- Audio: Opus via `libopus`; bitrate auto-selected by channel count (96k mono → 384k 7.1)
- HDR metadata preserved for Dolby Vision, HDR10, HDR10+
