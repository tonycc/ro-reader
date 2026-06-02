"""工作台启动器：端口探测 + 拉起 FastAPI + 自动开浏览器 + 托盘。

Spike C（Phase 0 遗留 → Phase 3 前置）的核心交付物。

用法：
    uv run python -m ro_workbench_launcher.launcher
    # → 双击 .app 后实际调用的就是这个脚本
"""

from __future__ import annotations

import atexit
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# 托盘图标（16×16 蓝色小方块）
_ICON_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAHklEQVQ4T2P8z8BQ"
    "w0hFYBwFoyAYBcOgYBSMgiEPAAAe0AABJdQytAAAAABJRU5ErkJggg=="
)


def _find_free_port() -> int:
    """绑定 port 0 获得一个空闲端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int) -> subprocess.Popen[bytes]:
    """以子进程启动 HTTP server，监听指定端口。

    后端 app 尚未实现时，用 http.server 作为占位（可返回简单页面）。
    """
    server_script = Path(__file__).resolve().parent / "_placeholder_server.py"
    script = str(server_script)
    if not server_script.exists():
        # 退化到 python -m http.server
        cmd = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
        cwd = _frontend_dist()
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=cwd)
        return proc

    proc = subprocess.Popen(
        [sys.executable, script, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def _server_script_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "ro_workbench_api" / "src" / "ro_workbench_api" / "app.py"


def _frontend_dist() -> str:
    return str(Path(__file__).resolve().parent.parent.parent.parent.parent / "frontend" / "dist")


def _open_browser(url: str, *, delay: float = 0.5) -> None:
    """延迟后打开默认浏览器。延迟是为了让 server 先完成启动。"""
    time.sleep(delay)
    webbrowser.open(url)


def _run_tray(port: int, server_proc: subprocess.Popen[bytes]) -> None:
    """启动系统托盘，提供退出入口。"""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        # 无托盘时退化为 Ctrl+C
        print(f"工作台运行中: http://127.0.0.1:{port}", file=sys.stderr)
        print("按 Ctrl+C 退出", file=sys.stderr)
        try:
            server_proc.wait()
        except KeyboardInterrupt:
            server_proc.terminate()
        return

    # 生成一个 16×16 的小图标
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, 14, 14), radius=3, fill=(37, 99, 235))

    def on_quit(icon: pystray.Icon) -> None:
        server_proc.terminate()
        icon.stop()

    icon = pystray.Icon(
        "RO Workbench",
        img,
        "RO 单据工作台",
        menu=pystray.Menu(
            pystray.MenuItem(f"打开工作台 (:{port})", lambda: webbrowser.open(f"http://127.0.0.1:{port}")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", on_quit),
        ),
    )
    # macOS 需要用 thread 跑 tray，否则会阻塞子进程等待
    icon.run_detached()
    server_proc.wait()
    icon.stop()


def main() -> None:
    port = _find_free_port()
    print(f"启动工作台于 http://127.0.0.1:{port}", file=sys.stderr)

    proc = _start_server(port)

    def cleanup() -> None:
        proc.terminate()

    atexit.register(cleanup)

    _open_browser(f"http://127.0.0.1:{port}", delay=0.8)
    _run_tray(port, proc)


if __name__ == "__main__":
    main()
