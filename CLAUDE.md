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

No build step required. Python dependencies (install into the project venv at `/opt/avicode/venv`):

```bash
pip install pysubs2  # required only for bilingual subtitle merging
```

`dovi_convert.py` (v8) also requires these system tools: `mkvmerge`, `mkvextract`, `dovi_tool`, `mediainfo`.

## External Dependencies

The script expects these tools/paths to exist:

| Dependency | Path |
|---|---|
| FFmpeg (Jellyfin build) | `/usr/lib/jellyfin-ffmpeg/ffmpeg` |
| ffprobe | resolved via `shutil.which` |
| pueue | resolved via `shutil.which` (optional with `--print`) |
| Dolby Vision scanner | `/opt/avicode/venv/bin/python` + `/opt/avicode/dovi_convert.py` (v8) |
| Batch output file | `~/.bin/batch-encode.sh` |
| Default output directory | `/media/bluecon/video/encode/` |

These paths are hardcoded at the top of `encode.py` (lines 11–15) and must be adjusted for different environments.

## Architecture

`main()` dispatches to `run_single_file()` or `run_batch()` depending on whether the input path is a file or directory. Both modes share two core helpers:

- **`build_encode_config(streams, input_file, args)`** — runs all interactive prompts (resolution, DV/HDR, rate control, audio, subtitles) and returns a config dict
- **`build_ffmpeg_command(input_path, output_path, config, args, merged_ass_path=None)`** — constructs the FFmpeg command list from a config dict; when `merged_ass_path` is set, adds it as a second `-i` input and maps it as the final subtitle stream

### Single file flow
1. Probe with `get_ffprobe_info()`, detect HDR/DV via `get_hdr_info()` / `get_dv_flags()`; for DV Profile 7 files `scan_dovi_profile()` invokes `dovi_convert.py scan` and parses the output — "FEL (Complex)" → unsafe, "MEL" or "Action: CONVERT" → safe (the latter also matches "CONVERT*" for Simple FEL)
2. `build_encode_config()` — interactive prompts
3. Prompt for output filename
4. If bilingual merge configured: `prepare_merged_ass()` runs before submission
5. `build_ffmpeg_command()` → `write_batch_command()` (`--print`) or `submit_to_pueue()`

### Batch flow
1. Glob all `.mkv` files in the directory, probe each with ffprobe
2. `check_stream_consistency()` compares audio/subtitle stream counts and languages against the first file; flags any per-file differences
3. If inconsistent, show the report and reference stream list, then ask the user whether to continue
4. `build_encode_config()` once (based on first file), then loop per episode — optionally `prepare_merged_ass()`, then `build_ffmpeg_command()` + `submit_to_pueue()`
5. Output filenames are auto-generated via `generate_filename()`, which detects `SxxExx` episode patterns

### Bilingual subtitle merge
When 2+ subtitle streams are selected and at least two are text-based, the tool offers to merge them into a single ASS track for language learning. Image-based codecs (PGS, VOBSUB, DVB, XSUB) are excluded automatically.

- **Learning language** — bottom right, white (primary reading position)
- **Reference language** — bottom left, grey

`prepare_merged_ass()` extracts each stream to a temp ASS via ffmpeg, merges them with `pysubs2`, and writes `<output_name>.bilingual.ass` alongside the output file at submission time (so it persists for delayed pueue jobs). The merged track is added as a second `-i` input, mapped last, flagged `default`, and titled `Bilingual (XX/YY)`. Original subtitle streams are copied unchanged.

`merge_bilingual_ass()` creates a fresh `SSAFile` with explicitly defined `Learning` and `Reference` styles rather than modifying styles from the source files — source ASS streams extracted from MKV often use arbitrary style names and cannot be assumed to have a `Default` style. The output `PlayResY` is set to 1080 (font sizes are relative to this). Inline override tags (`{\fs...\c&H...&}` etc.) are stripped from all source events before merging so they cannot override the defined styles.

To re-mux an existing file without re-encoding, choose `Passthrough` at the rate control prompt and `copy` for each audio stream — only the container is touched. Video passthrough skips DV/HDR flags and video filters since the stream is copied unchanged.

### Encoder defaults
- Codec: `libsvtav1`, preset 6, GOP 240, B-frames 2
- Video rate control: VBR (default), CRF, or Passthrough (copy)
- Audio: Opus via `libopus`; bitrate auto-selected by channel count (96k mono → 384k 7.1), or `copy` per-stream
- HDR metadata preserved for Dolby Vision, HDR10, HDR10+
