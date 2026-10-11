#!/usr/bin/env python3
"""EP1 AI UNHINGED assembly: cards + clips -> 1920x1080 long-form."""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json, os, re, subprocess, sys, textwrap
from collections import defaultdict
from PIL import Image, ImageDraw, ImageFont

W = os.path.dirname(os.path.abspath(__file__))
SRC = f"{W}/sources"
TTS = f"{W}/tts/seg"
BUILD = f"{W}/build"
FINAL = f"{W}/final"
os.makedirs(BUILD, exist_ok=True)
os.makedirs(FINAL, exist_ok=True)

FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FBI = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"  # no BoldOblique on system; use regular italic-ish

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print("CMD FAILED:", " ".join(cmd[:6]), r.stderr[-500:])
        raise SystemExit(1)
    return r

def valid_mp4(p):
    if not os.path.exists(p) or os.path.getsize(p) < 10000:
        return False
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","csv=p=0",p], capture_output=True, text=True)
    try:
        return float(r.stdout.strip()) > 0.5
    except Exception:
        return False
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print("CMD FAILED:", " ".join(cmd[:6]), r.stderr[-500:])
        raise SystemExit(1)
    return r

def probe_dur(p):
    r = run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p])
    return float(r.stdout.strip())

# ---------- score data ----------
SCORES = {
 "clip1":(6,"Knows gravity. Chooses not to."),
 "clip2":(7,"Broke gravity. Forgot to tell the cast."),
 "clip3":(8,"Beautiful. Illegal. Both."),
 "clip4":(8,"Ran out of tokens mid-room."),
 "clip5":(9,"Panicked. Hit undo. Relatable."),
 "clip6":(9,"Shadow received a text message."),
 "clip7":(8,"Two walls. Could not commit."),
 "clip8":(7,"Too realistic to be funny."),
 "clip9":(9,"Nailed the impact. Missed the cause."),
 "clip10":(8,"Lost an argument with a motor."),
 "clip11":(8,"Good karma. Bad meteorology."),
 "clip12":(9,"The grass was fine."),
 "clip13_14":(10,"Perfect archetype. Zero continuity."),
 "clip15":(8,"Built the emotion machine. Forgot the part where you care."),
 "clip16":(7,"Found the formula. Executed it. Nothing there."),
 "clip17":(6,"Shape of a happy ending. No contents."),
 "clip18":(7,"No showrunner. Never was."),
 "clip19":(8,"A movie about a word."),
 "clip20":(9,"Four inches tall. Lives on a floor. Had a plan."),
 "clip21":(9,"Bag: detonated."),
 "clip22":(8,"Counted to fifteen."),
 "clip23":(8,"Learned the word 'escalate'."),
 "clip24":(7,"Buried the irony."),
 "clip25":(9,"Felt something real."),
 "clip26":(10,"Best face of the week."),
 "clip27":(8,"Most deserved fall."),
 "clip28":(7,"Applied both punishments."),
 "finale":(10,"Broke her day. Kept the physics. That's a joke."),
}
CLIP_SRC = {
 "cold":"GsepiwYE9L8","clip1":"jc6Auc0aZlI","clip2":"kRD9PI64uPE","clip3":"pbNN4uYeoTk",
 "clip4":"C9S1coT8h98","clip5":"thaPylqVDVc","clip6":"H0YX_yYuX-Q","clip7":"eifnsCih2nw",
 "clip8":"ql5gvUlPC8U","clip9":"t5p6BuQsxAk","clip10":"XKZ0z2M-sU0","clip11":"nlFsmgODh8g",
 "clip12":"VnsQBCpBHJI","clip13a":"vUGTIwA35i4","clip13b":"NlFI6_6D07w",
 "clip15":"OZDzY9qR2SE","clip16":"avPE52EqR8w","clip17":"WKmN9kLPL0c","clip18":"IWADhrv_A-s",
 "clip19":"-cpc_PL-Uvc","clip20":"Ji2qoAFw8Xk","clip21":"AwKaxGQdEBk","clip22":"yBmyZriJang",
 "clip23":"ntIEXwAjyrI","clip24":"aanwqPw1xis","clip25":"apeZFZaAMqU","clip26":"559Z6E87bCg",
 "clip27":"Nk7uTP-nzDY","clip28":"CDm4gB63WnA","finale":"faUMhGOrySA",
}

