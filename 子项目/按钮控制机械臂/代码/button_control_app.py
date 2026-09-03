from __future__ import annotations

import socket
import threading
import time

import webview

from config import WEB_PORT


def _server_ready(host: str = "127.0.0.1", port: int = WEB_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _start_server_once():
    if _server_ready():
        return

    def run_server():
        import server

        server.start()

    threading.Thread(target=run_server, daemon=True).start()


def _wait_for_server(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_ready():
            return True
        time.sleep(0.25)
    return False


def main():
    _start_server_once()
    _wait_for_server()
    webview.create_window(
        "按钮控制机械臂",
        f"http://127.0.0.1:{WEB_PORT}/button",
        width=1100,
        height=750,
        min_size=(900, 620),
    )
    webview.start()


if __name__ == "__main__":
    main()
