# -*- coding: utf-8 -*-
"""
可选：用大模型给看板写「今日精选摘要」和新条目的「中文导读」。

只在配置了环境变量时工作，否则直接跳过（页面会退回脚本自带的排序精选）：
    LLM_API_KEY   接口密钥
    LLM_BASE_URL  兼容 OpenAI 的接口地址，默认 https://api.openai.com/v1
    LLM_MODEL     模型名，默认 gpt-4o-mini

本地由 Codex 定时任务负责这部分，云端由 GitHub Actions 调用本脚本。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import collect  # noqa: E402

STRUCTURE_PROMPT = """你在为一个本地「AI 日报」看板写内容。看板定位是「手艺与学习为主、资讯为辅」，
栏目包括 aicraft（AI 创作技巧）、editing（剪辑·后期）、directing（导演·影视化）、
storyboard（分镜·视觉）、learning（教程·学习）、tools（开源·工具）、drama（AI 短剧动态）、trend（风向·洞察）。
只输出 JSON，不要解释。"""


def preference_note(config: dict) -> str:
    """把 config.json 里的 ai_preferences 变成提示词里的一段要求。"""
    pref = str(config.get("options", {}).get("ai_preferences", "")).strip()
    if not pref:
        return ""
    return "\n\n本期用户的明确偏好（优先满足）：\n" + pref


def call_llm(prompt: str, api_key: str, base_url: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": STRUCTURE_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return data["choices"][0]["message"]["content"]


def parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


def main() -> int:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        print("未配置 LLM_API_KEY，跳过 AI 摘要（页面使用脚本排序的精选）")
        return 0
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini").strip()

    config = collect.load_config()
    history = collect.load_history()
    if not history:
        print("没有数据，跳过")
        return 0
    pref = preference_note(config)

    buckets = collect.build_view(history, config, set())["buckets"]
    craft_keys = ("editing", "directing", "storyboard", "aicraft", "learning", "video")
    lines = []
    for key in craft_keys:
        for item in buckets.get(key, [])[:12]:
            lines.append(
                f'{{"id":"{item["id"]}","cat":"{key}","title":"{item["title"][:110]}"}}'
            )
    listing = "\n".join(lines[:60])

    existing = collect.load_zh_notes()
    todo = [ln for ln in lines if json.loads(ln)["id"] not in existing][:30]
    todo_text = "\n".join(todo)

    try:
        note_raw = call_llm(
            "下面是今天的条目。给每条写一句中文导读（不超过 60 字，说清能学到什么，不要复述标题）。\n"
            '输出格式：{"items":{"<id>":"中文导读", ...}}'
            + pref
            + "\n\n" + todo_text,
            api_key,
            base_url,
            model,
        )
        notes = parse_json(note_raw).get("items", {})
        if notes:
            merged = dict(existing)
            merged.update({str(k): str(v) for k, v in notes.items()})
            collect.save_json(
                collect.ZH_PATH,
                {"generated": collect.today_str(), "items": merged},
            )
            print(f"写入 {len(notes)} 条中文导读")
    except Exception as exc:  # noqa: BLE001
        print(f"中文导读生成失败：{exc}")

    try:
        digest_raw = call_llm(
            "下面是今天的条目。挑 8-10 条最值得学的，编辑、导演、AI 创作技巧各至少 2 条，"
            "分镜、教程各至少 1 条，开源或风向最多 1 条。\n"
            '输出格式：{"summary":"2-3 句话概括今天能学到什么","picks":[{"id":"<id>","why":"一句话"}]}'
            + pref
            + "\n\n" + listing,
            api_key,
            base_url,
            model,
        )
        digest = parse_json(digest_raw)
        index = {item["id"]: item for group in buckets.values() for item in group}
        picks = []
        for pick in digest.get("picks", []):
            item = index.get(str(pick.get("id", "")))
            if not item:
                continue
            picks.append(
                {
                    "title": item["title"],
                    "url": item["url"],
                    "why": str(pick.get("why", ""))[:80],
                    "id": item["id"],
                }
            )
        if picks:
            collect.save_json(
                collect.DIGEST_PATH,
                {
                    "date": collect.today_str(),
                    "summary": str(digest.get("summary", ""))[:300],
                    "picks": picks,
                },
            )
            print(f"写入今日精选 {len(picks)} 条")
    except Exception as exc:  # noqa: BLE001
        print(f"精选摘要生成失败：{exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