# ---------- card rendering ----------
def gradient_bg():
    img = Image.new("RGB", (1920,1080))
    d = ImageDraw.Draw(img)
    for y in range(1080):
        t = y/1080
        c = (int(13+8*t), int(13+8*t), int(22+14*t))
        d.line([(0,y),(1920,y)], fill=c)
    d.rectangle([0,0,1920,14], fill=(200,40,40))
    return img, d

def draw_header(d, wigs):
    f_brand = ImageFont.truetype(FB, 40)
    brand = "A I   U N H I N G E D"
    d.text((60,45), brand, font=f_brand, fill=(255,80,80))
    f_w = ImageFont.truetype(FB, 36)
    wt = f"WIGS: {wigs}"
    bbox = d.textbbox((0,0), wt, font=f_w)
    ww = bbox[2]-bbox[0]
    d.rounded_rectangle([1920-60-ww-40, 40, 1920-60, 40+64], radius=12,
                        outline=(255,200,60), width=3)
    d.text((1920-60-ww-20, 48), wt, font=f_w, fill=(255,210,90))

def draw_score_banner(d, score, reason):
    y0 = 1080-250
    d.rectangle([0,y0,1920,1080], fill=(20,8,8))
    d.rectangle([0,y0,1920,y0+6], fill=(220,50,50))
    f_s = ImageFont.truetype(FB, 34)
    d.text((90,y0+28), "AI FAIL SCORE", font=f_s, fill=(255,120,120))
    f_big = ImageFont.truetype(FB, 110)
    d.text((90,y0+70), f"{score}/10", font=f_big, fill=(255,220,80))
    f_r = ImageFont.truetype(FBI, 40)
    d.text((480,y0+105), reason, font=f_r, fill=(235,235,235))

def render_card(path, text, wigs, score=None, reason=None, title_mode=False, block_label=None):
    img, d = gradient_bg()
    draw_header(d, wigs)
    if title_mode:
        f_t = ImageFont.truetype(FB, 120)
        lines = textwrap.wrap(text, width=22)
        y = 1080//2 - len(lines)*70
        for ln in lines:
            bb = d.textbbox((0,0), ln, font=f_t)
            d.text(((1920-(bb[2]-bb[0]))/2, y), ln, font=f_t, fill=(255,255,255))
            y += 140
    else:
        if block_label:
            f_b = ImageFont.truetype(FB, 34)
            d.text((90,150), block_label, font=f_b, fill=(150,150,170))
        f_m = ImageFont.truetype(FB, 56)
        lines = textwrap.wrap(text, width=42)
        # shrink if too many lines
        while len(lines) > 9:
            sz = f_m.size - 4
            f_m = ImageFont.truetype(FB, sz)
            lines = textwrap.wrap(text, width=42+ (56-sz))
        y = 1080//2 - len(lines)*38 - (60 if score else 0)
        for ln in lines:
            bb = d.textbbox((0,0), ln, font=f_m)
            d.text(((1920-(bb[2]-bb[0]))/2, y), ln, font=f_m, fill=(245,245,245))
            y += int(f_m.size*1.35)
    if score is not None:
        draw_score_banner(d, score, reason)
    img.save(path)

def concat_audio(seg_ids, out):
    """concat seg mp3s with 0.35s silence gaps -> out"""
    parts = []
    for i, sid in enumerate(seg_ids):
        parts += ["-i", f"{TTS}/seg_{sid:03d}.mp3"]
        if i < len(seg_ids)-1:
            parts += ["-f","lavfi","-t","0.35","-i","anullsrc=r=44100:cl=stereo"]
    n = len(seg_ids)
    if n == 1:
        run(["ffmpeg","-y","-v","error","-i",f"{TTS}/seg_{seg_ids[0]:03d}.mp3",
             "-af","atempo=0.95","-c:a","libmp3lame","-ar","44100",out])
        return probe_dur(out)
    filt = "".join(f"[{2*i}:a]" for i in range(n))  # audio inputs at even indices
    # inputs: 0:a, 1:sil, 2:a, 3:sil ... -> interleave
    ins = []
    for i in range(n):
        ins.append(f"[{2*i}:a]")
        if i < n-1: ins.append(f"[{2*i+1}:a]")
    filt = "".join(ins) + f"concat=n={2*n-1}:v=0:a=1[a];[a]atempo=0.95[aout]"
    cmd = ["ffmpeg","-y","-v","error"] + parts + ["-filter_complex",filt,
           "-map","[aout]","-c:a","libmp3lame","-ar","44100",out]
    run(cmd)
    return probe_dur(out)

