#!/bin/bash

target_dir="/media/bluecon/video/tmp/series"

# Check if input directory is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <input_directory>"
    exit 1
fi

# Input directory from argument
input_dir="$1"

# Verify input directory exists
if [ ! -d "$input_dir" ]; then
    echo "Error: Directory '$input_dir' does not exist."
    exit 1
fi

# Function to process each encode
encode_episode() {
    local input=$1
    local output=$2

    nice -n 19 ionice -c 3 /usr/lib/jellyfin-ffmpeg/ffmpeg \
       -loglevel info \
       -hwaccel vaapi \
       -vaapi_device /dev/dri/renderD128 \
       -hwaccel_output_format vaapi \
       -i "$input" \
       -vf hwdownload,format=p010le \
       -c:v libsvtav1 \
       -preset 6 \
       -map 0:v:0 \
       -crf 30 \
       -g 240 \
       -bf 2 \
       -map 0:a:0 \
       -disposition:a:0 default \
       -c:a libopus \
       -b:a 256k \
       -metadata:s:a:0 BPS=256000 \
       -metadata:s:a:0 BPS-eng=256000 \
       -c:s copy \
       -map_metadata 0 \
       -movflags +faststart \
       "$output"

    chmod 664 "$output"
    chgrp debian-transmission "$output"
}

# Process all files matching SxxExx pattern, excluding output files
for input_file in "$input_dir"/*S[0-9][0-9]E[0-9][0-9]*.mkv; do
    # Skip if file doesn't exist or is an output file
    [ -f "$input_file" ] || continue
    [[ "$input_file" == *-1080p\ AV1\ Opus.mkv ]] && continue

    # Extract season and episode number (e.g., S01E02)
    episode=$(basename "$input_file" | grep -o 'S[0-9]\{2\}E[0-9]\{2,\}')

    # Skip if no season/episode pattern found
    [ -z "$episode" ] && continue

    # Construct output filename (preserve everything before episode number)
    prefix=$(basename "$input_file" | sed "s/$episode.*/$episode/")
    output_file="$target_dir/${prefix} - 1080p AV1 Opus.mkv"

    # Encode the episode
    echo "Encoding: $input_file -> $output_file"
    encode_episode "$input_file" "$output_file"
done
