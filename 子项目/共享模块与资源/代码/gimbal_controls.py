from __future__ import annotations

import threading
import tkinter as tk

from gimbal_service import GimbalService


class GimbalControls:
    def __init__(self, parent: tk.Widget, root: tk.Tk, status) -> None:
        self.root = root
        self.status = status
        self.service = GimbalService()
        self.step = tk.StringVar(value="20")
        self.position = tk.StringVar()
        self._busy = False
        self._refresh()
        panel = tk.Frame(parent, bg="#181d22")
        panel.pack(fill=tk.X, padx=16, pady=(10, 12))
        tk.Label(panel, text="云台微调", bg="#181d22", fg="#f1f5f9", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w")
        tk.Label(panel, textvariable=self.position, bg="#181d22", fg="#9fb0c2", font=("Consolas", 10)).pack(anchor="w", pady=(4, 6))
        grid = tk.Frame(panel, bg="#181d22")
        grid.pack(fill=tk.X)
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1)
        self.buttons = []
        for text, axis, direction, row, col in (("左", "yaw", -1, 0, 0), ("右", "yaw", 1, 0, 1), ("上", "pitch", -1, 1, 0), ("下", "pitch", 1, 1, 1)):
            button = tk.Button(grid, text=text, command=lambda a=axis, d=direction: self.move(a, d), bg="#263039", fg="#e7edf3", activebackground="#394651", activeforeground="#ffffff", relief=tk.FLAT, font=("Microsoft YaHei", 11), height=1)
            button.grid(row=row, column=col, sticky="ew", padx=3, pady=3)
            self.buttons.append(button)
        row = tk.Frame(panel, bg="#181d22")
        row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(row, text="步长", bg="#181d22", fg="#9fb0c2", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        tk.Entry(row, textvariable=self.step, width=5, justify="center").pack(side=tk.LEFT, padx=6)

    def move(self, axis: str, direction: int) -> None:
        if self._busy:
            return
        try:
            step = max(1, min(500, int(self.step.get())))
        except ValueError:
            self.step.set("20")
            self.status("云台步长应为数字")
            return
        self._busy = True
        for button in self.buttons:
            button.configure(state=tk.DISABLED)
        self.status("云台正在移动")
        threading.Thread(target=self._move_worker, args=(axis, direction, step), daemon=True).start()

    def _move_worker(self, axis: str, direction: int, step: int) -> None:
        ok, detail = self.service.move(axis, direction, step_pwm=step)
        self.root.after(0, lambda: self._complete(ok, detail))

    def _complete(self, ok: bool, detail: str) -> None:
        self._busy = False
        for button in self.buttons:
            button.configure(state=tk.NORMAL)
        self._refresh()
        self.status("云台已移动" if ok else f"云台通信失败：{detail}")

    def _refresh(self) -> None:
        yaw, pitch = self.service.position
        self.position.set(f"水平 {yaw}  俯仰 {pitch}")