def card_scene(name, seg_ids, wigs, score=None, reason=None, title_mode=False, block_label=None,
               tail=None, text_override=None):
    png = f"{BUILD}/{name}.png"
    mp4 = f"{BUILD}/{name}.mp4"
    if valid_mp4(mp4): return mp4, probe_dur(mp4)
    if tail is None:
        tail = 1.4 if score is not None else 0.8
    manifest = json.load(open(f"{W}/vo_manifest.json",encoding="utf-8"))
    txt = text_override if text_override is not None else " ".join(manifest[i]["text"] for i in seg_ids)
    render_card(png, txt, wigs, score, reason, title_mode, block_label)
    aud = f"{BUILD}/{name}.mp3"
    ad = concat_audio(seg_ids, aud)
    dur = ad + tail
    run(["ffmpeg","-y","-v","error","-loop","1","-framerate","30","-i",png,
         "-i",aud,"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p","-r","30",
         "-c:a","aac","-ar","44100","-t",f"{dur:.2f}","-shortest",mp4])
    return mp4, probe_dur(mp4)

def clip_scene(name, src_id, wigs, cap=16, start=0):
    src = f"{SRC}/{src_id}.mp4"
    mp4 = f"{BUILD}/{name}.mp4"
    if valid_mp4(mp4): return mp4, probe_dur(mp4)
    sd = probe_dur(src)
    dur = min(sd - start, cap)
    vf = ("scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
          "split[bg][fg];[bg]boxblur=18[bg];[fg]scale=-2:1080[fg];"
          "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    vf += (f",drawtext=fontfile={FB}:text='WIGS\\: {wigs}':fontsize=34:fontcolor=0xffd25a:"
           f"x=w-tw-50:y=50:box=1:boxcolor=0x000000aa:boxborderw=12")
    run(["ffmpeg","-y","-v","error","-ss",f"{start:.1f}","-t",f"{dur:.2f}","-i",src,
         "-vf",vf,"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p","-r","30",
         "-c:a","aac","-ar","44100",mp4])
    return mp4, probe_dur(mp4)

# ---------- timeline ----------
def sec_ranges():
    manifest = json.load(open(f"{W}/vo_manifest.json",encoding="utf-8"))
    rng = defaultdict(list)
    for i, s in enumerate(manifest):
        rng[s["section"]].append(i)
    return manifest, rng

