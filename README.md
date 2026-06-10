# avicode

An interactive CLI for transcoding video to **AV1**, built around FFmpeg and [pueue](https://github.com/Nukesor/pueue). It probes a source file, walks you through a few prompts (resolution, HDR/Dolby Vision, rate control, audio, subtitles), then builds and queues the FFmpeg command for you.

## Features

- **AV1 encoding** via `libsvtav1` with sensible defaults (preset 6, GOP 240, 2 B-frames).
- **HDR / Dolby Vision aware** — preserves HDR10, HDR10+, and Dolby Vision metadata. DV Profile 7 files are scanned with [`dovi_convert`](https://github.com/cryptochrome/dovi_convert) and flagged FEL (Complex) → unsafe vs. MEL/convertible → safe.
- **Batch mode** — point it at a directory (e.g. a TV season) to encode every `.mkv`, with a stream-consistency check across episodes and automatic `SxxExx` filename generation.
- **Bilingual subtitle merge** — combine two text subtitle tracks into one ASS track for language learning (learning language bottom-right in white, reference bottom-left in grey).
- **Flexible rate control** — VBR (default), CRF, or Passthrough to remux without re-encoding.
- **Per-stream audio** — Opus (`libopus`) with bitrate auto-selected by channel count, or `copy`.
- **Queued, low-priority jobs** — submitted to pueue and run with `nice -n 19 ionice -c 3`.

## Requirements

| Dependency | Notes |
|---|---|
| Python 3 | `pysubs2` required only for bilingual subtitle merging |
| FFmpeg (Jellyfin build) | expected at `/usr/lib/jellyfin-ffmpeg/ffmpeg` |
| ffprobe | resolved via `PATH` |
| pueue | resolved via `PATH` (optional when using `--print`) |
| `dovi_convert.py` | bundled; v8+ needs `mkvmerge`, `mkvextract`, `dovi_tool`, `mediainfo` |

```bash
# Project venv (used by the bundled dovi_convert.py)
pip install pysubs2
```

## Usage

```bash
# Encode a single video interactively
python3 encode.py <input.mkv>

# Batch mode — encode every .mkv in a directory
python3 encode.py <directory/>

# Append the FFmpeg command to the batch file instead of queuing (single file only)
python3 encode.py <input.mkv> --print

# Create a 60-second test clip
python3 encode.py <input.mkv> --test
```

## Configuration

Environment-specific paths are hardcoded near the top of `encode.py` (lines 13–16) and must be adjusted for your setup:

| Constant | Default |
|---|---|
| `DOVI_PYTHON` | `/opt/avicode/venv/bin/python` |
| `DOVI_SCRIPT` | `/opt/avicode/dovi_convert.py` |
| `BATCH_FILE` | `~/.bin/batch-encode.sh` |
| `TARGET_DIR` | `/media/bluecon/video/encode` |

The FFmpeg binary path (`/usr/lib/jellyfin-ffmpeg/ffmpeg`) is also hardcoded.

## Credits

`dovi_convert.py` is a third-party tool by **cryptochrome**, distributed under the GPLv3 — see [github.com/cryptochrome/dovi_convert](https://github.com/cryptochrome/dovi_convert). Pull updates from upstream rather than editing the bundled copy.
