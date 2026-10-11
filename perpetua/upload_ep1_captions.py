#!/usr/bin/env python3
"""Upload EP1 English captions to x-os38-ph_Y via YouTube captions API (multipart/related).
Reuses /home/hatch/data/youtube/yt_upload.py auth + relay pattern. No new deps.
Reversible: the inserted track can be removed with captions.delete.
"""
import json, os, sys, urllib.request, urllib.error

sys.path.insert(0, "/home/hatch/data/youtube")
sys.path.insert(0, "/home/hatch/data")
from yt_upload import _load, _refresh
from relay import urlopen as _urlopen

VIDEO_ID = "x-os38-ph_Y"
SRT = "/home/hatch/data/perpetua/ai_unhinged/ep1/build/ep1.srt"

def api(token, url, method="GET", data=None, headers=None):
    h = {"Authorization": f"Bearer {token}"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with _urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:600]
        raise RuntimeError(f"HTTP {e.code}: {body}")

def main():
    if not os.path.exists(SRT):
        print(json.dumps({"ok": False, "stage": "srt_missing"}))
        return
    d = _load()
    tok = d["token"]
    try:
        tracks = api(tok, f"https://www.googleapis.com/youtube/v3/captions?part=snippet&videoId={VIDEO_ID}")["items"]
    except RuntimeError as e:
        if "401" in str(e) or "expired" in str(e).lower():
            tok = _refresh(_load())
            tracks = api(tok, f"https://www.googleapis.com/youtube/v3/captions?part=snippet&videoId={VIDEO_ID}")["items"]
        else:
            print(json.dumps({"ok": False, "stage": "list", "error": str(e)[:400]}))
            return
    existing = [{"id": t["id"], "lang": t["snippet"].get("language"),
                 "kind": t["snippet"].get("trackKind"),
                 "status": t["snippet"].get("status")} for t in tracks]
    # ASR 自动字幕不算"已上传"：只有人工/上传的 en 轨道才跳过
    if any(t["lang"] == "en" and t["kind"] != "asr" and t["status"] != "failed"
           for t in existing):
        print(json.dumps({"ok": True, "stage": "already_present", "tracks": existing}))
        return

    meta = json.dumps({"snippet": {"videoId": VIDEO_ID, "language": "en",
                                   "name": "English", "isDraft": False}}).encode()
    srt_bytes = open(SRT, "rb").read()
    boundary = "CAPSEP_9f3a2b1c"
    body = (b"--" + boundary.encode() + b"\r\n"
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n" + meta + b"\r\n"
            b"--" + boundary.encode() + b"\r\n"
            b"Content-Type: application/x-subrip\r\n\r\n" + srt_bytes + b"\r\n"
            b"--" + boundary.encode() + b"--\r\n")
    try:
        res = api(tok, "https://www.googleapis.com/upload/youtube/v3/captions?part=snippet",
                  method="POST", data=body,
                  headers={"Content-Type": f"multipart/related; boundary={boundary}"})
    except RuntimeError as e:
        print(json.dumps({"ok": False, "stage": "insert", "error": str(e)[:800],
                          "tracks_before": existing}))
        return
    verify = api(tok, f"https://www.googleapis.com/youtube/v3/captions?part=snippet&videoId={VIDEO_ID}")["items"]
    print(json.dumps({"ok": True, "stage": "inserted", "id": res.get("id"),
                      "status": res.get("snippet", {}).get("status"),
                      "tracks_after": [{"id": t["id"], "lang": t["snippet"].get("language"),
                                        "status": t["snippet"].get("status")} for t in verify]}))

if __name__ == "__main__":
    main()
