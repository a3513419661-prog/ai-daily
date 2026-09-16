# -*- coding: utf-8 -*-
"""B 站接口探测：找出哪条路能稳定拿到数据（本地和云端都跑一遍对比）。"""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import time
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get(url: str, referer: str = "https://www.bilibili.com/") -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with opener.open(req, timeout=25) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"EXC {exc}"


def mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in MIXIN_TAB)[:32]


def wbi_sign(params: dict, img_key: str, sub_key: str) -> str:
    key = mixin_key(img_key + sub_key)
    params = dict(params)
    params["wts"] = int(time.time())
    params = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in sorted(params.items())}
    query = urllib.parse.urlencode(params)
    return query + "&w_rid=" + hashlib.md5((query + key).encode()).hexdigest()


def show(label: str, status: int, body: str, pick=None) -> None:
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        print(f"{label:<34} HTTP {status} 非JSON: {body[:70]}")
        return
    code = data.get("code")
    msg = str(data.get("message", ""))[:26]
    extra = ""
    if code == 0 and pick:
        try:
            extra = pick(data)
        except Exception:  # noqa: BLE001
            extra = "(解析失败)"
    print(f"{label:<34} HTTP {status} code={code} {msg} {extra}")


def titles_from_list(data) -> str:
    lst = (((data.get("data") or {}).get("list") or {}).get("vlist")
           or (data.get("data") or {}).get("list")
           or (data.get("data") or {}).get("archives")
           or [])
    names = [i.get("title") or i.get("title_display") or "" for i in lst][:3]
    return " | ".join(n[:26] for n in names)


def main() -> int:
    print("=== B 站接口探测 ===")
    status, body = get("https://www.bilibili.com/")
    print(f"预热拿 Cookie: HTTP {status}, cookie 数 {len(list(jar))} "
          f"({', '.join(c.name for c in jar)[:60]})")

    status, body = get("https://api.bilibili.com/x/web-interface/nav")
    img_key = sub_key = ""
    try:
        wbi = json.loads(body)["data"]["wbi_img"]
        img_key = wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
        sub_key = wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    except Exception:  # noqa: BLE001
        pass
    print(f"wbi 密钥: img={img_key[:12]}… sub={sub_key[:12]}… ({'成功' if img_key else '失败'})")

    # 1) 老接口取 UP 主投稿（影视飓风 946974）
    s, b = get("https://api.bilibili.com/x/space/arc/search?mid=946974&ps=5&pn=1&order=pubdate")
    show("1 老接口 用户投稿", s, b, titles_from_list)

    # 2) wbi 签名接口取 UP 主投稿
    q = wbi_sign({"mid": 946974, "ps": 5, "pn": 1, "order": "pubdate"}, img_key, sub_key)
    s, b = get(f"https://api.bilibili.com/x/space/wbi/arc/search?{q}")
    show("2 wbi 用户投稿", s, b, titles_from_list)

    # 3) 分区最新（183 = 影视剪辑）
    s, b = get("https://api.bilibili.com/x/web-interface/dynamic/region?rid=183&ps=5&pn=1")
    show("3 分区最新 影视剪辑", s, b, titles_from_list)

    # 4) 分区最新（36 知识区、188 科技区）
    for rid, name in ((36, "知识"), (188, "科技")):
        s, b = get(f"https://api.bilibili.com/x/web-interface/dynamic/region?rid={rid}&ps=5&pn=1")
        show(f"4 分区最新 {name}", s, b, titles_from_list)

    # 5) 全站排行
    s, b = get("https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all")
    show("5 全站排行", s, b, titles_from_list)

    # 6) 综合热门
    s, b = get("https://api.bilibili.com/x/web-interface/popular?ps=5&pn=1")
    show("6 综合热门", s, b, titles_from_list)

    # 7) 搜索（需要 Cookie）
    kw = urllib.parse.quote("剪辑教程")
    s, b = get(f"https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={kw}&page=1")
    show("7 搜索 剪辑教程", s, b, lambda d: " | ".join(
        (i.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")[:26]
        for i in (d["data"].get("result") or [])[:3]))

    # 8) wbi 搜索
    q = wbi_sign({"search_type": "video", "keyword": "剪辑教程", "page": 1}, img_key, sub_key)
    s, b = get(f"https://api.bilibili.com/x/web-interface/wbi/search/type?{q}")
    show("8 wbi 搜索 剪辑教程", s, b, lambda d: " | ".join(
        (i.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")[:26]
        for i in (d["data"].get("result") or [])[:3]))

    # 9) 动态（UP 主动态）
    q = wbi_sign({"host_mid": 946974}, img_key, sub_key)
    s, b = get(f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?{q}")
    show("9 wbi UP 主动态", s, b, lambda d: f"items={len(d['data'].get('items') or [])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
