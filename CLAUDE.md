# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a single-file Python 3 CLI tool (`encode.py`) for interactive video transcoding. It generates and queues FFmpeg commands for AV1 encoding with HDR/Dolby Vision support.

## Running the Tool

```bash
# Encode a single video interactively
python3 encode.py <input.mkv>

# Batch mode — encode all .mkv files in a directory (e.g. a TV season)
python3 encode.py <directory/>

# Append FFmpeg command to batch file instead of queuing (single file only)
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

`main()` dispatches to `run_single_file()` or `run_batch()` depending on whether the input path is a file or directory. Both modes share two core helpers:

- **`build_encode_config(streams, input_file, args)`** — runs all interactive prompts (resolution, DV/HDR, rate control, audio, subtitles) and returns a config dict
- **`build_ffmpeg_command(input_path, output_path, config, args)`** — constructs the FFmpeg command list from a config dict

### Single file flow
1. Probe with `get_ffprobe_info()`, detect HDR/DV via `get_hdr_info()` / `get_dv_flags()`
2. `build_encode_config()` — interactive prompts
3. Prompt for output filename
4. `build_ffmpeg_command()` → `write_batch_command()` (`--print`) or `submit_to_pueue()`

### Batch flow
1. Glob all `.mkv` files in the directory, probe each with ffprobe
2. `check_stream_consistency()` compares audio/subtitle stream counts and languages against the first file; flags any per-file differences
3. If inconsistent, show the report and reference stream list, then ask the user whether to continue
4. `build_encode_config()` once (based on first file), then loop — `build_ffmpeg_command()` + `submit_to_pueue()` per episode
5. Output filenames are auto-generated via `generate_filename()`, which detects `SxxExx` episode patterns

### Encoder defaults
- Codec: `libsvtav1`, preset 6, GOP 240, B-frames 2
- Audio: Opus via `libopus`; bitrate auto-selected by channel count (96k mono → 384k 7.1)
- HDR metadata preserved for Dolby Vision, HDR10, HDR10+
