"""工作台启动器：端口探测 + 内嵌 FastAPI + 自动开浏览器 + 托盘。

双击 .app / .exe 直接运行。服务器在后台线程中运行，避免子进程复杂度。
退出托盘时通过信号优雅关闭，让 uvicorn 清理连接再退出。
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

_shutdown_requested = threading.Event()
_server_error: BaseException | None = None  # 服务线程捕获的异常，供主线程读取


def _resource_root() -> Path:
    """查找开发态或 PyInstaller 打包态资源根目录。"""
    # PyInstaller 打包后，资源在 sys._MEIPASS 下
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[5]


def _find_frontend_dist() -> str:
    """查找前端构建产物目录。"""
    dist = _resource_root() / "frontend" / "dist"
    if dist.exists():
        return str(dist)
    return ""


def _find_tray_icon() -> Path | None:
    """查找开发态或 PyInstaller 打包态的托盘图标。"""
    candidates = (
        _resource_root() / "resources" / "tray-icon.png",
        Path(__file__).resolve().parents[2] / "resources" / "tray-icon.png",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_server(port: int) -> None:
    """在后台线程启动 uvicorn，监听 shutdown 事件退出。

    Windows 注意：必须在线程内设置 SelectorEventLoop，
    ProactorEventLoop（Windows 默认）在 frozen 环境下与 uvicorn 不兼容。
    """
    global _server_error
    try:
        # Windows frozen 环境必须用 SelectorEventLoop；ProactorEventLoop 不兼容
        if sys.platform == "win32":
            import asyncio

            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        import uvicorn
        from ro_workbench_api.app import app

        # log_config=None: 跳过 uvicorn 的 dictConfig 调用。
        # 默认 LOGGING_CONFIG 引用 "uvicorn.logging.DefaultFormatter" 工厂类，
        # PyInstaller frozen 环境下 logging.config 无法按字符串路径找到该类，
        # 会抛 ValueError: Unable to configure formatter "default"。
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_config=None,
        )
        server = uvicorn.Server(config)

        def _poll_shutdown() -> None:
            while not _shutdown_requested.is_set():
                time.sleep(0.5)
            server.should_exit = True

        threading.Thread(target=_poll_shutdown, daemon=True).start()
        server.run()
    except Exception as exc:
        _server_error = exc


def _wait_until_ready(port: int, timeout: float = 30.0) -> bool:
    """等待 uvicorn 就绪。Windows PyInstaller 首次启动较慢，给 30 秒。"""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        # 如果服务线程已报错，立即放弃等待
        if _server_error is not None:
            return False
        try:
            with urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except URLError:
            time.sleep(0.3)
    return False


def _run_tray(port: int) -> None:
    """系统托盘，提供退出入口。"""
    try:
        import pystray  # type: ignore[import-untyped]
        from PIL import Image, ImageDraw
    except ImportError:
        print(f"赛肯单据生成工具运行中: http://127.0.0.1:{port}", file=sys.stderr)
        print("按 Ctrl+C 退出", file=sys.stderr)
        try:
            while not _shutdown_requested.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        _shutdown_requested.set()
        return

    icon_path = _find_tray_icon()
    if icon_path is not None:
        try:
            with Image.open(icon_path) as source:
                img = source.convert("RGBA")
        except OSError as exc:
            print(f"托盘图标加载失败（{icon_path}）：{exc}，使用内置图标", file=sys.stderr)
            img = None
    else:
        print("找不到托盘图标资源，使用内置图标", file=sys.stderr)
        img = None

    if img is None:
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((2, 2, 14, 14), radius=3, fill=(37, 99, 235))

    def on_quit(icon: pystray.Icon) -> None:
        icon.stop()
        _shutdown_requested.set()

    icon = pystray.Icon(
        "赛肯单据生成工具",
        img,
        "赛肯单据生成工具",
        menu=pystray.Menu(
            pystray.MenuItem(
                f"打开赛肯单据工具 (:{port})",
                lambda: webbrowser.open(f"http://127.0.0.1:{port}"),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", on_quit),
        ),
    )
    icon.run()


def _fatal(msg: str) -> None:
    """显示致命错误并退出。在 Windows 上弹对话框，其他平台打印 stderr。"""
    print(f"[RO Workbench] 致命错误: {msg}", file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, msg, "赛肯单据工具 - 启动失败", 0x10)
        except Exception:
            pass
    sys.exit(1)


def _lock_file_path() -> Path:
    return Path(tempfile.gettempdir()) / "saiken_doc_port.txt"


def _read_lock_port() -> int | None:
    """读取锁文件中的端口号，如果该端口仍在响应则返回端口号。"""
    try:
        port = int(_lock_file_path().read_text(encoding="utf-8").strip())
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
            if resp.status == 200:
                return port
    except Exception:
        pass
    return None


def main() -> None:
    existing = _read_lock_port()
    if existing is not None:
        # 已有运行中的实例，直接打开浏览器到已有端口
        webbrowser.open(f"http://127.0.0.1:{existing}")
        return

    port = _find_free_port()
    _lock_file_path().write_text(str(port), encoding="utf-8")

    # 设置前端静态资源路径（在 import app 之前）
    frontend_dist = os.environ.get("RO_WORKBENCH_FRONTEND_DIST", "")
    if not frontend_dist:
        frontend_dist = _find_frontend_dist()
    if not frontend_dist:
        resource_root = _resource_root()
        _fatal(
            f"找不到前端文件（frontend/dist）。\n"
            f"资源根目录：{resource_root}\n"
            f"期望路径：{resource_root / 'frontend' / 'dist'}\n\n"
            f"请重新下载安装包。"
        )
    os.environ["RO_WORKBENCH_FRONTEND_DIST"] = frontend_dist
    os.environ.setdefault("RO_WORKBENCH_RESOURCE_ROOT", str(_resource_root()))

    print(f"启动工作台于 http://127.0.0.1:{port}", file=sys.stderr)

    server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server_thread.start()

    if not _wait_until_ready(port):
        if _server_error is not None:
            details = "".join(
                traceback.format_exception(
                    type(_server_error), _server_error, _server_error.__traceback__
                )
            )
            _fatal(
                f"工作台服务启动失败（端口 {port}）：\n\n"
                f"{type(_server_error).__name__}: {_server_error}\n\n"
                f"详细信息：\n{details}"
            )
        _fatal(
            f"工作台服务启动失败：30 秒内未响应健康检查。\n\n"
            f"可能原因：\n"
            f"• 端口 {port} 被防火墙或杀毒软件拦截\n"
            f"• 系统资源不足\n\n"
            f"请以管理员身份运行，或检查防火墙设置。"
        )

    webbrowser.open(f"http://127.0.0.1:{port}")
    _run_tray(port)
    # 退出后清理锁文件
    _lock_file_path().unlink(missing_ok=True)


if __name__ == "__main__":
    # Windows PyInstaller 必需：防止 multiprocessing spawn 无限递归
    import multiprocessing

    multiprocessing.freeze_support()
    main()
