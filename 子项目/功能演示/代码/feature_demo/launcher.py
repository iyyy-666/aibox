from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from .app import build_application
from .models import ModuleState


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return int(server_socket.getsockname()[1])


def _wait_until_ready(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise RuntimeError("功能演示服务启动超时。")


def open_main_window(webview_module, url: str, manager) -> None:
    window = webview_module.create_window(
        "功能演示",
        url,
        min_size=(1100, 680),
    )

    def close_after_cleanup() -> bool:
        return manager.shutdown().state == ModuleState.IDLE

    window.events.closing += close_after_cleanup
    webview_module.start()


def main() -> int:
    import webview

    app, manager = build_application()
    port = _available_port()
    url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    server_thread = threading.Thread(target=server.run, name="feature-demo-api")
    server_thread.start()
    try:
        _wait_until_ready(url)
        open_main_window(webview, url, manager)
    finally:
        manager.shutdown()
        server.should_exit = True
        server_thread.join(timeout=5.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
