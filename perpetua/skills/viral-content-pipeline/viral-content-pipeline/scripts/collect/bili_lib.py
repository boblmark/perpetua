"""Bilibili public-data collector helpers.

Data sources (all public, no login):
  - /x/web-interface/wbi/search/type   -> keyword search (discover accounts/videos)
  - /x/web-interface/card              -> account followers / avatar / sign
  - /x/series/recArchivesByKeywords    -> a mid's recent video list (bvid, pubdate, duration, play)
  - /x/web-interface/view              -> authoritative per-video stat block
  - /x/frontend/finger/spi             -> anonymous device cookies (reduces risk-control trips)
No backend/private metric is retrieved; every number written out comes from these responses.
"""
import hashlib
import json
import random
import time
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
             33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
             26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
             20, 34, 44, 52]


class Bili:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Referer": "https://www.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self.mixin_key = None
        self._bootstrap()

    # ---------- infra ----------
    def _bootstrap(self):
        try:
            j = self.s.get("https://api.bilibili.com/x/frontend/finger/spi", timeout=15).json()
            d = j.get("data") or {}
            for k, v in (("b_3", d.get("b_3")), ("b_4", d.get("b_4"))):
                if v:
                    self.s.cookies.set("buvid" + k[-1], v, domain=".bilibili.com")
        except Exception:
            pass
        for _ in range(3):
            try:
                nav = self.s.get("https://api.bilibili.com/x/web-interface/nav", timeout=15).json()
                wi = nav["data"]["wbi_img"]
                raw = wi["img_url"].split("/")[-1].split(".")[0] + wi["sub_url"].split("/")[-1].split(".")[0]
                self.mixin_key = "".join(raw[i] for i in MIXIN_TAB)[:32]
                return
            except Exception:
                time.sleep(2)
        raise RuntimeError("could not obtain wbi mixin key")

    def _wbi(self, params):
        p = dict(params)
        p["wts"] = int(time.time())
        q = urllib.parse.urlencode(sorted(p.items()))
        p["w_rid"] = hashlib.md5((q + self.mixin_key).encode()).hexdigest()
        return p

    def _get(self, url, params=None, wbi=False, retries=4, referer=None):
        hdrs = {"Referer": referer} if referer else {}
        for attempt in range(retries):
            try:
                pp = self._wbi(params) if wbi else params
                r = self.s.get(url, params=pp, headers=hdrs, timeout=20)
                if r.status_code == 412:
                    time.sleep(3 + attempt * 4)
                    continue
                j = r.json()
                code = j.get("code")
                if code == 0:
                    return j.get("data")
                if code in (-352, -412):          # risk control
                    time.sleep(4 + attempt * 5)
                    continue
                if code == -799:                  # too frequent
                    time.sleep(6 + attempt * 6)
                    continue
                return {"__error__": code, "__message__": j.get("message")}
            except Exception:
                time.sleep(2 + attempt * 2)
        return None

    @staticmethod
    def _nap(lo=0.45, hi=1.05):
        time.sleep(random.uniform(lo, hi))

    # ---------- endpoints ----------
    def search_videos(self, keyword, page=1, order=""):
        d = self._get("https://api.bilibili.com/x/web-interface/wbi/search/type",
                      {"search_type": "video", "keyword": keyword, "page": page,
                       **({"order": order} if order else {})}, wbi=True)
        self._nap()
        if not d or "__error__" in d:
            return []
        return d.get("result") or []

    def card(self, mid):
        d = self._get("https://api.bilibili.com/x/web-interface/card", {"mid": mid, "photo": "true"})
        self._nap()
        if not d or "__error__" in d:
            return None
        c = d.get("card") or {}
        return {"mid": mid, "name": c.get("name"), "fans": c.get("fans"),
                "sign": (c.get("sign") or "").replace("\n", " ")[:80],
                "official": ((c.get("Official") or {}).get("title") or "")}

    def recent_archives(self, mid, keywords="", pn=1):
        d = self._get("https://api.bilibili.com/x/series/recArchivesByKeywords",
                      {"mid": mid, "keywords": keywords, "pn": pn})
        self._nap()
        if not d or "__error__" in d:
            return []
        return d.get("archives") or []

    def video_stat(self, bvid):
        # NOTE: the unsigned /x/web-interface/view endpoint is IP-banned (-412) for this
        # egress IP; the wbi-signed variant /x/web-interface/wbi/view returns full data.
        d = self._get("https://api.bilibili.com/x/web-interface/wbi/view", {"bvid": bvid}, wbi=True)
        self._nap()
        if not d or "__error__" in d:
            return None
        st = d.get("stat") or {}
        return {
            "bvid": bvid, "aid": d.get("aid"),
            "title": (d.get("title") or "").strip(),
            "desc": (d.get("desc") or "").replace("\n", " ").strip(),
            "pubdate": d.get("pubdate"), "ctime": d.get("ctime"),
            "duration": d.get("duration"),
            "tname": d.get("tname"),
            "pic": d.get("pic"),
            "owner_name": (d.get("owner") or {}).get("name"),
            "owner_mid": (d.get("owner") or {}).get("mid"),
            "view": st.get("view"), "like": st.get("like"), "coin": st.get("coin"),
            "favorite": st.get("favorite"), "reply": st.get("reply"),
            "danmaku": st.get("danmaku"), "share": st.get("share"),
            "dynamic": d.get("dynamic"),
        }
