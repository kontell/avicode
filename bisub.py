import sys
import os
import pysrt

if len(sys.argv) < 3:
    print("Usage: python script.py <english.srt> <french.srt> [output.ass]")
    sys.exit(1)

eng_path = sys.argv[1]
fra_path = sys.argv[2]

# Optional output filename
if len(sys.argv) >= 4:
    out_path = sys.argv[3]
else:
    base = os.path.splitext(os.path.basename(eng_path))[0]
    out_path = f"{base}_bilingual.ass"

eng = pysrt.open(eng_path)
fra = pysrt.open(fra_path)

def srt_time_to_ass(t):
    return f"{t.hours}:{t.minutes:02}:{t.seconds:02}.{int(t.milliseconds/10):02}"

def clean_text(text):
    return text.replace("\n", "\\N")

with open(out_path, "w", encoding="utf-8") as f:
    # --- HEADER ---
    f.write("""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: English,Arial,42,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,1,2,0,2,50,50,120,1
Style: French,Arial,38,&H0000FFFF,&H000000FF,&H00000000,&H64000000,0,0,1,2,0,2,50,50,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""")

    for i in range(min(len(eng), len(fra))):
        e = eng[i]
        fr = fra[i]

        start = srt_time_to_ass(e.start)
        end = srt_time_to_ass(e.end)

        eng_text = clean_text(e.text)
        fra_text = clean_text(fr.text)

        # French (upper line)
        f.write(f"Dialogue: 0,{start},{end},French,,0,0,0,,{fra_text}\n")

        # English (lower line)
        f.write(f"Dialogue: 0,{start},{end},English,,0,0,0,,{eng_text}\n")

print(f"Done → {out_path}")
