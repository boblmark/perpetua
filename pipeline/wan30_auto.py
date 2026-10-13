#!/usr/bin/env python3
"""Wan 3.0 视频生成（GMI Cloud API 直调）
官方文档：https://docs.gmicloud.ai/inference-engine/api-reference/video-api-reference
活动：Qwen Day 免费周（Qwen3.8-Max/Flash + Wan3.0-video，7 天免费，需账号余额 ≥$10）

流程：list models → 取 wan3.0 model_id → POST requests → 轮询 → 下载 artifact
用法：
  python3 wan30_auto.py --prompt-file xxx.txt --job-id xxx --out-dir /home/hatch/data/veo_inbox/
  python3 wan30_auto.py --check   # 只验证 API key + 列出视频模型，不生成

API key 存放：/home/hatch/data/gmi/.api_key（600 权限），或环境变量 GMI_API_KEY
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = "https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey"
KEY_PATH = "/home/hatch/data/gmi/.api_key"


def get_key():
    key = os.environ.get("GMI_API_KEY", "").strip()
    if not key and os.path.exists(KEY_PATH):
        with open(KEY_PATH) as f:
            key = f.read().strip()
    if not key:
        sys.exit("ERROR: 未找到 GMI API key。请先在 console.gmicloud.ai → Settings → API Keys 创建，"
                 "写入 /home/hatch/data/gmi/.api_key（600）或 export GMI_API_KEY")
    return key


def api(method, path, data=None, timeout=60):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        method=method,
        headers={"Authorization": f"Bearer {get_key()}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        sys.exit(f"ERROR: GMI API {method} {path} → HTTP {e.code}: {body}")


def find_wan30_model():
    """从模型列表中找到 wan3.0 video 模型"""
    resp = api("GET", "/models")
    models = resp.get("models") or resp.get("data") or resp.get("items") or []
    cands = []
    for m in models:
        mid = str(m.get("model_id") or m.get("id") or m.get("name") or "")
        if "wan" in mid.lower() and "3" in mid:
            cands.append((mid, m))
    if not cands:
        ids = [str(m.get("model_id") or m.get("id")) for m in models[:20]]
        sys.exit(f"ERROR: 模型列表中未找到 wan3.0。可用模型：{ids}")
    # 优先选带 video 字样的
    for mid, m in cands:
        if "video" in mid.lower():
            return mid, m
    return cands[0]


def check():
    mid, m = find_wan30_model()
    print(f"API key 有效。Wan3.0 模型：{mid}")
    detail = api("GET", f"/models/{mid}")
    schema = detail.get("schema") or detail.get("parameters") or detail.get("input_schema")
    print("模型参数 schema：")
    print(json.dumps(schema, ensure_ascii=False, indent=1)[:2000])
    return mid


def generate(prompt, duration=8, aspect="9:16", resolution="720p",
             out_path=None, poll_timeout=1800, poll_interval=20, model_id=None):
    mid, _ = (model_id, None) if model_id else find_wan30_model()
    print(f"模型：{mid}，时长 {duration}s，比例 {aspect}，分辨率 {resolution}")
    payload = {
        "model_id": mid,
        "input": {
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect,
            "resolution": resolution,
        },
    }
    created = api("POST", "/requests", payload)
    rid = created.get("request_id") or created.get("id") or created.get("requestId")
    if not rid:
        sys.exit(f"ERROR: 创建任务失败，返回：{json.dumps(created)[:300]}")
    print(f"任务已提交：{rid}，开始轮询…")
    deadline = time.time() + poll_timeout
    while time.time() < deadline:
        st = api("GET", f"/requests/{rid}")
        status = str(st.get("status", "")).lower()
        if status in ("finished", "completed", "succeeded", "success"):
            arts = st.get("artifacts") or st.get("outputs") or {}
            url = None
            if isinstance(arts, dict):
                for v in arts.values():
                    if isinstance(v, str) and v.startswith("http"):
                        url = v
                        break
                    if isinstance(v, dict) and v.get("url"):
                        url = v["url"]
                        break
            elif isinstance(arts, list) and arts:
                url = arts[0] if isinstance(arts[0], str) else arts[0].get("url")
            if not url:
                sys.exit(f"ERROR: 任务完成但未找到下载链接：{json.dumps(st)[:500]}")
            print(f"完成，下载：{url[:80]}…")
            urllib.request.urlretrieve(url, out_path)
            print(f"已保存 → {out_path}")
            return out_path
        if status in ("failed", "error", "cancelled"):
            sys.exit(f"ERROR: 任务失败：{json.dumps(st)[:500]}")
        print(f"  …{status}（{int(deadline - time.time())}s 剩余）", flush=True)
        time.sleep(poll_interval)
    sys.exit(f"ERROR: 轮询超时（{poll_timeout}s），任务 {rid} 未完成")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file")
    ap.add_argument("--job-id", default="wan30_test")
    ap.add_argument("--out-dir", default="/home/hatch/data/veo_inbox/")
    ap.add_argument("--duration", type=int, default=8)
    ap.add_argument("--aspect-ratio", default="9:16")
    ap.add_argument("--resolution", default="720p")
    ap.add_argument("--model-id", default="")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        check()
        return
    if not a.prompt_file:
        sys.exit("ERROR: 需要 --prompt-file")
    with open(a.prompt_file, encoding="utf-8") as f:
        prompt = f.read().strip()
    os.makedirs(a.out_dir, exist_ok=True)
    out = os.path.join(a.out_dir, f"{a.job_id}_wan30.mp4")
    generate(prompt, duration=a.duration, aspect=a.aspect_ratio,
             resolution=a.resolution, out_path=out,
             model_id=a.model_id or None)


if __name__ == "__main__":
    main()
