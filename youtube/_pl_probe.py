"""列出频道所有 playlist，拿 ID。"""
import json, sys, urllib.request, urllib.parse
sys.path.insert(0, "/home/hatch/data")
from relay import urlopen
from yt_upload import _load, _refresh

d = _load()
tok = d["token"]

URL = "https://www.googleapis.com/youtube/v3/playlists?part=snippet,contentDetails&mine=true&maxResults=50"
def call(t):
    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {t}"})
    return json.load(urlopen(req, timeout=60))

try:
    r = call(tok)
except Exception as e:
    print("retry after refresh:", e)
    tok = _refresh(d)
    r = call(tok)

print("total:", r.get("pageInfo", {}).get("totalResults"))
for it in r.get("items", []):
    print(f"{it['id']} | {it['snippet']['title']} | items={it['contentDetails']['itemCount']}")
