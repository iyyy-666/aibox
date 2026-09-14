#!/usr/bin/env python3
"""Simple local ASR test UI for RK3588."""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk

from audio_config import print_audio_devices
from voice_engine import VoiceEngine


class InputVoiceTestApp:
    def __init__(self):
        print_audio_devices("input_voice_test")
        self.root = tk.Tk()
        self.root.title("English Voice Input Test")
        self.root.geometry("760x520")
        self.root.configure(bg="#101417")

        self.voice = VoiceEngine()
        self.voice.use_command_grammar = False
        self.voice.set_commands({})

        self.listening = False
        self.status = tk.StringVar(value="Idle")
        self.button_text = tk.StringVar(value="Start Listening")
        self.backend = tk.StringVar(value="-")
        self.input_device = tk.StringVar(value="-")
        self.output_device = tk.StringVar(value="-")
        self.debug_wav = tk.StringVar(value="-")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(500, self.refresh)

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Microsoft YaHei", 14), padding=12)

        frame = tk.Frame(self.root, bg="#101417", padx=22, pady=20)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text="English Voice Input Test",
            fg="#f2f5f2",
            bg="#101417",
            font=("Microsoft YaHei", 24, "bold"),
        ).pack(anchor="w")
        tk.Label(
            frame,
            text="Press Start Listening, speak, then press Stop to view the transcript.",
            fg="#9aa7a1",
            bg="#101417",
            font=("Microsoft YaHei", 12),
        ).pack(anchor="w", pady=(5, 16))

        ttk.Button(frame, textvariable=self.button_text, command=self.toggle).pack(fill="x", pady=(0, 12))

        info = tk.Frame(frame, bg="#171d22", padx=12, pady=10)
        info.pack(fill="x", pady=(0, 14))
        for label, var in [
            ("Status", self.status),
            ("ASR", self.backend),
            ("Input", self.input_device),
            ("Output", self.output_device),
            ("WAV", self.debug_wav),
        ]:
            row = tk.Frame(info, bg="#171d22")
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=8, anchor="w", fg="#9aa7a1", bg="#171d22", font=("Microsoft YaHei", 10)).pack(side="left")
            tk.Label(row, textvariable=var, anchor="w", fg="#3fd47d", bg="#171d22", font=("Microsoft YaHei", 10)).pack(side="left", fill="x", expand=True)

        tk.Label(frame, text="RAW ASR", fg="#f2f5f2", bg="#101417", font=("Microsoft YaHei", 13, "bold")).pack(anchor="w")
        self.raw_box = tk.Text(frame, height=5, bg="#171d22", fg="#f2f5f2", insertbackground="#f2f5f2", relief="flat", wrap="word", font=("Microsoft YaHei", 15), padx=12, pady=10)
        self.raw_box.pack(fill="x", pady=(6, 14))
        self.raw_box.insert("1.0", "Waiting for speech...")

        tk.Label(frame, text="NORMALIZED RESULT", fg="#f2f5f2", bg="#101417", font=("Microsoft YaHei", 13, "bold")).pack(anchor="w")
        self.normalized_box = tk.Text(frame, height=5, bg="#171d22", fg="#f2f5f2", insertbackground="#f2f5f2", relief="flat", wrap="word", font=("Microsoft YaHei", 15), padx=12, pady=10)
        self.normalized_box.pack(fill="both", expand=True, pady=(6, 0))
        self.normalized_box.insert("1.0", "Waiting for speech...")

    def toggle(self):
        if self.listening:
            self.voice.stop()
            self.listening = False
            self.button_text.set("Start Listening")
            self.status.set("Stopped")
            return

        self.status.set("Loading speech model...")
        threading.Thread(target=self._start_voice, daemon=True).start()

    def _start_voice(self):
        if not self.voice.status().get("loaded"):
            if not self.voice.load():
                self.status.set("Failed to start: " + self.voice.last_error)
                return
        if self.voice.start():
            self.listening = True
            self.button_text.set("Stop Listening")
            self.status.set("Listening")

    def refresh(self):
        s = self.voice.status()
        self.backend.set(f"{s.get('backend')} / {s.get('model')}")
        self.input_device.set(str(s.get("input_device") or s.get("device") or "-"))
        self.output_device.set(str(s.get("output_device") or "-"))
        self.debug_wav.set(str(s.get("last_debug_wav") or "-"))
        if s.get("raw_asr"):
            self._set_text(self.raw_box, str(s.get("raw_asr")))
        elif not self.voice.status().get("running"):
            self._set_text(self.raw_box, "Waiting for speech...")
        if s.get("normalized_text"):
            self._set_text(self.normalized_box, str(s.get("normalized_text")))
        elif not self.voice.status().get("running"):
            self._set_text(self.normalized_box, "Waiting for speech...")
        if s.get("last_error"):
            self.status.set("Error: " + str(s.get("last_error")))
        elif s.get("busy"):
            self.status.set("Recognizing")
        elif s.get("running"):
            self.status.set("Listening")
        self.root.after(350, self.refresh)

    def _set_text(self, box: tk.Text, value: str):
        current = box.get("1.0", "end").strip()
        if current == value:
            return
        box.delete("1.0", "end")
        box.insert("1.0", value)

    def close(self):
        self.voice.stop()
        time.sleep(0.1)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    InputVoiceTestApp().run()
