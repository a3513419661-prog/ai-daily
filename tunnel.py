# -*- coding: utf-8 -*-
"""
AI 日报 · 公网隧道守护脚本

用 cloudflared 的快速隧道把本地看板发布到公网，得到一个 https://xxx.trycloudflare.com 地址，
这样换网络（比如回家）也能打开。地址会写进 data/tunnel-url.txt，并显示在页面底部。

不需要注册账号。注意：隧道重启（含电脑重启）后地址会变，脚本会自动把新地址写进文件。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
CLOUDFLARED = os.path.join(ROOT, "tools", "cloudflared.exe")
URL_FILE = os.path.join(DATA_DIR, "tunnel-url.txt")
LOG_FILE = os.path.join(DATA_DIR, "tunnel.log")
TARGET = "http://127.0.0.1:8765"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CREATE_NO_WINDOW = 0x08000000


def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def publish_url(url: str) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(URL_FILE, "w", encoding="utf-8") as fh:
            fh.write(url + "\n")
    except OSError:
        pass
    log(f"公网地址：{url}")


def run_tunnel() -> None:
    creation_flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [
            CLOUDFLARED,
            "tunnel",
            "--url",
            TARGET,
            "--no-autoupdate",
            "--loglevel",
            "info",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    found = False
    for line in proc.stdout or []:
        match = URL_RE.search(line)
        if match and not found:
            found = True
            publish_url(match.group(0))
    proc.wait()
    log(f"隧道进程退出，返回码 {proc.returncode}")


def main() -> int:
    if not os.path.exists(CLOUDFLARED):
        log("找不到 tools\\cloudflared.exe，无法建立公网隧道")
        return 1
    log("启动公网隧道")
    while True:
        try:
            run_tunnel()
        except Exception as exc:  # noqa: BLE001
            log(f"隧道异常：{exc}")
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
