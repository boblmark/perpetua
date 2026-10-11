#!/usr/bin/env python3
"""Final pass: BGM bed + audio envelope + loudnorm. NO burned subtitles
(cards already carry VO text; SRT uploaded as separate file)."""
import subprocess, os

W = os.path.dirname(os.path.abspath(__file__))
RAW = f"{W}/build/raw.mp4"
OUT = f"{W}/final/ep1_final.mp4"

def probe_dur(p):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","csv=p=0",p], capture_output=True, text=True)
    return float(r.stdout.strip())

dur = int(probe_dur(RAW))
print(f"raw duration: {dur}s")
cmd = [
 "ffmpeg","-y","-v","error",
 "-i", RAW,
 "-f","lavfi","-t",str(dur),
 "-i", f"anoisesrc=color=pink:duration={dur}:sample_rate=44100:seed=42",
 "-filter_complex",
 "[1:a]lowpass=f=320,volume=-24dB[bgm];"
 "[0:a]volume='if(lt(t,2),0.7+0.15*t,1)':eval=frame[env];"
 "[env][bgm]amix=inputs=2:duration=first:normalize=0[mix];"
 "[mix]loudnorm=I=-14:TP=-1.5:LRA=11:print_format=none[out]",
 "-map","0:v","-map","[out]",
 "-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",
 "-c:a","aac","-ar","44100",
 OUT,
]
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    print("FAILED:", r.stderr[-800:]); raise SystemExit(1)
print(f"done: {OUT} ({probe_dur(OUT):.0f}s)")
