# -*- coding: utf-8 -*-
"""
AI 日报 · 每日热点采集器

抓取 AI 资讯 / AI 短剧·视频 / 教程 / 开源项目 / Codex Skill，
去重后写入 data/，并生成可直接双击打开的 index.html。

只用 Python 标准库，不需要 pip 安装任何东西。

常用命令:
    py collect.py            抓取 + 生成页面
    py collect.py --render   不联网，只用已有数据重新生成页面
    py collect.py --open     抓取完成后自动打开页面
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import html
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
CONFIG_PATH = os.path.join(ROOT, "config.json")
TEMPLATE_PATH = os.path.join(ROOT, "template.html")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
LATEST_PATH = os.path.join(DATA_DIR, "latest.json")
DIGEST_PATH = os.path.join(DATA_DIR, "digest.json")
ZH_PATH = os.path.join(DATA_DIR, "zh.json")
TUNNEL_URL_PATH = os.path.join(DATA_DIR, "tunnel-url.txt")
SKILLS_SNAPSHOT_PATH = os.path.join(DATA_DIR, "skills.json")
LOG_PATH = os.path.join(DATA_DIR, "last-run.log")
SERVE_PORT = 8765

CN_TZ = timezone(timedelta(hours=8))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

CATEGORY_META = [
    ("aicraft", "AI 创作技巧"),
    ("editing", "剪辑 · 后期"),
    ("directing", "导演 · 影视化"),
    ("storyboard", "分镜 · 视觉"),
    ("learning", "教程 · 学习"),
    ("tools", "开源 · 工具"),
    ("drama", "AI 短剧动态"),
    ("trend", "风向 · 洞察"),
]

log_lines: list[str] = []


def log(msg: str) -> None:
    stamp = datetime.now(CN_TZ).strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    log_lines.append(line)
    try:
        print(line, flush=True)
    except Exception:
        pass


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_str() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def http_get(url: str, timeout: int = 20, tries: int = 2) -> bytes | None:
    last_err = None
    for attempt in range(tries):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                enc = (resp.headers.get("Content-Encoding") or "").lower()
                if "gzip" in enc:
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                elif "deflate" in enc:
                    try:
                        raw = zlib.decompress(raw)
                    except zlib.error:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                return raw
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(0.8 + attempt)
    log(f"  ! 抓取失败 {url} :: {last_err}")
    return None


def get_json(url: str, timeout: int = 20, tries: int = 2):
    raw = http_get(url, timeout=timeout, tries=tries)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\r\f\v]+")
TITLE_PREFIX_RE = re.compile(r"^\s*(?:[\u4e00-\u9fff]{2,6}频道|GitHub\s*项目)\s*[-—–|·:：]\s*")


def clean_title(title: str) -> str:
    """去掉站点在标题前面加的栏目名，比如「文章频道 - 」。"""
    cleaned = TITLE_PREFIX_RE.sub("", title or "").strip()
    return cleaned or (title or "").strip()


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
        if dt:
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        pass
    cleaned = value.replace("Z", "+00:00")
    cleaned = re.sub(r"\.(\d{3})\d*", r".\1", cleaned)
    for candidate in (cleaned, cleaned.replace(" ", "T")):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=CN_TZ).astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(value[: len(fmt) + 2].strip(), fmt).replace(tzinfo=CN_TZ).astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            continue
    return None


def iso(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def item_id(title: str, url: str) -> str:
    base = (url or title or "").strip().lower()
    base = re.sub(r"^https?://", "", base)
    base = re.sub(r"[?#].*$", "", base)
    base = base.rstrip("/")
    return hashlib.sha1(base.encode("utf-8", "replace")).hexdigest()[:16]


def norm_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"[\s\u3000]+", "", t)
    t = re.sub(r"[，。！？、：；,.!?:;\"'“”‘’（）()\[\]【】\-—_|/\\]", "", t)
    return t[:26]


# --------------------------------------------------------------------------
# RSS / Atom 解析
# --------------------------------------------------------------------------

def local_tag(el) -> str:
    return el.tag.split("}")[-1].lower()


def child_text(el, names: list[str]) -> str:
    for node in el.iter():
        if local_tag(node) in names and node.text:
            return node.text
    return ""


def entry_link(entry) -> str:
    for node in entry.iter():
        if local_tag(node) == "link":
            href = node.get("href")
            if href:
                return href.strip()
            if node.text and node.text.strip().startswith("http"):
                return node.text.strip()
    return child_text(entry, ["guid", "id"]).strip()


def parse_feed(raw: bytes, source: dict) -> list[dict]:
    head = raw[:400].decode("utf-8", "replace").lstrip().lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        log(f"  ! {source['name']} 返回的是网页而不是订阅源（可能被反爬拦截），已跳过")
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        try:
            root = ET.fromstring(raw.decode("utf-8", "replace").encode("utf-8"))
        except Exception:  # noqa: BLE001
            return []

    nodes = [n for n in root.iter() if local_tag(n) in ("item", "entry")]
    items: list[dict] = []
    for node in nodes:
        title = clean_title(strip_html(child_text(node, ["title"])))
        link = entry_link(node)
        if not title or not link:
            continue
        summary = child_text(node, ["description", "summary", "content", "encoded"])
        summary = clip(strip_html(summary), 240)
        publisher = ""
        publisher_url = ""
        for child in node.iter():
            if local_tag(child) == "source":
                publisher = (child.text or "").strip()
                publisher_url = (child.get("url") or "").strip()
                break
        published = parse_dt(
            child_text(node, ["pubdate", "published", "updated", "date", "dc:date"])
        )
        items.append(
            {
                "title": title,
                "url": link,
                "summary": summary,
                "published": iso(published),
                "source": source["name"],
                "source_id": source["id"],
                "lang": source.get("lang", "zh"),
                "weight": float(source.get("weight", 1.0)),
                "kind": "article",
                "publisher": publisher,
                "publisher_url": publisher_url,
            }
        )
    return items


# --------------------------------------------------------------------------
# 分类 / 标签 / 打分
# --------------------------------------------------------------------------

class Classifier:
    def __init__(self, keywords: dict):
        self.raw = {k: [w.lower() for w in v] for k, v in keywords.items()}

    def hits(self, text: str, group: str) -> list[str]:
        text_l = text.lower()
        found = []
        for word in self.raw.get(group, []):
            if re.search(r"[\u4e00-\u9fff]", word):
                if word in text_l:
                    found.append(word)
            elif re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text_l):
                found.append(word)
        return found

    def is_ai(self, text: str) -> bool:
        return bool(self.hits(text, "ai"))

    def classify(self, title: str, summary: str, kind: str = "article") -> tuple[str, list[str]]:
        text = f"{title} {summary}"
        tags: list[str] = []
        scores: dict[str, int] = {}
        for group in ("drama", "editing", "directing", "storyboard", "aicraft", "learning", "opensource", "trend"):
            found = self.hits(text, group)
            if found:
                scores[group] = len(found)
                tags.extend(found[:4])
        if kind == "repo":
            scores["opensource"] = scores.get("opensource", 0) + 3

        title_l = title.lower()
        title_drama = any(pattern.search(title) for pattern in DRAMA_TITLE_PATTERNS)
        title_editing = bool(self.hits(title, "editing"))
        title_directing = bool(self.hits(title, "directing"))
        title_storyboard = bool(self.hits(title, "storyboard"))
        title_aicraft = bool(self.hits(title, "aicraft"))
        title_ai = bool(self.hits(title, "ai"))
        title_learning = any(word in title_l for word in TUTORIAL_TITLE_WORDS) or any(
            pattern.search(title) for pattern in TUTORIAL_TITLE_PATTERNS
        )

        if title_storyboard:
            category = "storyboard"
        elif title_drama or scores.get("drama", 0) >= 2:
            category = "drama"
        elif title_editing:
            category = "editing"
        elif title_directing:
            category = "directing"
        elif title_aicraft and (title_ai or scores.get("aicraft", 0) >= 2):
            category = "aicraft"
        elif kind == "repo":
            category = "tools"
        elif title_learning:
            category = "learning"
        elif scores.get("aicraft", 0) >= 3:
            category = "aicraft"
        elif scores.get("learning", 0) >= 2:
            category = "learning"
        elif scores.get("storyboard", 0) >= 2:
            category = "storyboard"
        elif scores.get("editing", 0) >= 2:
            category = "editing"
        elif scores.get("directing", 0) >= 2:
            category = "directing"
        elif scores.get("opensource", 0) >= 1:
            category = "tools"
        else:
            category = "trend"

        deduped: list[str] = []
        for tag in tags:
            if tag not in deduped:
                deduped.append(tag)
        return category, deduped[:6]


DRAMA_TITLE_PATTERNS = [
    re.compile(r"短剧"),
    re.compile(r"漫剧"),
    re.compile(r"AI\s*视频|AI\s*动画|AI\s*影视", re.I),
    re.compile(r"(文生|图生|音生)视频"),
    re.compile(r"\bSora\b|\bVeo\b|\bRunway\b|\bPika\b|\bLuma\b", re.I),
    re.compile(r"可灵|即梦|海螺|Vidu|Seedance"),
    re.compile(r"数字人|对口型|口型|换脸"),
    re.compile(r"text[- ]to[- ]video|image[- ]to[- ]video", re.I),
]

TUTORIAL_TITLE_WORDS = [
    "教程", "指南", "实操", "保姆级", "手把手", "入门", "避坑", "复盘", "拆解",
    "方法论", "工作流", "全流程", "从零", "怎么用", "如何",
    "tutorial", "guide", "how to", "walkthrough", "cookbook", "getting started",
    "cheat sheet", "best practices",
]

TUTORIAL_TITLE_PATTERNS = [
    re.compile(r"教程|指南|实操|避坑|复盘|拆解|方法论|工作流|全流程|从零"),
    re.compile(r"\b(tutorial|guide|walkthrough|cookbook|handbook)\b", re.I),
    re.compile(r"\bhow to\b", re.I),
]


def score_item(item: dict, classifier: Classifier) -> float:
    text = f"{item.get('title','')} {item.get('summary','')}"
    score = float(item.get("weight", 1.0)) * 10.0
    score += 1.4 * len(item.get("tags", []))
    hot = classifier.hits(text, "ai")
    score += min(len(hot), 6) * 0.7

    published = parse_dt(item.get("published", ""))
    if published:
        hours = max((now_utc() - published).total_seconds() / 3600.0, 0.0)
        score += max(0.0, 26.0 - hours * 0.9)
    else:
        score += 8.0

    if item.get("kind") == "repo":
        stars = item.get("stars") or 0
        score += min(stars / 1500.0, 8.0)
        score += 3.0
    elif item.get("kind") == "skill":
        score += 5.0

    if item.get("category") == "drama":
        score += 3.0
    return round(score, 2)


# --------------------------------------------------------------------------
# 来源抓取
# --------------------------------------------------------------------------

def fetch_feeds(config: dict, classifier: Classifier) -> list[dict]:
    feeds = config.get("feeds", [])
    timeout = int(config.get("options", {}).get("timeout_seconds", 20))
    results: list[dict] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(http_get, f["url"], timeout): f for f in feeds}
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                raw = future.result()
            except Exception as exc:  # noqa: BLE001
                log(f"  ! {source['name']} 异常: {exc}")
                continue
            if not raw:
                continue
            parsed = parse_feed(raw, source)
            if not parsed:
                continue
            recent_days = int(source.get("recent_days", 0) or 0)
            if recent_days:
                cutoff = now_utc() - timedelta(days=recent_days)
                parsed = [
                    i for i in parsed
                    if not i["published"] or (parse_dt(i["published"]) or now_utc()) >= cutoff
                ]
            parsed.sort(key=lambda i: parse_dt(i.get("published", "")) or now_utc(), reverse=True)
            max_items = int(source.get("max_items", 25))
            parsed = parsed[: max_items * 3]
            kept = []
            craft_source = bool(source.get("default_category"))
            for item in parsed:
                text = f"{item['title']} {item['summary']}"
                if source.get("ai_title_only"):
                    # 技术/方法论类源：标题里得真的带 AI / 生成式话题
                    title_hits = (
                        classifier.hits(item["title"], "ai")
                        + classifier.hits(item["title"], "drama")
                        + classifier.hits(item["title"], "aicraft")
                    )
                    if not title_hits:
                        continue
                if craft_source:
                    if source.get("craft_only"):
                        # 手艺类源：只留剪辑/导演/分镜相关的干货，丢掉器材评测和其他语种随笔
                        if GEAR_NOISE.search(item["title"]) or not CRAFT_GATE.search(text):
                            continue
                        if not is_preferred_language(item["title"]):
                            continue
                        if PROMO_NOISE.search(item["title"]):
                            continue
                    item["default_category"] = source.get("default_category")
                    item["craft_source"] = bool(source.get("craft_only"))
                    kept.append(item)
                    continue
                title_hits = classifier.hits(item["title"], "ai") + classifier.hits(item["title"], "drama")
                # 泛科技源只放行标题就带 AI 信号的内容，避免手机数码新闻刷屏
                if source.get("ai_only") or title_hits or len(classifier.hits(text, "ai")) >= 4:
                    item["default_category"] = source.get("default_category")
                    kept.append(item)
            kept = kept[:max_items]
            results.extend(kept)
            log(f"  · {source['name']}: 抓到 {len(parsed)} 条，保留 {len(kept)} 条")
    return results


GOOGLE_NEWS_JUNK = re.compile(
    r"吉祥访|官网|下载安装|免费观看|完整版|在线观看|全集|哪里看|高清资源|手机版下载|apk"
    r"|正规吗|资质|报名|招生|加盟|贷款|骗局|办证",
    re.I,
)

# Google 新闻检索结果的标题闸门：标题里必须真的带手艺词，避免“只是在讲这个行业”的新闻
GOOGLE_NEWS_GATE = re.compile(
    r"剪辑|剪片|剪出|后期|调色|混音|音效|字幕|蒙太奇|转场|卡点|拉片|"
    r"分镜|分镜头|故事板|运镜|镜头语言|镜头设计|景别|构图|布光|光影|场面调度|视听语言|"
    r"导演|表演指导|影视化|电影感|影像风格|概念设计|美术设定|美术设计|角色设计|视觉开发|"
    r"\b(edit|editing|editor|colorist|grading|post[- ]production|montage|storyboard|animatic|"
    r"shot list|cinematograph\w*|directing|director|screenwriting|filmmaking|shot composition|"
    r"camera movement|lighting|framing)\b",
    re.I,
)

# 只收这些站点的检索结果，挡掉 SEO 站和内容农场
NEWS_DOMAIN_WHITELIST = (
    "thepaper.cn", "sina.com.cn", "sina.cn", "163.com", "qq.com", "sohu.com", "ifeng.com",
    "1905.com", "mtime.com", "people.com.cn", "xinhuanet.com", "chinanews.com", "cnr.cn",
    "jiemian.com", "yicai.com", "caixin.com", "gmw.cn", "cctv.com", "chinadaily.com.cn",
    "china.com.cn", "huanqiu.com", "infzm.com", "stcn.com", "21jingji.com", "nbd.com.cn",
    "eeo.com.cn", "cls.cn", "21cbh.com", "ithome.com", "36kr.com", "tmtpost.com",
    "leiphone.com", "qbitai.com", "jiqizhixin.com", "huxiu.com", "sspai.com", "ifanr.com",
    "geekpark.net", "pingwest.com", "cnbeta.com.tw", "zhidx.com", "iyiou.com",
    "nofilmschool.com", "studiobinder.com", "premiumbeat.com", "provideocoalition.com",
    "filmdaft.com", "vashivisuals.com", "ymcinema.com", "indiewire.com", "variety.com",
    "hollywoodreporter.com", "deadline.com", "filmmakermagazine.com", "filmcourage.com",
    "beforesandafters.com", "cined.com", "framestore.com", "petapixel.com", "theverge.com",
    "slashfilm.com", "firstshowing.net", "collider.com", "motionarray.com", "shutterstock.com",
    "nofilmschool.com", "creativebloq.com", "digitalcameraworld.com",
)

# 所有来源通用：明显是垃圾/盗版/推广的标题直接丢掉
TITLE_JUNK = re.compile(
    r"\bapk\b|mod apk|cracked\b|crack\b|torrent|free download|full version|premium unlocked|"
    r"注册即送|免费领取|加微信|私聊|代做|兼职日结|彩票|赌博",
    re.I,
)

# 服务商/工作室的自我推广稿，技巧类栏目里不要
PROMO_NOISE = re.compile(
    r"\b(our|we)\b[^.]{0,25}\b(services?|agency|team|studio|clients?)\b|"
    r"\b(hire|booking|book us|contact us|get a quote)\b|"
    r"professional (photo|video|editing|grading|production) (services?|company|studio)|"
    r"best (video|photo|editing) (editor|company|service)|"
    r"for your business|grow your business|call today|"
    r"services? for (films?|brands?|business|creators?|ott)|media house|go-to media|"
    r"\breviews?\b|\branked\b",
    re.I,
)

# 风向栏目：标题里必须有分析/观点/趋势类信号，纯新闻不要
TREND_GATE = re.compile(
    r"趋势|预测|展望|拐点|格局|泡沫|战略|路线|观点|分析|深度|解读|观察|思考|复盘|教训|经验|"
    r"启示|报告|调研|白皮书|为什么|赛道|竞争|商业化|就业|岗位|判断|意味着|走向|方向|机会|挑战|"
    r"\btrends?\b|\boutlook\b|\bforecasts?\b|\banalysis\b|\bopinion\b|\bessay\b|\bstrategy\b|"
    r"\breport\b|\bfuture\b|\bshift\b|\blessons?\b|\bwhy\b|\bwhat it means\b|\bstate of\b",
    re.I,
)


NEWS_DOMAIN_BLOCKLIST = (
    "perfectcorp.com", "pw.live", "youtu.be", "tiktok.com", "amraandelma.com", "awisee.com",
    "msn.com", "sportskeeda.com", "quora.com", "pinterest.com", "facebook.com", "instagram.com",
    "chinaz.com", "mtz.china.com", "eastmoney.com", "xueqiu.com", "ttplus.cn",
)


def domain_allowed(url: str, strict: bool = True) -> bool:
    """strict=True 只放白名单（中文检索用），strict=False 只挡黑名单（英文检索用）。"""
    if not url:
        return False
    host = urllib.parse.urlparse(url).netloc.lower()
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if any(host == b or host.endswith("." + b) for b in NEWS_DOMAIN_BLOCKLIST):
        return False
    if not strict:
        return True
    return any(host == d or host.endswith("." + d) for d in NEWS_DOMAIN_WHITELIST)


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
EN_STOPWORD_RE = re.compile(
    r"\b(the|a|an|of|to|in|on|for|and|or|with|how|why|what|your|you|is|are|my|from|that|this)\b",
    re.I,
)


def is_junk_title(title: str) -> bool:
    """明显是盗版/推广/内容农场的标题。"""
    return bool(TITLE_JUNK.search(title or ""))


def is_preferred_language(text: str) -> bool:
    """只保留中文或英文内容，挡掉 Medium 里的其他语种随笔。"""
    text = text or ""
    if CJK_RE.search(text):
        return True
    return bool(EN_STOPWORD_RE.search(text))

# 剪辑 / 导演 / 分镜类专业源的内容闸门：只留手艺相关内容，过滤器材发布会
CRAFT_GATE = re.compile(
    r"剪辑|后期|调色|混音|音效|字幕|分镜|故事板|运镜|镜头语言|导演|表演|布光|光影|构图|"
    r"摄影|影视|影片|胶片|镜头设计|视觉开发|美术设计|"
    r"\b(edit|editing|editor|editorial|cut|cutting|timeline|footage|post[- ]production|grading|"
    r"color|sound|audio|mixing|vfx|compositing|storyboard|animatic|previz|previsualization|"
    r"concept art|shot list|cinematograph\w*|director|directing|filmmaking|scene|narrative|"
    r"lighting|screenwriting|framing)\b",
    re.I,
)
GEAR_NOISE = re.compile(
    r"(review|reviews|hands[- ]on|announce\w*|introduc\w*|launch\w*|first look)[^.]{0,80}"
    r"\b(lens(es)?|camera(s)?|batter(y|ies)|monitor(s)?|gimbal(s)?|filter(s)?|tripod(s)?|"
    r"ssds?|microphones?|mics?|adapters?|mounts?|backpacks?|bags?|lights?|drives?|rigs?)\b",
    re.I,
)


def fetch_google_news(config: dict, classifier: Classifier) -> list[dict]:
    """Google 新闻关键词检索：补足剪辑 / 导演 / 分镜这类垂类内容。"""
    items: list[dict] = []
    for entry in config.get("google_news", []):
        query = entry.get("q", "")
        if not query:
            continue
        hl = entry.get("hl", "zh-CN")
        gl = entry.get("gl", "CN")
        ceid = entry.get("ceid", "CN:zh-Hans")
        url = (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote(query)
            + f"&hl={hl}&gl={gl}&ceid={ceid}"
        )
        source = {
            "id": "google_news",
            "name": f"Google 新闻 · {entry.get('label', query)}",
            "lang": "zh" if hl.startswith("zh") else "en",
            "weight": float(entry.get("weight", 0.95)),
            "ai_only": True,
        }
        raw = http_get(url, timeout=20, tries=2)
        if not raw:
            continue
        parsed = parse_feed(raw, source)
        parsed.sort(key=lambda i: parse_dt(i.get("published", "")) or now_utc(), reverse=True)
        limit = int(entry.get("max_items", 8))
        strict_domain = hl.startswith("zh")
        kept = 0
        for item in parsed:
            published = parse_dt(item.get("published", ""))
            if published and (now_utc() - published) > timedelta(days=60):
                continue  # 检索会翻出旧文，超过两个月的不进榜
            publisher = item.get("publisher") or ""
            if publisher and item["title"].endswith(" - " + publisher):
                item["title"] = item["title"][: -(len(publisher) + 3)].strip()
            if len(item["title"]) < 8 or GOOGLE_NEWS_JUNK.search(item["title"]):
                continue
            if not GOOGLE_NEWS_GATE.search(item["title"]):
                # 英文媒体经常把关键词放在摘要里，标题过不了就看标题+摘要
                if strict_domain or not GOOGLE_NEWS_GATE.search(
                    item["title"] + " " + item.get("summary", "")
                ):
                    continue
            if not domain_allowed(item.get("publisher_url", ""), strict=strict_domain):
                continue
            if not strict_domain and not is_preferred_language(item["title"]):
                continue  # 英文检索偶尔混进其他语种，标题里没有英文常用词就丢掉
            item["source"] = publisher or source["name"]
            item["default_category"] = entry.get("hint")
            item["extra"] = f"Google 新闻 · {entry.get('label', '')}"
            items.append(item)
            kept += 1
            if kept >= limit:
                break
        log(f"  · Google 新闻「{entry.get('label', query)}」: {kept} 条")
        time.sleep(0.5)
    return items


def fetch_hn_queries(config: dict, classifier: Classifier) -> list[dict]:
    """Hacker News 关键词搜索（Algolia 接口，无需鉴权）。"""
    items: list[dict] = []
    for entry in config.get("hn_queries", []):
        query = entry.get("q", "")
        if not query:
            continue
        url = (
            "https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=10&query="
            + urllib.parse.quote(query)
            + "&numericFilters="
            + urllib.parse.quote(f"points>{int(entry.get('min_points', 10))}")
        )
        data = get_json(url, timeout=20, tries=2)
        hits = (data or {}).get("hits") or []
        kept = 0
        for hit in hits:
            title = (hit.get("title") or "").strip()
            if not title:
                continue
            created = parse_dt(hit.get("created_at", ""))
            if created and (now_utc() - created) > timedelta(days=21):
                continue  # 搜索结果里翻出的老帖不进榜单
            points = hit.get("points") or 0
            items.append(
                {
                    "title": title,
                    "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                    "summary": clip(strip_html(hit.get("story_text") or ""), 200)
                    or f"Hacker News 讨论，{points} 赞",
                    "published": iso(created),
                    "source": f"HN · {entry.get('label', '搜索')}",
                    "source_id": "hn_algolia",
                    "lang": "en",
                    "weight": 0.9,
                    "kind": "article",
                    "extra": f"▲ {points}",
                }
            )
            kept += 1
        log(f"  · HN 搜索「{entry.get('label', query)}」: {kept} 条")
        time.sleep(0.7)
    return items


def fetch_github_trending(config: dict, classifier: Classifier) -> list[dict]:
    raw = http_get("https://github.com/trending?since=daily", timeout=20)
    if not raw:
        return []
    page = raw.decode("utf-8", "replace")
    blocks = page.split('<article class="Box-row"')[1:]
    items: list[dict] = []
    for block in blocks[:45]:
        repo_match = re.search(r'<h2[^>]*>[\s\S]{0,900}?href="/([^"/?]+)/([^"/?]+)"', block)
        if not repo_match:
            continue
        owner, repo = repo_match.group(1), repo_match.group(2)
        if owner in ("login", "signup", "sponsors"):
            continue
        desc_match = re.search(r'<p class="[^"]*col-9[^"]*"[^>]*>([\s\S]*?)</p>', block)
        desc = strip_html(desc_match.group(1)) if desc_match else ""
        lang_match = re.search(r'itemprop="programmingLanguage">([^<]+)<', block)
        stars_match = re.search(r'href="/[^"]+/stargazers"[^>]*>[\s\S]{0,900}?([\d,]{2,})\s*</a>', block)
        today_match = re.search(r"([\d,]+)\s*stars?\s*today", block, re.I)
        text = f"{owner}/{repo} {desc} {lang_match.group(1) if lang_match else ''}"
        if not classifier.is_ai(text) and not classifier.hits(text, "drama"):
            continue
        items.append(
            {
                "title": f"{owner}/{repo}",
                "url": f"https://github.com/{owner}/{repo}",
                "summary": clip(desc or "GitHub Trending 项目", 220),
                "published": iso(now_utc()),
                "source": "GitHub Trending",
                "source_id": "github_trending",
                "lang": "en",
                "weight": 1.0,
                "kind": "repo",
                "stars": int((stars_match.group(1) if stars_match else "0").replace(",", "") or 0),
                "extra": f"今日 +{(today_match.group(1) if today_match else '?')}"
                + (f" · {lang_match.group(1)}" if lang_match else ""),
            }
        )
    log(f"  · GitHub Trending: 命中 {len(items)} 个 AI/视频相关仓库")
    return items


def fetch_github_search(config: dict, classifier: Classifier) -> list[dict]:
    gh = config.get("github", {})
    items: list[dict] = []
    for entry in gh.get("searches", []):
        url = (
            "https://api.github.com/search/repositories?q="
            + urllib.parse.quote(entry["q"])
            + f"&sort={entry.get('sort','stars')}&order=desc&per_page=6"
        )
        data = get_json(url, timeout=20, tries=2)
        if not data or not data.get("items"):
            log(f"  ! GitHub 搜索无结果: {entry['q']}")
            continue
        for repo in data["items"]:
            if repo.get("archived"):
                continue
            desc = (repo.get("description") or "").strip()
            stars = repo.get("stargazers_count") or 0
            items.append(
                {
                    "title": repo.get("full_name", ""),
                    "url": repo.get("html_url", ""),
                    "summary": clip(desc or "GitHub 项目", 220),
                    "published": iso(parse_dt(repo.get("pushed_at", ""))),
                    "source": f"GitHub · {entry.get('label','搜索')}",
                    "source_id": "github_search",
                    "lang": "en",
                    "weight": 1.0,
                    "kind": "repo",
                    "stars": stars,
                    "extra": f"★ {stars:,}",
                }
            )
        time.sleep(2.2)  # 未鉴权搜索接口限流较严
    log(f"  · GitHub 搜索: 汇总 {len(items)} 个项目")
    return items


# --------------------------------------------------------------------------
# Codex Skill 扫描
# --------------------------------------------------------------------------

FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def parse_skill_md(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(6000)
    except Exception:  # noqa: BLE001
        return {}
    meta = {"name": os.path.basename(os.path.dirname(path)), "description": ""}
    match = FRONT_RE.match(text)
    if match:
        lines = match.group(1).splitlines()
        key = None
        buf: list[str] = []
        for line in lines:
            if re.match(r"^\s+", line) and key:
                buf.append(line.strip())
                continue
            if key and buf:
                meta[key] = " ".join(buf)
                buf = []
            m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
            if not m:
                continue
            key = m.group(1).lower()
            value = m.group(2).strip().strip('"').strip("'")
            if value in ("|", ">", "|-", ">-"):
                value = ""
            meta[key] = value
        if key and buf:
            meta[key] = " ".join(buf)
    if not meta.get("description"):
        body = FRONT_RE.sub("", text)
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("---"):
                meta["description"] = line
                break
    return {
        "name": (meta.get("name") or os.path.basename(os.path.dirname(path))).strip(),
        "description": clip(strip_html(meta.get("description", "")), 260),
        "path": os.path.dirname(path).replace("\\", "/"),
    }


def scan_skills(config: dict) -> list[dict]:
    found: dict[str, dict] = {}
    for root in config.get("skill_dirs", []):
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            dirnames[:] = [
                d for d in dirnames
                if d not in (".backup", "node_modules", ".git", "__pycache__")
            ]
            if depth > 6:
                dirnames[:] = []
                continue
            if "SKILL.md" not in filenames:
                continue
            meta = parse_skill_md(os.path.join(dirpath, "SKILL.md"))
            key = meta.get("name") or dirpath
            rel = dirpath.replace("\\", "/").lower()
            origin = "插件内置" if "plugins" in rel else "个人 Skill"
            meta["origin"] = origin
            meta["url"] = "file:///" + os.path.join(dirpath, "SKILL.md").replace("\\", "/")
            if key not in found:
                found[key] = meta
    skills = sorted(found.values(), key=lambda s: (s["origin"], s["name"].lower()))
    log(f"  · 本地 Skill: 收录 {len(skills)} 个")
    return skills


# --------------------------------------------------------------------------
# 历史 / 去重
# --------------------------------------------------------------------------

def load_history() -> dict:
    if not os.path.exists(HISTORY_PATH):
        return {}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def merge_history(history: dict, items: list[dict], config: dict) -> list[dict]:
    history_days = int(config.get("options", {}).get("history_days", 90))
    cutoff = now_utc() - timedelta(days=history_days)
    today = today_str()
    seen_titles = {norm_title(v.get("title", "")) for v in history.values() if v.get("title")}
    fresh: list[dict] = []
    new_count = 0

    for item in items:
        key = item_id(item["title"], item["url"])
        title_key = norm_title(item["title"])
        item["id"] = key
        existing = history.get(key)
        if existing:
            item["first_seen"] = existing.get("first_seen", today)
            # 用新抓到的描述补齐旧数据
            if not existing.get("summary") and item.get("summary"):
                existing["summary"] = item["summary"]
            history[key].update({k: v for k, v in item.items() if v not in (None, "", [])})
        else:
            if title_key and title_key in seen_titles:
                continue
            item["first_seen"] = today
            history[key] = item
            if title_key:
                seen_titles.add(title_key)
            new_count += 1
            fresh.append(item)

    pruned = {
        k: v for k, v in history.items()
        if (parse_dt(v.get("published", "")) or parse_dt(v.get("first_seen", "") + "T00:00:00Z") or now_utc()) >= cutoff
    }
    return pruned, new_count


def reclassify_history(history: dict, classifier: Classifier, days: int = 60) -> tuple[int, int]:
    """用当前规则重算近期条目的分类与得分，改了关键词不用清库。"""
    cutoff = now_utc() - timedelta(days=days)
    changed = 0
    dropped: list[str] = []
    for item in history.values():
        if item.get("kind") not in ("article", "repo"):
            continue
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        # 专业源条目退回到不符合内容闸门时直接清掉（比如只剩器材评测）
        if is_junk_title(item.get("title", "")) or (
            item.get("craft_source")
            and (
                GEAR_NOISE.search(item.get("title", ""))
                or not CRAFT_GATE.search(text)
                or not is_preferred_language(item.get("title", ""))
                or PROMO_NOISE.search(item.get("title", ""))
            )
        ):
            dropped.append(item.get("id", ""))
            continue
        stamp = parse_dt(item.get("published", "")) or parse_dt(
            (item.get("first_seen") or "") + "T00:00:00Z"
        )
        if stamp and stamp < cutoff:
            continue
        category, tags = classifier.classify(item.get("title", ""), text, item.get("kind", "article"))
        if item.get("default_category") and category in ("trend", "hotspot"):
            category = item["default_category"]
        if category == "trend" and not TREND_GATE.search(item.get("title", "")):
            dropped.append(item.get("id", ""))
            continue
        if category != item.get("category"):
            changed += 1
        item["category"] = category
        item["tags"] = tags
        item["score"] = score_item(item, classifier)
    for key in dropped:
        history.pop(key, None)
    return changed, len(dropped)


def build_view(history: dict, config: dict, fresh_ids: set[str]) -> dict:
    options = config.get("options", {})
    max_per_category = int(options.get("max_per_category", 60))
    fresh_hours = int(options.get("fresh_window_hours", 30))
    fresh_cutoff = now_utc() - timedelta(hours=fresh_hours)

    buckets: dict[str, list[dict]] = {key: [] for key, _ in CATEGORY_META}
    for item in history.values():
        category = item.get("category", "hotspot")
        if category not in buckets:
            category = "trend"
        entry = dict(item)
        entry["is_new"] = entry.get("id") in fresh_ids
        buckets[category].append(entry)

    caps = options.get("category_caps", {})
    for key in buckets:
        bucket_cap = int(caps.get(key, max_per_category))
        buckets[key].sort(key=lambda x: x.get("score", 0), reverse=True)
        limited, per_source = [], {}
        for item in buckets[key]:
            source = item.get("source", "")
            if per_source.get(source, 0) >= 10:
                continue
            per_source[source] = per_source.get(source, 0) + 1
            limited.append(item)
            if len(limited) >= bucket_cap:
                break
        buckets[key] = limited

    recent = [
        item for item in history.values()
        if (parse_dt(item.get("published", "")) or fresh_cutoff) >= fresh_cutoff
    ]
    recent.sort(key=lambda x: x.get("score", 0), reverse=True)
    return {"buckets": buckets, "recent_count": len(recent)}


# --------------------------------------------------------------------------
# 页面渲染
# --------------------------------------------------------------------------

def load_digest() -> dict | None:
    if not os.path.exists(DIGEST_PATH):
        return None
    try:
        with open(DIGEST_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def load_zh_notes() -> dict:
    """data/zh.json：给非中文条目配的一句话中文导读，key 是条目 id。"""
    if not os.path.exists(ZH_PATH):
        return {}
    try:
        with open(ZH_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001
        return {}
    if isinstance(data, dict) and isinstance(data.get("items"), dict):
        data = data["items"]
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def load_skills_snapshot() -> list[dict]:
    """云端没有本机 Skill 目录时，用仓库里的快照兜底。"""
    if not os.path.exists(SKILLS_SNAPSHOT_PATH):
        return []
    try:
        with open(SKILLS_SNAPSHOT_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def attach_zh_notes(history: dict, notes: dict) -> int:
    if not notes:
        return 0
    count = 0
    for item in history.values():
        note = notes.get(item.get("id", ""))
        if note:
            item["zh"] = note
            count += 1
    return count


def build_access_info() -> dict:
    """页面底部展示的访问地址：本机、局域网 IP、主机名。"""
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.append(ip)
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    public = ""
    if os.path.exists(TUNNEL_URL_PATH):
        try:
            with open(TUNNEL_URL_PATH, "r", encoding="utf-8") as fh:
                public = fh.read().strip()
        except OSError:
            public = ""
    return {
        "port": SERVE_PORT,
        "local": f"http://127.0.0.1:{SERVE_PORT}/",
        "lan": [f"http://{ip}:{SERVE_PORT}/" for ip in ips],
        "hostname": f"http://{hostname}:{SERVE_PORT}/" if hostname else "",
        "public": public,
    }


def build_digest_fallback(history: dict) -> dict:
    # 精选优先放资讯类内容，开源仓库排后面
    ranked = sorted(
        history.values(),
        key=lambda x: (x.get("kind") == "repo", -x.get("score", 0)),
    )
    # 按类别配额挑选，优先技巧 / 学习 / 手艺，资讯类只留一两条
    quota = [
        ("editing", 2), ("directing", 2), ("aicraft", 2), ("learning", 2),
        ("storyboard", 1), ("trend", 1), ("tools", 1),
    ]
    chosen, used = [], set()
    for category, need in quota:
        taken = 0
        for item in ranked:
            if taken >= need or len(chosen) >= 9:
                break
            if item.get("category") != category or item["id"] in used:
                continue
            used.add(item["id"])
            chosen.append(item)
            taken += 1
    for item in ranked:
        if len(chosen) >= 6:
            break
        if item["id"] in used:
            continue
        used.add(item["id"])
        chosen.append(item)
    return {
        "date": today_str(),
        "auto": True,
        "summary": "脚本按「时效 + 关键词命中 + 来源权重」自动排序：优先剪辑、导演、分镜、AI 创作技巧与学习类内容，资讯只留少量。",
        "picks": [
            {"title": i["title"], "url": i["url"], "why": i.get("source", ""), "id": i["id"]}
            for i in chosen
        ],
    }


def render(config: dict, history: dict, view: dict, skills: list[dict], stats: dict, digest) -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as fh:
        template = fh.read()

    payload = {
        "generated_at": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M"),
        "date": today_str(),
        "stats": stats,
        "categories": [{"key": k, "label": lab} for k, lab in CATEGORY_META],
        "items": view["buckets"],
        "recent_count": view["recent_count"],
        "skills": skills,
        "digest": digest,
        "access": build_access_info(),
    }
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = template.replace("__PAYLOAD__", blob).replace("__DATE__", today_str())
    out_path = os.path.join(ROOT, "index.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return out_path


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def run(render_only: bool, open_after: bool) -> int:
    started = time.time()
    config = load_config()
    classifier = Classifier(config.get("keywords", {}))
    history = load_history()
    fresh_ids: set[str] = set()
    stats = {"sources_ok": 0, "sources_total": len(config.get("feeds", [])), "new": 0, "total": 0}

    if render_only:
        log("跳过抓取，仅重新渲染页面")
        fresh_ids = {v["id"] for v in history.values() if v.get("first_seen") == today_str() and v.get("id")}
        stats["new"] = len(fresh_ids)
        stats["total"] = len(history)
    else:
        log(f"开始抓取，共 {stats['sources_total']} 个订阅源")
        raw_items = fetch_feeds(config, classifier)
        raw_items += fetch_google_news(config, classifier)
        raw_items += fetch_hn_queries(config, classifier)
        raw_items += fetch_github_trending(config, classifier)
        raw_items += fetch_github_search(config, classifier)
        stats["sources_ok"] = stats["sources_total"]

        kept_items: list[dict] = []
        for item in raw_items:
            if TITLE_JUNK.search(item["title"]):
                continue
            category, tags = classifier.classify(item["title"], item.get("summary", ""), item.get("kind", "article"))
            if item.get("default_category") and category in ("trend", "hotspot"):
                category = item["default_category"]
            if category == "trend" and not TREND_GATE.search(item["title"]):
                continue  # 风向栏目只留有观点、有判断的内容，纯新闻不入榜
            item["category"] = category
            item["tags"] = tags
            item["score"] = score_item(item, classifier)
            kept_items.append(item)

        history, new_count = merge_history(history, kept_items, config)
        today = today_str()
        stats["new"] = sum(1 for v in history.values() if v.get("first_seen") == today)
        stats["fetched"] = len(kept_items)
        fresh_ids = {v.get("id") for v in history.values() if v.get("first_seen") == today_str()}
        log(f"抓取完成：原始 {len(raw_items)} 条，写入 {new_count} 条，今日累计 {stats['new']} 条，库存 {len(history)} 条")
        save_json(HISTORY_PATH, history)

    skills = scan_skills(config)
    if not skills:
        skills = load_skills_snapshot()
        if skills:
            log(f"本机没有 Skill 目录，使用仓库快照里的 {len(skills)} 个")
    for skill in skills:
        skill["id"] = item_id(skill["name"], skill.get("path", skill["name"]))
    if skills and os.environ.get("AI_DAILY_SKIP_SKILL_SNAPSHOT") != "1":
        try:
            save_json(SKILLS_SNAPSHOT_PATH, skills)
        except OSError:
            pass

    moved, dropped = reclassify_history(history, classifier)
    if moved or dropped:
        log(f"按最新规则重分类 {moved} 条，清掉不符合闸门的 {dropped} 条")
    stats["new"] = sum(1 for v in history.values() if v.get("first_seen") == today_str())
    stats["total"] = len(history)
    zh_count = attach_zh_notes(history, load_zh_notes())
    if zh_count:
        log(f"已挂上 {zh_count} 条中文导读")
    if not render_only:
        save_json(HISTORY_PATH, history)

    view = build_view(history, config, fresh_ids)
    stats["total"] = len(history)
    digest = load_digest() or build_digest_fallback(history)
    if digest.get("date") != today_str() and not digest.get("auto"):
        digest["stale"] = True

    out_path = render(config, history, view, skills, stats, digest)
    save_json(LATEST_PATH, {"generated_at": iso(now_utc()), "stats": stats, "view": view, "skills": skills, "digest": digest})
    save_json(os.path.join(ARCHIVE_DIR, f"{today_str()}.json"), history)

    elapsed = time.time() - started
    log(f"页面已生成：{out_path}（耗时 {elapsed:.1f}s）")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(log_lines) + "\n")

    if open_after:
        try:
            os.startfile(out_path)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 日报每日热点采集器")
    parser.add_argument("--render", action="store_true", help="不联网，仅用已有数据重新生成页面")
    parser.add_argument("--open", action="store_true", help="完成后自动打开页面")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return run(render_only=args.render, open_after=args.open)


if __name__ == "__main__":
    raise SystemExit(main())