def build():
    manifest, rng = sec_ranges()
    def ids(*names):
        out = []
        for n in names: out += rng[n]
        return out

    scenes = []  # (name, mp4path, dur, srt_entries[(start,end,text)])
    wigs = 0
    t = 0.0
    srt = []

    def add_card(name, seg_ids, score=None, reason=None, title_mode=False,
                 block_label=None, text_override=None):
        nonlocal t
        mp4, d = card_scene(name, seg_ids, wigs, score, reason, title_mode,
                            block_label, text_override=text_override)
        scenes.append(mp4)
        for sid in seg_ids:
            # approx timing: distribute evenly (refined by concat_audio order)
            pass
        t += d
        return d

    def add_card_srt(name, seg_ids, **kw):
        nonlocal t
        # compute per-seg durations for accurate subtitles
        durs = [probe_dur(f"{TTS}/seg_{sid:03d}.mp3") for sid in seg_ids]
        mp4, d = card_scene(name, seg_ids, wigs, **kw)
        scenes.append(mp4)
        cur = t
        for sid, dd in zip(seg_ids, durs):
            srt.append((cur, cur+dd, manifest[sid]["text"]))
            cur += dd + 0.35
        t += d

    def add_clip(name, src_id, cap=16, start=0, wig=None):
        nonlocal t
        mp4, d = clip_scene(name, src_id, wigs if wig is None else wig, cap, start)
        scenes.append(mp4)
        t += d

    # 1. cold open (20s, no VO)
    add_clip("s00_cold", CLIP_SRC["cold"], cap=20)

    # 2. hook (5)
    for j, sid in enumerate(ids("00:20–00:55 ｜主持人钩子（HOST HOOK）")):
        add_card_srt(f"s01_hook{j}", [sid], block_label="COLD OPEN → HOST")

    # 3. monologue (6) — draft pending user review
    for j, sid in enumerate(ids("monologue")):
        add_card_srt(f"s02_mono{j}", [sid], block_label="WEEKLY OBSERVATION - 60 SECONDS (DRAFT)")

    # 4. block1 title
    add_card_srt("s03_b1t", ids("00:55–01:05 ｜BLOCK 1 标题卡"),
                 title_mode=True, text_override="BLOCK 1: PHYSICS GAVE UP")

    # 5. clips 1-7
    for cn in range(1, 8):
        key = f"clip{cn}"
        sids = rng[key]
        pre, post = sids[:-2], sids[-2:]
        for j, sid in enumerate(pre):
            add_card_srt(f"s04_c{cn}pre{j}", [sid], block_label=f"CLIP {cn}")
        add_clip(f"s04_c{cn}", CLIP_SRC[key])
        sc, rs = SCORES[key]
        for j, sid in enumerate(post):
            add_card_srt(f"s04_c{cn}post{j}", [sid], score=sc if j==len(post)-1 else None,
                         reason=rs if j==len(post)-1 else None, block_label=f"CLIP {cn}")

    # 6. transition 1
    for j, sid in enumerate(ids("06:10–06:25 ｜BLOCK 过渡（元评论 — 必须有，这是\"实质变化\"的证据）")):
        add_card_srt(f"s05_tr{j}", [sid], block_label="TRANSITION")

    # 7. block2 title
    add_card_srt("s06_b2t", ids("06:25–06:35 ｜BLOCK 2 标题卡"),
                 title_mode=True, text_override="BLOCK 2: KAREN vs AI")

    # 8. clips 8-12
    for cn in range(8, 13):
        key = f"clip{cn}"
        sids = rng[key]
        pre, post = sids[:-2], sids[-2:]
        for j, sid in enumerate(pre):
            add_card_srt(f"s07_c{cn}pre{j}", [sid], block_label=f"CLIP {cn}")
        add_clip(f"s07_c{cn}", CLIP_SRC[key])
        if cn == 12:
            wigs = 1  # wig flies here
        sc, rs = SCORES[key]
        for j, sid in enumerate(post):
            add_card_srt(f"s07_c{cn}post{j}", [sid], score=sc if j==len(post)-1 else None,
                         reason=rs if j==len(post)-1 else None, block_label=f"CLIP {cn}",
                         )
    # 9. clip 13+14 double feature
    sids = rng["clip13_14"]
    pre, mid, post = sids[:3], sids[3:4], sids[4:]
    for j, sid in enumerate(pre):
        add_card_srt(f"s08_c13pre{j}", [sid], block_label="CLIP 19 ★")
    add_clip("s08_c13a", CLIP_SRC["clip13a"])
    for sid in mid:
        add_card_srt("s08_c13mid", [sid], block_label="CLIP 19 ★")
    add_clip("s08_c13b", CLIP_SRC["clip13b"])
    sc, rs = SCORES["clip13_14"]
    for j, sid in enumerate(post):
        add_card_srt(f"s08_c13post{j}", [sid], score=sc if j==len(post)-1 else None,
                     reason=rs if j==len(post)-1 else None, block_label="CLIP 19 ★")

    # 10. midroll
    for j, sid in enumerate(ids("11:15–11:35 ｜MID-ROLL 广告位")):
        add_card_srt(f"s09_mid{j}", [sid], block_label="MID-ROLL")

    # 11. block3 title
    add_card_srt("s10_b3t", ids("11:35–11:45 ｜BLOCK 3 标题卡"),
                 title_mode=True, text_override="BLOCK 3: AI TRIED TO MAKE A MOVIE")

    # 12. clips 15-20
    for cn in range(15, 21):
        key = f"clip{cn}"
        sids = rng[key]
        pre, post = sids[:-2], sids[-2:]
        for j, sid in enumerate(pre):
            add_card_srt(f"s11_c{cn}pre{j}", [sid], block_label=f"CLIP {cn}")
        add_clip(f"s11_c{cn}", CLIP_SRC[key])
        sc, rs = SCORES[key]
        for j, sid in enumerate(post):
            add_card_srt(f"s11_c{cn}post{j}", [sid], score=sc if j==len(post)-1 else None,
                         reason=rs if j==len(post)-1 else None, block_label=f"CLIP {cn}")

    # 13. transition 2
    for j, sid in enumerate(ids("16:40–16:55 ｜BLOCK 过渡")):
        add_card_srt(f"s12_tr{j}", [sid], block_label="RAPID FIRE →")

    # 14. rapid fire 21-28: clip then 1 post card
    for cn in range(21, 29):
        key = f"clip{cn}"
        add_clip(f"s13_c{cn}", CLIP_SRC[key], cap=14)
        sc, rs = SCORES[key]
        add_card_srt(f"s13_c{cn}post", rng[key], score=sc, reason=rs,
                     block_label=f"RAPID {cn}")

    # 15. finale buildup
    for j, sid in enumerate(ids("21:00–21:20 ｜压轴铺垫")):
        add_card_srt(f"s14_bu{j}", [sid], block_label="GRAND FINALE →")

    # 16. finale clip (full, no overlays per script)
    add_clip("s15_fin", CLIP_SRC["finale"], cap=30)

    # 17. finale commentary (7)
    for j, sid in enumerate(ids("21:20–23:20 ｜GRAND FINALE")):
        kw = {}
        if j == len(ids("21:20–23:20 ｜GRAND FINALE"))-1:
            sc, rs = SCORES["finale"]
            kw = {"score": sc, "reason": rs}
        add_card_srt(f"s16_fin{j}", [sid], block_label="WHY IT WORKED", **kw)

    # 18. outro (4) + end screen hold
    for j, sid in enumerate(ids("23:20–24:00 ｜OUTRO")):
        add_card_srt(f"s17_out{j}", [sid], block_label="OUTRO")
    # end screen 15s
    render_card(f"{BUILD}/s18_end.png", "AI UNHINGED — Full Episodes\n\nNext: EP2 Tuesday",
                wigs, title_mode=False, block_label="END SCREEN")
    run(["ffmpeg","-y","-v","error","-loop","1","-framerate","30","-i",f"{BUILD}/s18_end.png",
         "-f","lavfi","-t","15","-i","anullsrc=r=44100:cl=stereo",
         "-c:v","libx264","-pix_fmt","yuv420p","-r","30","-c:a","aac","-ar","44100",
         "-t","15",f"{BUILD}/s18_end.mp4"])
    scenes.append(f"{BUILD}/s18_end.mp4")
    t += 15

    print(f"scenes: {len(scenes)}, est total: {t/60:.1f} min")
    with open(f"{BUILD}/concat.txt","w") as f:
        for s in scenes: f.write(f"file '{s}'\n")
    atomic_write_json(f"{BUILD}/srt.json", srt)
    return scenes, t, srt

def write_srt(srt, path):
    def ts(x):
        h=int(x//3600); m=int(x%3600//60); s=int(x%60); ms=int(x%1*1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    with open(path,"w",encoding="utf-8") as f:
        for i,(a,b,txt) in enumerate(srt,1):
            f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{txt}\n\n")

if __name__ == "__main__":
    scenes, t, srt = build()
    write_srt(srt, f"{BUILD}/ep1.srt")
    print("timeline built; running concat…")
    run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",f"{BUILD}/concat.txt",
         "-c","copy",f"{BUILD}/raw.mp4"])
    print("raw done:", probe_dur(f"{BUILD}/raw.mp4"))
