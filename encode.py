#!/usr/bin/env python3
import subprocess
import json
import sys
import re
import os
import shlex
import shutil
import argparse

# -- Configuration --
DOVI_PYTHON = "/opt/dovi_convert/venv/bin/python"
DOVI_SCRIPT = "/opt/dovi_convert/dovi_convert.py"
BATCH_FILE = os.path.expanduser("~/.bin/batch-encode.sh")
TARGET_DIR = "/media/bluecon/video/encode"

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
    cmd = [DOVI_PYTHON, DOVI_SCRIPT, "-scan", input_file]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        clean_output = strip_ansi_codes(result.stdout)
        
        if "FEL" in clean_output:
            print("   -> Detected FEL. Unsafe for Profile 8.1 conversion.")
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
                    details = f"Def: {default} | Forced: {forced}"

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
    # Base cleaning
    basename = os.path.splitext(os.path.basename(input_file))[0]
    
    # Trim logic
    match = re.search(r"(.*(?:19|20)\d{2})", basename)
    if match:
        clean_name = match.group(1).strip()
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

# -- Main Logic --
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file", help="Input MKV file")
    parser.add_argument("--print", action="store_true", help="Print to batch file")
    parser.add_argument("--test", action="store_true", help="Encode 60s test clip")
    args = parser.parse_args()

    input_abspath = os.path.abspath(args.input_file)
    if not os.path.isfile(input_abspath):
        print(f"Error: File {input_abspath} not found.")
        sys.exit(1)

    # -- PARTIAL FILE LOGIC --
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

    # -- Interactive Config --
    
    # 1. Video & Resolution
    video_stream = next((s for s in streams if s['codec_type'] == 'video'), None)
    is_uhd = (video_stream.get('width', 0) or 0) >= 3800
    downscale = False
    
    if is_uhd:
        if input("Detected 2160p. Downscale to 1080p? [y/N]: ").strip().lower() == "y":
            downscale = True
            is_uhd = False

    # 2. HDR / DV Status
    dv_flags = get_dv_flags(streams, input_abspath)
    hdr_info_str = get_hdr_info(video_stream) if video_stream else ""
    is_hdr10_source = "HDR10" in hdr_info_str or "Mastering display metadata" in str(video_stream)

    # 3. Rate Control
    rc_input = input("Rate Control: (V)BR or (C)RF? [VBR]: ").strip().upper()
    rc_mode = rc_input if rc_input else "V"

    vid_params = ["-c:v", "libsvtav1", "-preset", "6", "-g", "240", "-bf", "2"]
    vid_meta = [] # Track video stream metadata
    
    if rc_mode == "C":
        crf = input("Enter CRF value [24]: ").strip() or "24"
        vid_params.extend(["-crf", crf])
    else:
        default_bitrate = "20000k" if is_uhd else "4500k"
        bitrate = input(f"Enter target VBR bitrate [{default_bitrate}]: ").strip() or default_bitrate
        
        vid_params.extend(["-rc", "1", "-b:v", bitrate])
        
        # Inject target bitrate into BPS metadata
        try:
            bps_val = str(int(bitrate.lower().replace("k", "")) * 1000)
            vid_meta.extend(["-metadata:s:v:0", f"BPS={bps_val}"])
        except ValueError:
            pass # Failsafe in case of weird input like '20M'

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
    sub_streams = [s for s in streams if s['codec_type'] == 'subtitle']
    if sub_streams:
        s_indices = [s['index'] for s in sub_streams]
        sel = input(f"Select Subtitle Indices (e.g. {','.join(map(str, s_indices))} or 'none') [none]: ")
        
        if sel and sel.lower() != "none":
            sel_indices = [int(x) for x in sel.split(",") if x.strip().isdigit()]
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

    # 6. Filename
    dv_active = len(dv_flags) > 0
    default_name = generate_filename(ffmpeg_input, is_uhd, dv_active, is_hdr10_source)
    if args.test:
        default_name = default_name.replace(".mkv", ".TEST.mkv")

    default_path = os.path.join(TARGET_DIR, default_name)
    out_input = input(f"Output Filename [{default_path}]: ").strip()
    
    if not out_input:
        out_abspath = default_path
    else:
        if os.path.isabs(out_input):
            out_abspath = out_input
        else:
            out_abspath = os.path.join(TARGET_DIR, out_input)

    os.makedirs(os.path.dirname(out_abspath), exist_ok=True)
    out_abspath = os.path.abspath(out_abspath)

    # -- Construct Command --
    cmd = ["nice", "-n", "19", "ionice", "-c", "3", "/usr/lib/jellyfin-ffmpeg/ffmpeg"]
    cmd.extend(["-loglevel", "info"])
    
    if args.test:
        cmd.extend(["-ss", "00:02:00", "-t", "60"])

    cmd.extend(["-i", ffmpeg_input])

    vf = []
    if downscale:
        vf.append("scale=1920:-2:flags=lanczos")
    vf.append("format=yuv420p10le") 
    
    cmd.extend(["-vf", ",".join(vf)])
    cmd.extend(vid_params)
    cmd.extend(dv_flags)
    
    cmd.extend(["-map", "0:v:0"])
    
    # Inject video metadata here
    cmd.extend(vid_meta)
    
    cmd.extend(audio_flags)
    cmd.extend(sub_flags)
    
    cmd.extend(["-map_metadata:g", "0:g", "-movflags", "+faststart", out_abspath])

    if args.print:
        write_batch_command(cmd)
    else:
        submit_to_pueue(cmd, os.path.basename(out_abspath), delay=delay_val)

if __name__ == "__main__":
    main()
