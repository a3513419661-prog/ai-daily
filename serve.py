# -*- coding: utf-8 -*-
"""
AI 日报 · 本地看板服务

把 ai-daily 目录挂在 HTTP 上，方便随时用一条链接打开：
    本机   http://127.0.0.1:8765/
    同 Wi-Fi 的手机/平板   http://<这台电脑的局域网 IP>:8765/

只用标准库，双击 start-server.cmd 即可启动。
"""

from __future__ import annotations

import argparse
import functools
import os
import socket
import sys
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(ROOT, "data", "server.log")

# 只对外暴露这三个路径，data/ 下面的一切（含本地路径信息）不通过 HTTP 提供
PUBLIC_FILES = {"/", "/index.html", "/preview.png"}


class DashboardHandler(SimpleHTTPRequestHandler):
    """静态文件服务，禁用缓存，保证打开的永远是最新一版页面。"""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/favicon.ico"):
            self.send_response(204)
            self.end_headers()
            return
        clean = self.path.split("?", 1)[0].split("#", 1)[0]
        if clean not in PUBLIC_FILES:
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("仅提供看板页面".encode("utf-8"))
            return
        super().do_GET()

    def log_message(self, fmt: str, *args) -> None:
        line = "[{}] {} {}\n".format(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            self.address_string(),
            fmt % args,
        )
        try:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass


def local_ips() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 日报本地看板服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0（同网段可访问）")
    parser.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    args = parser.parse_args()

    handler = functools.partial(DashboardHandler, directory=ROOT)
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        print(f"端口 {args.port} 起不来：{exc}", file=sys.stderr)
        return 1

    print(f"AI 日报看板已启动：http://127.0.0.1:{args.port}/")
    for ip in local_ips():
        print(f"  同一网络可用：http://{ip}:{args.port}/")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
