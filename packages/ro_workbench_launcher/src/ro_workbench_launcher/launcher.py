"""工作台启动器：端口探测 + 内嵌 FastAPI + 自动开浏览器 + 托盘。

双击 .app 后直接运行此脚本。
服务器在后台线程中运行，避免子进程复杂度。
"""

from __future__ import annotations

import atexit
import socket
import threading
import time
import webbrowser
import sys
from pathlib import Path


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_server(port: int, ready_event: threading.Event) -> None:
    """在后台线程启动 uvicorn。"""
    import uvicorn
    try:
        from ro_workbench_api.app import app
    except ImportError:
        # 退化：内置占位 app
        from fastapi import FastAPI
        app = FastAPI()

        @app.get("/health")
        def health() -> dict[str, str]:
            return {"status": "ok"}

    ready_event.set()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def _run_tray(port: int) -> None:
    """系统托盘，提供退出入口。"""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print(f"工作台运行中: http://127.0.0.1:{port}", file=sys.stderr)
        print("按 Ctrl+C 退出", file=sys.stderr)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, 14, 14), radius=3, fill=(37, 99, 235))

    def on_quit(icon: pystray.Icon) -> None:
        icon.stop()
        import os
        os._exit(0)

    icon = pystray.Icon(
        "RO Workbench", img, "RO 单据工作台",
        menu=pystray.Menu(
            pystray.MenuItem(
                f"打开工作台 (:{port})",
                lambda: webbrowser.open(f"http://127.0.0.1:{port}"),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", on_quit),
        ),
    )
    icon.run()


def main() -> None:
    port = _find_free_port()
    print(f"启动工作台于 http://127.0.0.1:{port}", file=sys.stderr)

    ready = threading.Event()
    server_thread = threading.Thread(target=_run_server, args=(port, ready), daemon=True)
    server_thread.start()

    # 等待 server 就绪
    ready.wait(timeout=5)
    time.sleep(0.5)

    webbrowser.open(f"http://127.0.0.1:{port}")
    _run_tray(port)


if __name__ == "__main__":
    main()
