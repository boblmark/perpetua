#!/usr/bin/env python3
"""Upload EP1 English captions to x-os38-ph_Y via YouTube captions API (resumable upload).
Reuses /home/hatch/data/youtube/yt_upload.py auth + relay pattern. No new deps.
Reversible: the inserted track can be removed with captions.delete.
注（2026-10-16 实测）：multipart/related 一步上传在此账号恒报 400 invalid metadata，
改用 resumable 两步（init→PUT）一次成功。
"""
import json, os, sys, urllib.request, urllib.error

sys.path.insert(0, "/home/hatch/data/youtube")
sys.path.insert(0, "/home/hatch/data")
from yt_upload import _load, _refresh
from relay import urlopen as _urlopen

VIDEO_ID = "x-os38-ph_Y"
SRT = "/home/hatch/data/perpetua/ep1_qc/ep1_subtitles.srt"  # 2026-10-14 QC 版（349 条），替代 10-10 build 旧版

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
    # resumable 两步上传：先 init 拿 session URI，再 PUT 文件体
    try:
        init_req = urllib.request.Request(
            "https://www.googleapis.com/upload/youtube/v3/captions?part=snippet&uploadType=resumable",
            data=meta, method="POST",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json; charset=UTF-8",
                     "X-Upload-Content-Type": "text/plain",
                     "X-Upload-Content-Length": str(len(srt_bytes))})
        with _urlopen(init_req, timeout=60) as ir:
            session_uri = ir.headers.get("Location")
        if not session_uri:
            raise RuntimeError("resumable init 未返回 Location")
        put_req = urllib.request.Request(
            session_uri, data=srt_bytes, method="PUT",
            headers={"Content-Type": "text/plain",
                     "Content-Length": str(len(srt_bytes))})
        with _urlopen(put_req, timeout=120) as pr:
            res = json.load(pr)
    except (urllib.error.HTTPError, RuntimeError) as e:
        err = e.read().decode(errors="replace")[:800] if isinstance(e, urllib.error.HTTPError) else str(e)[:800]
        print(json.dumps({"ok": False, "stage": "insert", "error": err,
                          "tracks_before": existing}))
        return
    verify = api(tok, f"https://www.googleapis.com/youtube/v3/captions?part=snippet&videoId={VIDEO_ID}")["items"]
    print(json.dumps({"ok": True, "stage": "inserted", "id": res.get("id"),
                      "status": res.get("snippet", {}).get("status"),
                      "tracks_after": [{"id": t["id"], "lang": t["snippet"].get("language"),
                                        "status": t["snippet"].get("status")} for t in verify]}))

if __name__ == "__main__":
    main()
