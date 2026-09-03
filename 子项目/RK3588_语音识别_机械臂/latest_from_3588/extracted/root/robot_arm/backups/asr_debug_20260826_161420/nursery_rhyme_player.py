"""Voice controlled Chinese nursery rhyme player for RK3588."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
import time
import wave
from contextlib import suppress
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import numpy as np

from audio_config import audio_output_device, print_audio_devices, voice_input_device
from speech_context import correct_text, match_song

VOICE_DEVICE = os.getenv("NURSERY_VOICE_DEVICE", voice_input_device())
PLAY_DEVICE = os.getenv("NURSERY_PLAY_DEVICE", audio_output_device())
VOSK_MODEL_DIR = os.getenv("VOSK_MODEL_DIR", "/root/robot_arm/voice/vosk-model-cn-0.22")
SHERPA_ASR_DIR = os.getenv(
    "SHERPA_ASR_DIR",
    "/root/sherpa_models/sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01",
)
SHERPA_TTS_DIR = os.getenv("SHERPA_TTS_DIR", "/root/sherpa_models/vits-melo-tts-zh_en")
SHERPA_TTS_SID = int(os.getenv("NURSERY_SHERPA_TTS_SID", "0"))
SHERPA_TTS_SPEED = float(os.getenv("NURSERY_SHERPA_TTS_SPEED", "0.8"))
SHERPA_TTS_LENGTH_SCALE = float(os.getenv("NURSERY_SHERPA_TTS_LENGTH_SCALE", "1.05"))
TTS_OUTPUT_GAIN = float(os.getenv("NURSERY_TTS_OUTPUT_GAIN", "1.65"))
APP_LOG = os.getenv("NURSERY_APP_LOG", "/tmp/nursery_rhyme_player.log")
ASSET_DIR = Path("/root/robot_arm/assets/nursery")

SAMPLE_RATE = 16000
FRAME_SIZE = 160
GAIN = 2.2
TRIGGER_PEAK = 0.180
SILENCE_PEAK = 0.085
MIN_RECORD_SEC = 0.12
MAX_RECORD_SEC = 2.0
POST_SILENCE_SEC = 0.12
NOISE_CALIBRATE_SEC = 0.35
NOISE_TRIGGER_MULT = 3.2
NOISE_SILENCE_MULT = 1.75
MIN_VALID_PEAK_MARGIN = 0.028
MIN_VALID_AUDIO_SEC = 0.18

PROMPT = "\u4f60\u597d\uff0c\u8bf7\u95ee\u60f3\u542c\u4ec0\u4e48\u6b4c\uff1f\u4e24\u53ea\u8001\u864e\uff0c\u8fd8\u662f\u5c0f\u661f\u661f\uff1f"
WAITING_TEXT = "\u7b49\u5f85\u9009\u62e9\u6b4c\u66f2...\n\n" + PROMPT
PROMPT_WAV = ASSET_DIR / "prompt_question.wav"

SONGS = {
    "\u5c0f\u661f\u661f": {
        "aliases": ("\u5c0f\u661f\u661f", "\u5c0f\u661f", "\u661f\u661f", "\u5c0f\u5fc3\u661f", "\u5c0f\u7329\u7329", "\u5c0f\u65b0\u661f", "\u5c0f\u884c\u661f", "\u5c0f\u6b23\u6b23", "\u5c0f\u661f\u5fc3", "\u5c0f\u7329\u661f", "\u5c0f\u65b0\u65b0", "\u5c0f\u5fc3\u5fc3", "\u64ad\u653e\u5c0f\u661f\u661f", "\u6211\u8981\u542c\u5c0f\u661f\u661f", "\u4e00\u95ea\u4e00\u95ea", "\u4eae\u6676\u6676", "\u6ee1\u5929\u90fd\u662f\u5c0f\u661f\u661f"),
        "source_file": "xiaoxingxing_vocal.mp3",
        "lyrics": [
            "\u4e00\u95ea\u4e00\u95ea\u4eae\u6676\u6676",
            "\u6ee1\u5929\u90fd\u662f\u5c0f\u661f\u661f",
            "\u6302\u5728\u5929\u7a7a\u653e\u5149\u660e",
            "\u597d\u50cf\u8bb8\u591a\u5c0f\u773c\u775b",
            "\u4e00\u95ea\u4e00\u95ea\u4eae\u6676\u6676",
            "\u6ee1\u5929\u90fd\u662f\u5c0f\u661f\u661f",
        ],
    },
    "\u4e24\u53ea\u8001\u864e": {
        "aliases": ("\u4e24\u53ea\u8001\u864e", "\u4e24\u652f\u8001\u864e", "\u4e24\u4e2a\u8001\u864e", "\u4e24\u53ea\u8001", "\u4e24\u53ea\u864e", "\u4e24\u8001\u864e", "\u4e8c\u53ea\u8001\u864e", "\u4fe9\u53ea\u8001\u864e", "\u6881\u5fd7\u8001\u864e", "\u826f\u77e5\u8001\u864e", "\u6768\u77e5\u8001", "\u6768\u77e5\u8001\u864e", "\u4e24\u53ea\u8111\u864e", "\u4e24\u53ea\u8001\u53e4", "\u4e24\u53ea\u8001\u4e94", "\u4e24\u53ea\u8001\u80e1", "\u4e24\u53ea\u52b3\u864e", "\u4e24\u53ea\u8001\u864e\u513f\u6b4c", "\u64ad\u653e\u4e24\u53ea\u8001\u864e", "\u6211\u8981\u542c\u4e24\u53ea\u8001\u864e", "\u8001\u864e", "\u8111\u864e", "\u52b3\u864e", "\u8001\u80e1", "\u8001\u53e4", "\u8001\u4e94", "\u8dd1\u5f97\u5feb", "\u771f\u5947\u602a"),
        "source_file": "liangzhilaohu_vocal.mp3",
        "trim_start": 0.0,
        "trim_duration": 16.1,
        "lyrics": [
            "\u4e24\u53ea\u8001\u864e\uff0c\u4e24\u53ea\u8001\u864e",
            "\u8dd1\u5f97\u5feb\uff0c\u8dd1\u5f97\u5feb",
            "\u4e00\u53ea\u6ca1\u6709\u773c\u775b",
            "\u4e00\u53ea\u6ca1\u6709\u5c3e\u5df4",
            "\u771f\u5947\u602a\uff0c\u771f\u5947\u602a",
        ],
    },
}


def normalize(text: str) -> str:
    return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff").lower()


def choose_song(text: str) -> str | None:
    matched = match_song(text)
    if matched:
        return matched
    text = correct_text(text, "nursery", strict=True)
    normalized = normalize(text)
    if not normalized:
        return None
    scores: dict[str, int] = {}
    for name, song in SONGS.items():
        score = 0
        for alias in song["aliases"]:
            alias_norm = normalize(alias)
            if alias_norm and alias_norm in normalized:
                score += 8 + len(alias_norm)
        scores[name] = score

    if "\u5c0f\u661f" in normalized or "\u661f\u661f" in normalized:
        scores["\u5c0f\u661f\u661f"] += 10
    if "\u4e24\u53ea" in normalized and "\u8001\u864e" in normalized:
        scores["\u4e24\u53ea\u8001\u864e"] += 20
    elif "\u8001\u864e" in normalized:
        scores["\u4e24\u53ea\u8001\u864e"] += 10

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ordered or ordered[0][1] < 10:
        return None
    if len(ordered) > 1 and ordered[0][1] - ordered[1][1] < 6:
        return None
    return ordered[0][0]


def boost_wav_volume(path: str, gain: float) -> None:
    try:
        with wave.open(path, "rb") as wf:
            params = wf.getparams()
            data = wf.readframes(wf.getnframes())
        if params.sampwidth != 2:
            return
        audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        audio = np.clip(audio * gain, -32768, 32767).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setparams(params)
            wf.writeframes(audio.tobytes())
    except Exception:
        pass


class NurseryRhymePlayer:
    def __init__(self):
        print_audio_devices("nursery")
        self.root = tk.Tk()
        self.root.title("\u8bed\u97f3\u513f\u6b4c\u64ad\u653e")
        self.root.geometry("620x520")
        self.root.configure(bg="#101417")

        self.listening = False
        self.playing = False
        self.paused = False
        self.speaking = False
        self.listen_thread: threading.Thread | None = None
        self.play_proc: subprocess.Popen | None = None
        self.asr_backend = "sherpa"
        self.asr_model = None
        self.sherpa_tts = None
        self.sherpa_tts_ready = False
        self.sherpa_tts_lock = threading.Lock()
        self.vosk_model = None
        self.model_loading = False
        self.play_token = 0
        self.noise_peak = 0.0
        self.dynamic_trigger = TRIGGER_PEAK
        self.dynamic_silence = SILENCE_PEAK

        self.status = tk.StringVar(value="\u51c6\u5907\u4e2d")
        self.last_text = tk.StringVar(value="-")
        self.current_song = tk.StringVar(value="-")
        self.listen_button_text = tk.StringVar(value="\u5f00\u542f\u8bed\u97f3\u8f93\u5165")
        self.pause_button_text = tk.StringVar(value="\u6682\u505c")
        self.lyrics_box: tk.Text | None = None

        self._build_ui()
        self._raise_volume()
        self.root.after(2500, self._start_model_load)
        threading.Thread(target=self._init_sherpa_tts, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(300, self.ask_song)

    def _ui_status(self, text: str):
        try:
            self.root.after(0, lambda: self.status.set(text))
        except Exception:
            self.status.set(text)

    def _log(self, message: str) -> None:
        try:
            with open(APP_LOG, "a", encoding="utf-8") as fh:
                fh.write(f"{time.time():.3f} {message}\n")
        except Exception:
            pass

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Microsoft YaHei", 14), padding=11)

        frame = tk.Frame(self.root, bg="#101417", padx=22, pady=20)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="\u8bed\u97f3\u513f\u6b4c\u64ad\u653e", fg="#f2f5f2", bg="#101417",
                 font=("Microsoft YaHei", 24, "bold")).pack(anchor="w")
        tk.Label(frame, text=PROMPT, fg="#9aa7a1", bg="#101417",
                 font=("Microsoft YaHei", 12)).pack(anchor="w", pady=(5, 16))

        ttk.Button(frame, textvariable=self.listen_button_text, command=self.toggle_listen).pack(fill="x", pady=(0, 10))
        controls = tk.Frame(frame, bg="#101417")
        controls.pack(fill="x", pady=(0, 14))
        ttk.Button(controls, textvariable=self.pause_button_text, command=self.toggle_pause).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(controls, text="\u9000\u51fa", command=self.exit_song).pack(side="left", fill="x", expand=True, padx=(6, 0))

        info = tk.Frame(frame, bg="#171d22", padx=12, pady=10)
        info.pack(fill="x")
        for label, var in [("\u72b6\u6001", self.status), ("\u6700\u8fd1\u8bc6\u522b", self.last_text), ("\u6b63\u5728\u64ad\u653e", self.current_song)]:
            row = tk.Frame(info, bg="#171d22")
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=8, anchor="w", fg="#9aa7a1", bg="#171d22",
                     font=("Microsoft YaHei", 11)).pack(side="left")
            tk.Label(row, textvariable=var, anchor="w", fg="#3fd47d", bg="#171d22",
                     font=("Microsoft YaHei", 11)).pack(side="left", fill="x", expand=True)

        tk.Label(frame, text="\u6b4c\u8bcd", fg="#f2f5f2", bg="#101417",
                 font=("Microsoft YaHei", 14, "bold")).pack(anchor="w", pady=(18, 8))
        self.lyrics_box = tk.Text(frame, height=11, bg="#171d22", fg="#f2f5f2",
                                  insertbackground="#f2f5f2", relief="flat", wrap="word",
                                  font=("Microsoft YaHei", 16), padx=12, pady=10)
        self.lyrics_box.pack(fill="both", expand=True)
        self._set_lyrics(WAITING_TEXT)

    def _set_lyrics(self, text: str):
        if not self.lyrics_box:
            return
        self.lyrics_box.configure(state="normal")
        self.lyrics_box.delete("1.0", tk.END)
        self.lyrics_box.insert("1.0", text)
        self.lyrics_box.configure(state="disabled")

    def _raise_volume(self):
        for control in ("Master", "PCM", "Speaker"):
            with suppress(Exception):
                subprocess.run(["amixer", "-c", "0", "sset", control, "70%"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)

    def _load_model(self):
        if self.model_loading or self.asr_model is not None or self.vosk_model is not None:
            return
        self.model_loading = True
        try:
            base = Path(SHERPA_ASR_DIR)
            model = base / "model.int8.onnx"
            tokens = base / "tokens.txt"
            if not model.exists() or not tokens.exists():
                raise FileNotFoundError("sherpa model not found")
            import sherpa_onnx

            self.asr_model = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
                tokens=str(tokens),
                model=str(model),
                num_threads=3,
                sample_rate=SAMPLE_RATE,
                feature_dim=80,
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=0.8,
                rule2_min_trailing_silence=0.25,
                rule3_min_utterance_length=5.0,
                decoding_method="greedy_search",
                provider="cpu",
            )
            self.asr_backend = "sherpa"
            self._ui_status("\u8bed\u97f3\u6a21\u578b\u5df2\u52a0\u8f7d")
        except Exception:
            self.asr_backend = "vosk"
        try:
            if self.asr_backend != "vosk":
                return
            from vosk import Model
            self.vosk_model = Model(VOSK_MODEL_DIR)
            self._ui_status("\u8bed\u97f3\u6a21\u578b\u5df2\u52a0\u8f7d")
        except Exception as exc:
            self._ui_status(f"\u8bed\u97f3\u6a21\u578b\u52a0\u8f7d\u5931\u8d25: {exc}")
        finally:
            self.model_loading = False

    def _start_model_load(self):
        if self.asr_model is None and self.vosk_model is None and not self.model_loading:
            self.status.set("\u6b63\u5728\u52a0\u8f7d\u8bed\u97f3\u6a21\u578b")
            threading.Thread(target=self._load_model, daemon=True).start()

    def _init_sherpa_tts(self) -> None:
        try:
            base = Path(SHERPA_TTS_DIR)
            model = base / "model.onnx"
            tokens = base / "tokens.txt"
            lexicon = base / "lexicon.txt"
            if not model.exists() or not tokens.exists() or not lexicon.exists():
                raise FileNotFoundError(f"{SHERPA_TTS_DIR} not complete")
            import sherpa_onnx

            rule_fsts = ",".join(
                str(p) for p in [base / "phone.fst", base / "date.fst", base / "number.fst"] if p.exists()
            )
            cfg = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=str(model),
                        lexicon=str(lexicon),
                        tokens=str(tokens),
                        data_dir="",
                        length_scale=SHERPA_TTS_LENGTH_SCALE,
                    ),
                    provider="cpu",
                    num_threads=4,
                ),
                rule_fsts=rule_fsts,
                max_num_sentences=1,
            )
            self.sherpa_tts = sherpa_onnx.OfflineTts(cfg)
            self.sherpa_tts_ready = True
        except Exception as exc:
            self.sherpa_tts = None
            self.sherpa_tts_ready = False
            self._ui_status(f"\u8bed\u97f3\u8f93\u51fa\u52a0\u8f7d\u5931\u8d25: {exc}")

    def ask_song(self):
        if self.playing:
            return
        self.paused = False
        self.pause_button_text.set("\u6682\u505c")
        self.status.set("\u8bf7\u8bf4\u6b4c\u540d")
        self.current_song.set("-")
        self._set_lyrics(WAITING_TEXT)
        threading.Thread(target=self._speak_prompt, daemon=True).start()

    def toggle_listen(self):
        if self.listening:
            self.listening = False
            self.listen_button_text.set("\u5f00\u542f\u8bed\u97f3\u8f93\u5165")
            self.status.set("\u8bed\u97f3\u8f93\u5165\u5df2\u5173\u95ed")
            return
        if self.asr_model is None and self.vosk_model is None:
            self._start_model_load()
            self.status.set("\u8bed\u97f3\u6a21\u578b\u8fd8\u5728\u52a0\u8f7d\uff0c\u8bf7\u7a0d\u7b49")
            if self.asr_model is None and self.vosk_model is None:
                return
        self.listening = True
        self.listen_button_text.set("\u5173\u95ed\u8bed\u97f3\u8f93\u5165")
        self.status.set("\u8bed\u97f3\u8f93\u5165\u4e2d")
        self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listen_thread.start()

    def toggle_pause(self):
        if not self.play_proc or self.play_proc.poll() is not None:
            return
        if self.paused:
            os.kill(self.play_proc.pid, signal.SIGCONT)
            self.paused = False
            self.pause_button_text.set("\u6682\u505c")
            self.status.set("\u7ee7\u7eed\u64ad\u653e")
        else:
            os.kill(self.play_proc.pid, signal.SIGSTOP)
            self.paused = True
            self.pause_button_text.set("\u6062\u590d")
            self.status.set("\u5df2\u6682\u505c")

    def exit_song(self):
        self.play_token += 1
        self._stop_play_proc()
        self.listening = False
        self.playing = False
        self.paused = False
        self.speaking = False
        self.listen_button_text.set("\u5f00\u542f\u8bed\u97f3\u8f93\u5165")
        self.last_text.set("-")
        self.ask_song()

    def _speak_prompt(self):
        self.speaking = True
        wav_path = str(PROMPT_WAV) if PROMPT_WAV.exists() and PROMPT_WAV.stat().st_size > 1024 else self._make_tts(PROMPT)
        self._log(f"prompt_start path={wav_path!r}")
        if wav_path:
            self._play_wav_blocking(wav_path)
            if Path(wav_path) != PROMPT_WAV:
                with suppress(FileNotFoundError):
                    os.remove(wav_path)
        self.speaking = False
        self._log("prompt_end")
        if self.listening and not self.playing:
            self.root.after(0, lambda: self.status.set("\u8bed\u97f3\u8f93\u5165\u4e2d"))

    def _make_tts(self, text: str) -> str | None:
        fd, path = tempfile.mkstemp(prefix="nursery_tts_", suffix=".wav")
        os.close(fd)
        try:
            deadline = time.time() + 12.0
            while not self.sherpa_tts_ready and time.time() < deadline:
                time.sleep(0.05)
            if not self.sherpa_tts_ready or self.sherpa_tts is None:
                raise RuntimeError("sherpa tts not ready")
            import sherpa_onnx

            with self.sherpa_tts_lock:
                audio = self.sherpa_tts.generate(text.strip(), sid=SHERPA_TTS_SID, speed=SHERPA_TTS_SPEED)
            sherpa_onnx.write_wave(path, audio.samples, audio.sample_rate)
            boost_wav_volume(path, TTS_OUTPUT_GAIN)
            if not Path(path).exists() or Path(path).stat().st_size <= 1024:
                raise RuntimeError("sherpa tts produced no audio")
            return path
        except Exception:
            with suppress(FileNotFoundError):
                os.remove(path)
            return None

    def _ensure_song_asset(self, name: str) -> Path | None:
        song = SONGS[name]
        ASSET_DIR.mkdir(parents=True, exist_ok=True)
        path = ASSET_DIR / song["source_file"]
        if path.exists() and path.stat().st_size > 64 * 1024:
            return path
        self.status.set(f"\u7f3a\u5c11{name}\u5b8c\u6574\u4eba\u58f0\u97f3\u9891")
        return None

    def _build_play_file(self, name: str) -> str | None:
        song = SONGS[name]
        source = self._ensure_song_asset(name)
        if not source:
            return None
        fd, wav_path = tempfile.mkstemp(prefix="nursery_song_", suffix=".wav")
        os.close(fd)
        volume_filter = "volume=0.70"
        try:
            cmd = ["ffmpeg", "-y"]
            trim_start = song.get("trim_start")
            trim_duration = song.get("trim_duration")
            if trim_start is not None:
                cmd.extend(["-ss", str(trim_start)])
            cmd.extend(["-i", str(source)])
            if trim_duration is not None:
                cmd.extend(["-t", str(trim_duration)])
            cmd.extend(["-af", volume_filter, "-ac", "1", "-ar", "44100", wav_path])
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=90,
            )
            return wav_path if Path(wav_path).exists() and Path(wav_path).stat().st_size > 1024 else None
        except Exception:
            with suppress(FileNotFoundError):
                os.remove(wav_path)
            return None

    def _make_missing_song_prompt(self, name: str) -> str | None:
        return self._make_tts(f"\u8fd8\u6ca1\u627e\u5230{name}\u7684\u5b8c\u6574\u4eba\u58f0\u7248\u97f3\u9891\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002")

    def _play_wav_blocking(self, path: str):
        self._log(f"play_start device={PLAY_DEVICE} path={path}")
        self.play_proc = subprocess.Popen(
            ["aplay", "-q", "-D", PLAY_DEVICE, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.play_proc.wait()
        err = (self.play_proc.stderr.read() if self.play_proc.stderr else "").strip()
        self._log(f"play_end rc={self.play_proc.returncode} err={err!r}")
        self.play_proc = None

    def play_song(self, name: str):
        if self.playing:
            return
        song = SONGS[name]
        lyrics = "\n".join(song["lyrics"])
        self.playing = True
        self.paused = False
        self.play_token += 1
        token = self.play_token
        self.pause_button_text.set("\u6682\u505c")
        self.current_song.set(name)
        self.status.set(f"\u6b63\u5728\u64ad\u653e{name}")
        self._set_lyrics(lyrics)
        threading.Thread(target=self._play_song_worker, args=(token, name), daemon=True).start()

    def _play_song_worker(self, token: int, name: str):
        play_path = self._build_play_file(name)
        if token != self.play_token:
            if play_path:
                with suppress(FileNotFoundError):
                    os.remove(play_path)
            return
        if not play_path:
            play_path = self._make_missing_song_prompt(name)
        if play_path:
            try:
                self._play_wav_blocking(play_path)
            finally:
                with suppress(FileNotFoundError):
                    os.remove(play_path)
        if token != self.play_token:
            return
        self.playing = False
        self.paused = False
        self.root.after(0, self.ask_song)

    def _stop_play_proc(self):
        if self.play_proc and self.play_proc.poll() is None:
            if self.paused:
                with suppress(Exception):
                    os.kill(self.play_proc.pid, signal.SIGCONT)
            self.play_proc.terminate()
            with suppress(Exception):
                self.play_proc.wait(timeout=1)
            if self.play_proc.poll() is None:
                with suppress(Exception):
                    self.play_proc.kill()
        subprocess.run(["pkill", "-f", r"aplay.*(/tmp/nursery_|nursery_song_|nursery_tts_)"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.play_proc = None

    def _listen_loop(self):
        import alsaaudio
        try:
            pcm = alsaaudio.PCM(
                alsaaudio.PCM_CAPTURE,
                alsaaudio.PCM_NORMAL,
                VOICE_DEVICE,
                channels=1,
                rate=SAMPLE_RATE,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=FRAME_SIZE,
            )
        except Exception as exc:
            self.status.set(f"\u9ea6\u514b\u98ce\u542f\u52a8\u5931\u8d25: {exc}")
            self.listening = False
            self.listen_button_text.set("\u5f00\u542f\u8bed\u97f3\u8f93\u5165")
            return

        self._calibrate_noise(pcm)
        while self.listening:
            if self.playing or self.speaking:
                time.sleep(0.15)
                continue
            audio = self._record_utterance(pcm)
            if not audio:
                continue
            peak = self._audio_peak(audio)
            if not self._is_valid_audio(audio, peak):
                continue
            text = self._recognize(audio)
            if text:
                self.root.after(0, self._handle_text, text)
            time.sleep(0.04)

    def _audio_peak(self, audio: bytes) -> float:
        samples = np.frombuffer(audio, dtype=np.int16)
        if samples.size == 0:
            return 0.0
        return float(np.max(np.abs(samples))) / 32768.0

    def _calibrate_noise(self, pcm) -> None:
        peaks: list[float] = []
        deadline = time.time() + NOISE_CALIBRATE_SEC
        while self.listening and time.time() < deadline:
            try:
                length, data = pcm.read()
            except Exception:
                break
            if length <= 0:
                continue
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if samples.size == 0:
                continue
            boosted = np.clip(samples * GAIN, -32768, 32767).astype(np.int16)
            peaks.append(float(np.max(np.abs(boosted))) / 32768.0)
        if not peaks:
            return
        noise = float(np.percentile(np.array(peaks, dtype=np.float32), 90))
        self.noise_peak = noise
        self.dynamic_trigger = max(TRIGGER_PEAK, min(0.260, noise * NOISE_TRIGGER_MULT + 0.014))
        self.dynamic_silence = max(SILENCE_PEAK, min(0.135, self.dynamic_trigger * 0.70, noise * NOISE_SILENCE_MULT + 0.010))

    def _is_valid_audio(self, audio: bytes, peak: float) -> bool:
        duration = len(audio) / 2 / SAMPLE_RATE if audio else 0.0
        if duration < MIN_VALID_AUDIO_SEC:
            return False
        if peak < self.dynamic_trigger + MIN_VALID_PEAK_MARGIN:
            return False
        samples = np.frombuffer(audio, dtype=np.int16)
        if samples.size == 0:
            return False
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) / 32768.0
        return rms >= max(0.012, self.noise_peak * 0.85)

    def _recognize(self, audio: bytes) -> str:
        if self.asr_backend == "sherpa" and self.asr_model is not None:
            return self._recognize_sherpa(audio)
        return self._recognize_vosk(audio)

    def _recognize_sherpa(self, audio: bytes) -> str:
        try:
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            stream = self.asr_model.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            stream.accept_waveform(SAMPLE_RATE, np.zeros(int(0.12 * SAMPLE_RATE), dtype=np.float32))
            stream.input_finished()
            while self.asr_model.is_ready(stream):
                self.asr_model.decode_stream(stream)
            text = self.asr_model.get_result_all(stream).text
            return correct_text(text, "nursery", strict=True)
        except Exception:
            return ""

    def _recognize_vosk(self, audio: bytes) -> str:
        if self.vosk_model is None:
            return ""
        try:
            from vosk import KaldiRecognizer

            rec = KaldiRecognizer(self.vosk_model, SAMPLE_RATE)
            rec.AcceptWaveform(audio)
            text = json.loads(rec.FinalResult()).get("text", "").replace(" ", "")
            return correct_text(text, "nursery", strict=True)
        except Exception:
            return ""

    def _record_utterance(self, pcm) -> bytes:
        min_frames = max(1, int(MIN_RECORD_SEC * SAMPLE_RATE / FRAME_SIZE))
        max_frames = max(1, int(MAX_RECORD_SEC * SAMPLE_RATE / FRAME_SIZE))
        post_silence_frames = max(1, int(POST_SILENCE_SEC * SAMPLE_RATE / FRAME_SIZE))
        frames: list[bytes] = []
        speaking = False
        silence = 0
        started = time.monotonic()
        while self.listening and not self.playing and not self.speaking:
            try:
                length, data = pcm.read()
            except Exception:
                return b""
            if not length:
                continue
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            boosted = np.clip(samples * GAIN, -32768, 32767).astype(np.int16)
            peak = float(np.max(np.abs(boosted))) / 32768.0 if boosted.size else 0.0
            if peak >= self.dynamic_trigger:
                speaking = True
                silence = 0
                frames.append(boosted.tobytes())
            elif speaking:
                frames.append(boosted.tobytes())
                silence = silence + 1 if peak < self.dynamic_silence else 0
                if len(frames) >= min_frames and silence >= post_silence_frames:
                    break
            if speaking and len(frames) >= max_frames:
                break
            if not speaking and time.monotonic() - started > 0.45:
                break
        return b"".join(frames) if speaking else b""

    def _handle_text(self, text: str):
        if self.playing:
            return
        text = correct_text(text, "nursery", strict=True)
        self.last_text.set(text)
        song_name = choose_song(text)
        if song_name:
            self.play_song(song_name)
            return
        self.status.set("\u6ca1\u542c\u6e05\uff0c\u8bf7\u53ea\u8bf4\u5c0f\u661f\u661f\u6216\u4e24\u53ea\u8001\u864e")

    def close(self):
        self.listening = False
        self.playing = False
        self.speaking = False
        self.play_token += 1
        self._stop_play_proc()
        with suppress(Exception):
            self.root.destroy()
        os._exit(0)


if __name__ == "__main__":
    NurseryRhymePlayer().root.mainloop()
