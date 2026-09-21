from __future__ import annotations


class FakeWorker:
    def __init__(self, module_id: str, pid: int = 42001):
        self.module_id = module_id
        self.pids = (pid,)
        self.started = False
        self.stopped = False
        self.commands: list[tuple[str, dict]] = []

    def start(self) -> None:
        self.started = True

    def command(self, name: str, payload: dict) -> dict:
        self.commands.append((name, payload))
        return {"ok": True, "command": name}

    def stop(self, timeout: float) -> None:
        self.stopped = True
        self.pids = ()

    def snapshot(self) -> dict:
        return {"ready": self.started and not self.stopped}
