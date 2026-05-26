#!/usr/bin/env python3
import subprocess
import json
import sys
import re
import os
import glob
import shlex
import shutil
import argparse

# -- Configuration --
DOVI_PYTHON = "/opt/avicode/venv/bin/python"
DOVI_SCRIPT = "/opt/avicode/dovi_convert.py"
BATCH_FILE = os.path.expanduser("~/.bin/batch-encode.sh")
TARGET_DIR = "/media/bluecon/video/encode"

IMAGE_SUBTITLE_CODECS = {'hdmv_pgs_subtitle', 'dvd_subtitle', 'dvb_subtitle', 'xsub'}

# -- Utils --
def check_dependencies(use_pueue=True):
    required = ["ffmpeg", "ffprobe"]
    if use_pueue:
        required.append("pueue")

    missing = [tool for tool in required if not shutil.which(tool)]
    if missing:
        print(f"Error: Missing required tools: {', '.join(missing)}")
        if "pueue" in missing:
            print("Install pueue: sudo apt install pueue")
        sys.exit(1)

def run_command(cmd, capture_output=True):
    try:
        result = subprocess.run(cmd, capture_output=capture_output, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(cmd)}")
        sys.exit(1)

def strip_ansi_codes(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

# -- Probe & Info --
def get_ffprobe_info(input_file):
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", input_file]
    try:
        data = json.loads(run_command(cmd))
        return data.get("streams", [])
    except:
        print("Error: Failed to probe file.")
        sys.exit(1)

def get_audio_config(stream):
    """Returns suggested (bitrate, mode) based on channel count, title, or profile."""
    channels = stream.get('channels', 2)

    # Check Metadata Title (e.g. "Surround 5.1 Atmos")
    title = stream.get('tags', {}).get('title', '').lower()

    # Check Codec Profile (e.g. "Dolby Digital Plus + Dolby Atmos")
    profile = stream.get('profile', '').lower()

    # Check Codec Long Name (fallback)
    codec_long = stream.get('codec_long_name', '').lower()

    if "atmos" in title or "atmos" in profile or "atmos" in codec_long:
        return "copy", "copy"

    if channels >= 8: return "384k", "encode" # 7.1
    if channels >= 6: return "256k", "encode" # 5.1
    if channels >= 2: return "128k", "encode" # Stereo
    return "96k", "encode"                    # Mono

def format_bitrate(val):
    try:
        if not val: return "N/A"
        if val.isdigit():
            return f"{int(val) // 1000} kb/s"
        return val
    except: return "N/A"

def get_hdr_info(stream):
    info = []
    for side in stream.get("side_data_list", []):
        stype = side.get("side_data_type", "")
        if "DOVI" in stype:
            profile = side.get("dv_profile", "?")
            info.append(f"Dolby Vision (Profile {profile})")
        elif "Mastering display metadata" in stype:
            info.append("HDR10")
        elif "HDR Dynamic Metadata" in stype:
            info.append("HDR10+")
    return " / ".join(list(set(info))) if info else ""

# -- DV Logic --
def scan_dovi_profile(input_file):
    if not os.path.exists(DOVI_PYTHON) or not os.path.exists(DOVI_SCRIPT):
        return None

    print("   -> Invoking dovi_convert -scan ...")
    cmd = [DOVI_PYTHON, DOVI_SCRIPT, "scan", input_file]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        clean_output = strip_ansi_codes(result.stdout)

        if "FEL (Complex)" in clean_output:
            print("   -> Detected Complex FEL. Unsafe for Profile 8.1 conversion.")
            return False
        if "MEL" in clean_output or "Action: CONVERT" in clean_output:
            return True
        return None
    except Exception as e:
        print(f"   -> Error running dovi_convert: {e}")
        return None

def get_dv_flags(streams, input_file):
    video_streams = [s for s in streams if s['codec_type'] == 'video']
    if not video_streams: return []

    dv_profile = None
    for side in video_streams[0].get("side_data_list", []):
        if side.get("side_data_type") == "DOVI configuration record":
            dv_profile = side.get("dv_profile")
            break

    if dv_profile is None: return []

    print(f"Detected Dolby Vision Profile {dv_profile}")
    if dv_profile == 7:
        is_safe = scan_dovi_profile(input_file)
        if is_safe is True:
            print("   -> MEL detected (Safe). Enabling Dolby Vision.")
            return ["-dolbyvision", "true"]
        elif is_safe is False:
            print("   -> FEL detected (Unsafe). Disabling Dolby Vision.")
            return []
        else:
            if input("   -> Scan inconclusive. Include DV anyway? [y/N]: ").strip().lower() == "y":
                return ["-dolbyvision", "true"]
            return []

    print(f"   -> Profile {dv_profile} is standard. Enabling Dolby Vision.")
    return ["-dolbyvision", "true"]

# -- Display --
def print_stream_list(streams):
    print(f"\nStream List (Use these INDICES for selection):")
    print("-" * 60)

    for g in ['video', 'audio', 'subtitle']:
        found = [s for s in streams if s['codec_type'] == g]
        if found:
            print(f"--- {g.upper()} ---")
            for s in found:
                idx = s['index']
                lang = s.get('tags', {}).get('language', 'und')
                codec = s.get('codec_name', 'unknown')
                title = s.get('tags', {}).get('title', '')

                details = ""
                if g == "video":
                    w, h = s.get('width', 0), s.get('height', 0)
                    hdr = get_hdr_info(s)
                    details = f"{w}x{h} | {hdr}"
                elif g == "audio":
                    ch = s.get('channels', '?')
                    br = format_bitrate(s.get('bit_rate'))
                    s_config, _ = get_audio_config(s)

                    profile = s.get('profile', '')
                    extra = ""
                    if "Atmos" in profile: extra = " (Atmos)"

                    details = f"{ch}ch | {br}{extra} | Auto: {s_config}"
                elif g == "subtitle":
                    default = "Yes" if s.get('disposition', {}).get('default') else "No"
                    forced = "Yes" if s.get('disposition', {}).get('forced') else "No"
                    image = " [image-based]" if is_image_subtitle(s) else ""
                    details = f"Def: {default} | Forced: {forced}{image}"

                line = f"Index {idx:<3} [{lang}] {codec}"
                if title: line += f" | {title}"
                if details: line += f" | {details}"
                print(line)
            print("")
    print("-" * 60 + "\n")

# -- Mapping Helper --
def get_relative_index(ff_index, stream_type, all_streams):
    rel = 0
    for s in all_streams:
        if s['codec_type'] == stream_type:
            if s['index'] == ff_index: return rel
            rel += 1
    return 0

# -- Output Generators --
def generate_filename(input_file, is_uhd, dv_active, hdr10_active):
    basename = os.path.splitext(os.path.basename(input_file))[0]

    # Try TV episode pattern first (SxxExx or SxxExxExx for multi-episode)
    ep_match = re.search(r"(.*S\d{2}E\d{2,}(?:E\d{2,})*)", basename, re.IGNORECASE)
    if ep_match:
        clean_name = ep_match.group(1).strip()
    else:
        # Fall back to year-based trimming for movies
        year_match = re.search(r"(.*(?:19|20)\d{2})", basename)
        if year_match:
            clean_name = year_match.group(1).strip()
        else:
            clean_name = basename.strip()

    # Build tags
    tags = []
    tags.append("Bluray-2160p" if is_uhd else "Bluray-1080p")
    tags.append("AV1")

    if dv_active:
        tags.append("DV")
    elif hdr10_active:
        tags.append("HDR10")

    return f"{clean_name} {' '.join(tags)}.mkv"

def write_batch_command(command):
    os.makedirs(os.path.dirname(BATCH_FILE), exist_ok=True)
    if not os.path.exists(BATCH_FILE):
        with open(BATCH_FILE, "w") as f:
            f.write("#!/bin/bash\n")
            os.chmod(BATCH_FILE, 0o755)

    # Clean formatting
    formatted = []
    split_on = [
        "-i", "-vf", "-c:v", "-dolbyvision", "-map",
        "-metadata", "-map_metadata", "-movflags"
    ]
    current_line = []
    idx = 0
    while idx < len(command):
        arg = command[idx]
        if arg == "-i": break
        current_line.append(shlex.quote(arg))
        idx += 1

    formatted.append(" ".join(current_line) + " \\")

    current_line = []
    while idx < len(command):
        arg = command[idx]
        if arg in split_on:
            if current_line:
                formatted.append("  " + " ".join(current_line) + " \\")
            current_line = [arg]
        else:
            current_line.append(shlex.quote(arg))
        idx += 1

    if current_line:
        formatted.append("  " + " ".join(current_line))

    full_block = "\n".join(formatted)

    with open(BATCH_FILE, "a") as f:
        f.write("\n" + full_block + "\n")
    print(f"Command appended to {BATCH_FILE}")

def submit_to_pueue(command, label, delay=None):
    pueue_cmd = ["pueue", "add", "--escape"]
    if delay:
        pueue_cmd.extend(["--delay", delay])
    pueue_cmd.extend(["--label", label, "--"])
    pueue_cmd.extend(command)

    print("-" * 40)
    print(f"Submitting to Queue (pueue)...")
    if delay:
        print(f"   -> Delayed start by: {delay}")

    try:
        subprocess.run(pueue_cmd, check=True)
        print(f"Job Queued in Pueue: {label}")
        print("Run 'pueue status' to view queue.")
    except Exception as e:
        print(f"Error submitting to pueue: {e}")

# -- Subtitle Merge --
def is_image_subtitle(stream):
    return stream.get('codec_name', '').lower() in IMAGE_SUBTITLE_CODECS

def extract_subtitle_to_ass(input_file, stream_index, output_path):
    """Extract a single subtitle stream to ASS format using ffmpeg."""
    cmd = [
        "/usr/lib/jellyfin-ffmpeg/ffmpeg", "-y", "-v", "quiet",
        "-i", input_file,
        "-map", f"0:{stream_index}",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError:
        print(f"Error: Failed to extract subtitle stream {stream_index} to ASS.")
        sys.exit(1)

def merge_bilingual_ass(learning_ass, reference_ass, output_ass, learning_lang="", reference_lang=""):
    """
    Merge two ASS subtitle files into a single bilingual track.
    Learning language: bottom right, white (primary reading position).
    Reference language: bottom left, grey (glanceable fallback).
    """
    try:
        import pysubs2
    except ImportError:
        print("Error: pysubs2 is required for subtitle merging.")
        print("       Install with: pip install pysubs2")
        sys.exit(1)

    doc = pysubs2.load(learning_ass)
    ref = pysubs2.load(reference_ass)

    # Build styles from scratch — don't assume any particular style name exists
    # in the source files (ASS extracted from MKV can use arbitrary style names).
    learning_style = pysubs2.SSAStyle()
    learning_style.fontname    = "Arial"
    learning_style.fontsize    = 52
    learning_style.primarycolor  = pysubs2.Color(255, 255, 255, 0)  # white
    learning_style.outlinecolor  = pysubs2.Color(0, 0, 0, 0)        # black outline
    learning_style.alignment   = 2   # numpad: bottom centre (within right half)
    learning_style.marginl     = 960
    learning_style.marginr     = 0
    learning_style.marginv     = 30

    reference_style = pysubs2.SSAStyle()
    reference_style.fontname   = "Arial"
    reference_style.fontsize   = 44
    reference_style.primarycolor = pysubs2.Color(200, 200, 200, 0)  # light grey
    reference_style.outlinecolor = pysubs2.Color(0, 0, 0, 0)        # black outline
    reference_style.alignment  = 2   # numpad: bottom centre (within left half)
    reference_style.marginl    = 0
    reference_style.marginr    = 960
    reference_style.marginv    = 30

    out = pysubs2.SSAFile()
    out.info["PlayResX"] = "1920"
    out.info["PlayResY"] = "1080"
    out.styles["Learning"]  = learning_style
    out.styles["Reference"] = reference_style

    # Strip inline override tags (e.g. {\fs48\c&HFFFFFF&}) from source events so
    # they don't override the Learning/Reference style definitions above.
    for event in doc.events:
        event.style = "Learning"
        event.text  = re.sub(r'\{[^}]*\}', '', event.text)
    for event in ref.events:
        event.style = "Reference"
        event.text  = re.sub(r'\{[^}]*\}', '', event.text)

    out.events = doc.events + ref.events
    out.sort()
    out.save(output_ass)

def prepare_merged_ass(input_file, config, out_base):
    """
    Extract and merge subtitle streams to produce a bilingual ASS file.
    out_base is the output path without extension; the .bilingual.ass file
    is written there so it persists until the queued encode runs.
    Returns the path to the merged ASS file.
    """
    mc = config['merge_config']
    merged_path = out_base + '.bilingual.ass'
    tmp_dir = os.path.join(os.path.dirname(out_base), '.subtitle-tmp')
    os.makedirs(tmp_dir, exist_ok=True)
    base_name = os.path.basename(out_base)
    tmp_learning  = os.path.join(tmp_dir, base_name + '.tmp_learning.ass')
    tmp_reference = os.path.join(tmp_dir, base_name + '.tmp_reference.ass')

    print("Preparing bilingual subtitle merge...")
    print(f"   -> Extracting stream {mc['learning']} ({mc.get('learning_lang', '?')})...")
    extract_subtitle_to_ass(input_file, mc['learning'], tmp_learning)
    print(f"   -> Extracting stream {mc['reference']} ({mc.get('reference_lang', '?')})...")
    extract_subtitle_to_ass(input_file, mc['reference'], tmp_reference)
    print("   -> Merging...")
    merge_bilingual_ass(tmp_learning, tmp_reference, merged_path,
                        mc.get('learning_lang', ''), mc.get('reference_lang', ''))
    os.unlink(tmp_learning)
    os.unlink(tmp_reference)
    print(f"   -> Written: {os.path.basename(merged_path)}")
    return merged_path

# -- Batch Consistency Check --
def get_stream_signature(streams):
    """Returns a comparable signature of audio and subtitle streams."""
    audio = [
        (s.get('tags', {}).get('language', 'und'), s.get('channels', 0), s.get('codec_name', ''))
        for s in streams if s['codec_type'] == 'audio'
    ]
    subs = [
        (s.get('tags', {}).get('language', 'und'), s.get('codec_name', ''))
        for s in streams if s['codec_type'] == 'subtitle'
    ]
    return {'audio': audio, 'subtitle': subs}

def check_stream_consistency(file_streams_map):
    """
    Compare stream layout across all files against the first file.
    Returns (is_consistent: bool, inconsistencies: dict[filepath -> list[str]])
    """
    files = list(file_streams_map.keys())
    if len(files) <= 1:
        return True, {}

    ref_file = files[0]
    ref_sig = get_stream_signature(file_streams_map[ref_file])
    inconsistencies = {}

    for f in files[1:]:
        sig = get_stream_signature(file_streams_map[f])
        issues = []

        # Audio
        if len(sig['audio']) != len(ref_sig['audio']):
            issues.append(
                f"Audio stream count: {len(sig['audio'])} vs {len(ref_sig['audio'])} in reference"
            )
        else:
            for i, (a, ref_a) in enumerate(zip(sig['audio'], ref_sig['audio'])):
                if a[0] != ref_a[0]:
                    issues.append(f"Audio stream {i}: language '{a[0]}' vs '{ref_a[0]}' in reference")
                if a[1] != ref_a[1]:
                    issues.append(f"Audio stream {i}: {a[1]}ch vs {ref_a[1]}ch in reference")

        # Subtitles
        if len(sig['subtitle']) != len(ref_sig['subtitle']):
            issues.append(
                f"Subtitle stream count: {len(sig['subtitle'])} vs {len(ref_sig['subtitle'])} in reference"
            )
        else:
            for i, (s, ref_s) in enumerate(zip(sig['subtitle'], ref_sig['subtitle'])):
                if s[0] != ref_s[0]:
                    issues.append(f"Subtitle stream {i}: language '{s[0]}' vs '{ref_s[0]}' in reference")

        if issues:
            inconsistencies[f] = issues

    return len(inconsistencies) == 0, inconsistencies

# -- Encode Config Builder --
def build_encode_config(streams, input_file, args):
    """
    Run interactive prompts to build encode configuration.
    Returns a dict with all parameters needed to construct FFmpeg commands.
    """
    # 1. Video & Resolution
    video_stream = next((s for s in streams if s['codec_type'] == 'video'), None)
    is_uhd = (video_stream.get('width', 0) or 0) >= 3800
    downscale = False

    if is_uhd:
        if input("Detected 2160p. Downscale to 1080p? [y/N]: ").strip().lower() == "y":
            downscale = True
            is_uhd = False

    # 2. HDR / DV Status
    dv_flags = get_dv_flags(streams, input_file)
    dv_profile = next(
        (s.get("dv_profile") for s in (video_stream or {}).get("side_data_list", [])
         if s.get("side_data_type") == "DOVI configuration record"),
        None
    )
    hdr_info_str = get_hdr_info(video_stream) if video_stream else ""
    is_hdr10_source = "HDR10" in hdr_info_str or "Mastering display metadata" in str(video_stream)

    # 3. Rate Control
    rc_input = input("Rate Control: (V)BR, (C)RF, or (P)assthrough/copy? [VBR]: ").strip().upper()
    rc_mode = rc_input if rc_input in ("V", "C", "P") else "V"

    vid_meta = []

    if rc_mode == "P":
        vid_params = ["-c:v", "copy"]
        dv_flags = []
    else:
        vid_params = ["-c:v", "libsvtav1", "-preset", "6", "-g", "240", "-bf", "2"]
        if rc_mode == "C":
            crf = input("Enter CRF value [24]: ").strip() or "24"
            vid_params.extend(["-crf", crf])
        else:
            default_bitrate = "20000k" if is_uhd else "4500k"
            bitrate = input(f"Enter target VBR bitrate [{default_bitrate}]: ").strip() or default_bitrate
            vid_params.extend(["-rc", "1", "-b:v", bitrate])
            try:
                bps_val = str(int(bitrate.lower().replace("k", "")) * 1000)
                vid_meta.extend(["-metadata:s:v:0", f"BPS={bps_val}"])
            except ValueError:
                pass

    # 4. Audio
    audio_flags = []
    audio_streams = [s for s in streams if s['codec_type'] == 'audio']
    if audio_streams:
        a_indices = [s['index'] for s in audio_streams]
        sel = input(f"Select Audio Indices (e.g. {','.join(map(str, a_indices))}) [Default: First]: ")
        sel_indices = [int(x) for x in sel.split(",")] if sel and sel.strip() else [a_indices[0]]

        def_idx = sel_indices[0]
        if len(sel_indices) > 1:
            d = input(f"Which index is Default? [{def_idx}]: ")
            if d.isdigit() and int(d) in sel_indices: def_idx = int(d)

        for i, idx in enumerate(sel_indices):
            rel = get_relative_index(idx, "audio", streams)
            s_info = next(s for s in streams if s['index'] == idx)
            lang = s_info.get('tags', {}).get('language', 'und')

            audio_flags.extend(["-map", f"0:a:{rel}"])
            disp = "default" if idx == def_idx else "0"
            audio_flags.extend([f"-disposition:a:{i}", disp])

            rec_br, mode = get_audio_config(s_info)
            prompt = f"Audio {idx} [{lang}] ({s_info.get('channels','?')}ch): Bitrate/Copy [{rec_br}]: "
            choice = input(prompt).strip() or rec_br

            if choice.lower() == "copy":
                audio_flags.extend([f"-c:a:{i}", "copy"])
            else:
                audio_flags.extend([f"-c:a:{i}", "libopus", f"-b:a:{i}", choice])
                try:
                    bps_val = str(int(choice.lower().replace("k", "")) * 1000)
                    audio_flags.extend([f"-metadata:s:a:{i}", f"BPS={bps_val}"])
                    if lang != 'und':
                        audio_flags.extend([f"-metadata:s:a:{i}", f"BPS-{lang}={bps_val}"])
                except: pass

                audio_flags.extend([f"-metadata:s:a:{i}", "DURATION="])
                audio_flags.extend([f"-metadata:s:a:{i}", "_STATISTICS_TAGS="])
                audio_flags.extend([f"-metadata:s:a:{i}", "_STATISTICS_WRITING_APP="])
                audio_flags.extend([f"-metadata:s:a:{i}", "_STATISTICS_WRITING_DATE_UTC="])

    # 5. Subtitles
    sub_flags = []
    subtitle_count = 0
    merge_config = None
    sub_streams = [s for s in streams if s['codec_type'] == 'subtitle']

    if sub_streams:
        s_indices = [s['index'] for s in sub_streams]
        sel = input(f"Select Subtitle Indices (e.g. {','.join(map(str, s_indices))} or 'none') [none]: ")

        if sel and sel.lower() != "none":
            sel_indices = [int(x) for x in sel.split(",") if x.strip().isdigit()]
            subtitle_count = len(sel_indices)
            def_idx = sel_indices[0] if len(sel_indices) == 1 else None

            if len(sel_indices) > 1:
                d = input("Which Subtitle is Default? [None]: ")
                if d.isdigit() and int(d) in sel_indices: def_idx = int(d)

            for i, idx in enumerate(sel_indices):
                rel = get_relative_index(idx, "subtitle", streams)
                sub_flags.extend(["-map", f"0:s:{rel}"])
                disp = "default" if idx == def_idx else "0"
                sub_flags.extend([f"-disposition:s:{i}", disp])

            sub_flags.extend(["-c:s", "copy"])

            # Bilingual merge prompt — requires 2+ text-based streams
            if len(sel_indices) >= 2:
                text_subs = [
                    idx for idx in sel_indices
                    if not is_image_subtitle(next(s for s in streams if s['index'] == idx))
                ]
                if len(text_subs) >= 2:
                    if input("Merge two subtitle streams into a bilingual ASS track? [y/N]: ").strip().lower() == 'y':
                        print("  Text-based streams available:")
                        for idx in text_subs:
                            s = next(s for s in streams if s['index'] == idx)
                            lang = s.get('tags', {}).get('language', 'und')
                            print(f"    Index {idx} [{lang}] {s.get('codec_name', '')}")

                        l_def = str(text_subs[0])
                        r_def = str(text_subs[1])
                        l_in = input(f"  Learning language stream — right, white [{l_def}]: ").strip() or l_def
                        r_in = input(f"  Reference language stream — left, grey [{r_def}]: ").strip() or r_def

                        if (l_in.isdigit() and r_in.isdigit()
                                and int(l_in) in text_subs
                                and int(r_in) in text_subs
                                and l_in != r_in):
                            l_idx, r_idx = int(l_in), int(r_in)
                            l_lang = next(s for s in streams if s['index'] == l_idx).get('tags', {}).get('language', 'und')
                            r_lang = next(s for s in streams if s['index'] == r_idx).get('tags', {}).get('language', 'und')
                            merge_config = {
                                'learning':      l_idx,
                                'reference':     r_idx,
                                'learning_lang':  l_lang,
                                'reference_lang': r_lang,
                            }
                            print(f"  Bilingual track: {l_lang.upper()} (right) / {r_lang.upper()} (left)")
                        else:
                            print("  Invalid selection, skipping merge.")

    return {
        'vid_params':     vid_params,
        'vid_meta':       vid_meta,
        'dv_flags':       dv_flags,
        'dv_profile':     dv_profile,
        'audio_flags':    audio_flags,
        'sub_flags':      sub_flags,
        'subtitle_count': subtitle_count,
        'merge_config':   merge_config,
        'is_uhd':         is_uhd,
        'is_hdr10_source': is_hdr10_source,
        'downscale':      downscale,
    }

# -- FFmpeg Command Builder --
def build_ffmpeg_command(input_path, output_path, config, args, merged_ass_path=None):
    """Construct the full FFmpeg command list from a config dict."""
    cmd = ["nice", "-n", "19", "ionice", "-c", "3", "/usr/lib/jellyfin-ffmpeg/ffmpeg"]
    cmd.extend(["-loglevel", "info"])

    if args.test:
        cmd.extend(["-ss", "00:02:00", "-t", "60"])

    cmd.extend(["-i", input_path])
    if merged_ass_path:
        cmd.extend(["-i", merged_ass_path])

    is_copy = config['vid_params'] == ["-c:v", "copy"]
    if not is_copy:
        vf = []
        if config['downscale']:
            vf.append("scale=1920:-2:flags=lanczos")
        vf.append("format=yuv420p10le")
        if config.get('dv_profile') == 5 and config.get('dv_flags'):
            vf.append("setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv")
        cmd.extend(["-vf", ",".join(vf)])

    cmd.extend(config['vid_params'])
    cmd.extend(config['dv_flags'])
    cmd.extend(["-map", "0:v:0"])
    cmd.extend(config['vid_meta'])
    cmd.extend(config['audio_flags'])
    cmd.extend(config['sub_flags'])

    if merged_ass_path:
        mc = config.get('merge_config', {})
        n = config.get('subtitle_count', 0)
        l_lang = mc.get('learning_lang', '').upper()
        r_lang = mc.get('reference_lang', '').upper()
        title = f"Bilingual ({l_lang}/{r_lang})" if l_lang and r_lang else "Bilingual"
        cmd.extend(["-map", "1:0"])
        cmd.extend([f"-disposition:s:{n}", "default"])
        cmd.extend([f"-metadata:s:s:{n}", f"title={title}"])

    cmd.extend(["-map_metadata:g", "0:g", "-movflags", "+faststart", output_path])
    return cmd

# -- Single File Mode --
def run_single_file(input_abspath, args):
    ffmpeg_input = input_abspath
    delay_val = None

    if input_abspath.endswith(".part"):
        print("\n[!] Partial Download Detected (.part)")
        ffmpeg_input = input_abspath[:-5]
        print(f"    -> Target Input: {os.path.basename(ffmpeg_input)}")
        user_delay = input("    -> Enter delay time (e.g. 3h, 30m) [3h]: ").strip()
        delay_val = user_delay if user_delay else "3h"

    check_dependencies(use_pueue=not args.print)

    streams = get_ffprobe_info(input_abspath)
    print_stream_list(streams)

    config = build_encode_config(streams, input_abspath, args)

    dv_active = len(config['dv_flags']) > 0
    default_name = generate_filename(ffmpeg_input, config['is_uhd'], dv_active, config['is_hdr10_source'])
    if args.test:
        default_name = default_name.replace(".mkv", ".TEST.mkv")

    default_path = os.path.join(TARGET_DIR, default_name)
    out_input = input(f"Output Filename [{default_path}]: ").strip()

    if not out_input:
        out_abspath = default_path
    elif os.path.isabs(out_input):
        out_abspath = out_input
    else:
        out_abspath = os.path.join(TARGET_DIR, out_input)

    os.makedirs(os.path.dirname(out_abspath), exist_ok=True)
    out_abspath = os.path.abspath(out_abspath)

    merged_ass_path = None
    if config.get('merge_config'):
        out_base = os.path.splitext(out_abspath)[0]
        merged_ass_path = prepare_merged_ass(ffmpeg_input, config, out_base)

    cmd = build_ffmpeg_command(ffmpeg_input, out_abspath, config, args, merged_ass_path=merged_ass_path)

    if args.print:
        write_batch_command(cmd)
    else:
        submit_to_pueue(cmd, os.path.basename(out_abspath), delay=delay_val)

# -- Batch Mode --
def run_batch(directory, args):
    check_dependencies(use_pueue=True)

    # Find MKV files, sorted by name
    mkv_files = sorted(glob.glob(os.path.join(directory, "*.mkv")))
    if not mkv_files:
        print(f"Error: No .mkv files found in '{directory}'.")
        sys.exit(1)

    print(f"Found {len(mkv_files)} file(s) in '{os.path.basename(directory)}':")
    for f in mkv_files:
        print(f"  {os.path.basename(f)}")

    # Probe all files
    print(f"\nProbing {len(mkv_files)} file(s)...")
    all_streams = {}
    for f in mkv_files:
        print(f"  -> {os.path.basename(f)}")
        all_streams[f] = get_ffprobe_info(f)

    # Check consistency
    print("\nChecking stream consistency...")
    consistent, inconsistencies = check_stream_consistency(all_streams)

    first_file = mkv_files[0]

    if not consistent:
        print("\n[!] Stream inconsistencies detected vs. reference file:")
        print(f"    Reference: {os.path.basename(first_file)}")
        print("")
        for filepath, issues in inconsistencies.items():
            print(f"  {os.path.basename(filepath)}:")
            for issue in issues:
                print(f"    - {issue}")

        print(f"\nReference streams ({os.path.basename(first_file)}):")
        print_stream_list(all_streams[first_file])

        cont = input("Streams are inconsistent. Continue with first file's config? [y/N]: ").strip().lower()
        if cont != 'y':
            print("Aborting.")
            sys.exit(0)
    else:
        print("All files have consistent streams.")
        print(f"\nConfiguring encode based on: {os.path.basename(first_file)}")
        print_stream_list(all_streams[first_file])

    config = build_encode_config(all_streams[first_file], first_file, args)

    # Output directory
    out_dir_input = input(f"Output directory [{TARGET_DIR}]: ").strip()
    out_dir = out_dir_input if out_dir_input else TARGET_DIR
    os.makedirs(out_dir, exist_ok=True)

    # Queue each file
    dv_active = len(config['dv_flags']) > 0
    print(f"\nQueuing {len(mkv_files)} encode(s) to pueue...")

    for input_file in mkv_files:
        out_name = generate_filename(input_file, config['is_uhd'], dv_active, config['is_hdr10_source'])
        if args.test:
            out_name = out_name.replace(".mkv", ".TEST.mkv")
        out_path = os.path.join(out_dir, out_name)
        out_base = os.path.splitext(out_path)[0]

        merged_ass_path = None
        if config.get('merge_config'):
            print(f"\n{os.path.basename(input_file)}:")
            merged_ass_path = prepare_merged_ass(input_file, config, out_base)

        cmd = build_ffmpeg_command(input_file, out_path, config, args, merged_ass_path=merged_ass_path)
        submit_to_pueue(cmd, os.path.basename(out_path))

    print(f"\nDone. {len(mkv_files)} job(s) queued.")

# -- Main --
def main():
    parser = argparse.ArgumentParser(
        description="Interactive AV1 encode tool. Accepts a single file or a directory of episodes."
    )
    parser.add_argument("input_path", help="Input MKV file or directory of episodes (batch mode)")
    parser.add_argument("--print", action="store_true", help="Append command to batch file (single file mode only)")
    parser.add_argument("--test", action="store_true", help="Encode 60s test clip")
    args = parser.parse_args()

    input_abspath = os.path.abspath(args.input_path)

    if os.path.isdir(input_abspath):
        if args.print:
            print("Warning: --print is not supported in batch mode. Jobs will be submitted to pueue.")
        run_batch(input_abspath, args)
    elif os.path.isfile(input_abspath):
        run_single_file(input_abspath, args)
    else:
        print(f"Error: '{input_abspath}' is not a valid file or directory.")
        sys.exit(1)

if __name__ == "__main__":
    main()
