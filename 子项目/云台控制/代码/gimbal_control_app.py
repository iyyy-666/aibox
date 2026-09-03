#!/usr/bin/env python3
from __future__ import annotations

import glob
import fcntl
import os
import struct
import threading
import time
import tkinter as tk
from dataclasses import dataclass

import serial


DEFAULT_PORTS = [
    "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
    "/dev/ttyUSB1",
    "/dev/serial/by-id/usb-WCH.CN_USB_Single_Serial_0004-if00",
    "/dev/ttyACM0",
]

SERVO_MIN = int(os.getenv("GIMBAL_SERVO_MIN", "500"))
SERVO_MAX = int(os.getenv("GIMBAL_SERVO_MAX", "2500"))
SERVO_CENTER = int(os.getenv("GIMBAL_SERVO_CENTER", "1500"))
STEP_DEFAULT = int(os.getenv("GIMBAL_STEP", "30"))
MOVE_TIME_MS = int(os.getenv("GIMBAL_MOVE_TIME_MS", "350"))

YAW_SERVO_ID = int(os.getenv("GIMBAL_YAW_SERVO_ID", "1"))
PITCH_SERVO_ID = int(os.getenv("GIMBAL_PITCH_SERVO_ID", "2"))

SERIAL_BAUD = int(os.getenv("GIMBAL_SERIAL_BAUD", "115200"))
SERIAL_TIMEOUT = float(os.getenv("GIMBAL_SERIAL_TIMEOUT", "0.1"))
SERIAL_ACK_TIMEOUT = float(os.getenv("GIMBAL_SERIAL_ACK_TIMEOUT", "0.45"))
SERIAL_REQUIRE_ACK = os.getenv("GIMBAL_SERIAL_REQUIRE_ACK", "0").strip().lower() in ("1", "true", "yes", "on")
SERIAL_PROTOCOL = os.getenv("GIMBAL_SERIAL_PROTOCOL", "hiwonder_pwm").strip().lower()
BACKEND_PREF = os.getenv("GIMBAL_BACKEND", "serial").strip().lower()

PWM_PERIOD_NS = int(os.getenv("GIMBAL_PWM_PERIOD_NS", "20000000"))
PWM_ADDR_YAW = int(os.getenv("GIMBAL_PWM_ADDR_YAW", "0x40"), 0)
PWM_ADDR_PITCH = int(os.getenv("GIMBAL_PWM_ADDR_PITCH", "0x41"), 0)
PWM_CH_YAW = int(os.getenv("GIMBAL_PWM_CH_YAW", "0"))
PWM_CH_PITCH = int(os.getenv("GIMBAL_PWM_CH_PITCH", "0"))

I2C_BUS_GLOB = os.getenv("GIMBAL_I2C_BUS_GLOB", "/dev/i2c-*")
I2C_ADDR_YAW = int(os.getenv("GIMBAL_I2C_ADDR_YAW", "0x40"), 0)
I2C_ADDR_PITCH = int(os.getenv("GIMBAL_I2C_ADDR_PITCH", "0x41"), 0)
I2C_CH_YAW = int(os.getenv("GIMBAL_I2C_CH_YAW", "0"), 0)
I2C_CH_PITCH = int(os.getenv("GIMBAL_I2C_CH_PITCH", "1"), 0)


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


def action_log(message: str) -> None:
    try:
        with open("/tmp/gimbal_control_actions.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


@dataclass
class GimbalState:
    yaw: int = SERVO_CENTER
    pitch: int = SERVO_CENTER
    connected: bool = False
    backend: str = ""
    target: str = ""
    last_command: str = ""
    last_error: str = ""


class SerialLobotBackend:
    def __init__(self) -> None:
        self.ser: serial.Serial | None = None
        self.lock = threading.Lock()
        self.port = ""

    def _candidate_ports(self) -> list[str]:
        raw = os.getenv("GIMBAL_SERIAL_PORTS", "").strip()
        ports = [item.strip() for item in raw.split(",") if item.strip()]
        if not ports:
            ports = list(DEFAULT_PORTS)
        for pattern in ("/dev/serial/by-id/*", "/dev/ttyACM*", "/dev/ttyUSB*"):
            for path in sorted(glob.glob(pattern)):
                if path not in ports:
                    ports.append(path)
        return ports

    @staticmethod
    def _lobot_frame(servo_id: int, position: int, time_ms: int) -> bytes:
        position = clamp(position, SERVO_MIN, SERVO_MAX)
        time_ms = clamp(time_ms, 1, 9999)
        lobot_position = clamp(round((position - 500) / 2), 0, 1000)
        payload = [
            0x55,
            0x55,
            servo_id & 0xFF,
            0x07,
            0x01,
            lobot_position & 0xFF,
            (lobot_position >> 8) & 0xFF,
            time_ms & 0xFF,
            (time_ms >> 8) & 0xFF,
        ]
        payload.append((~sum(payload[2:])) & 0xFF)
        return bytes(payload)

    @staticmethod
    def _pwm_command(servo_id: int, position: int, time_ms: int) -> bytes:
        position = clamp(position, SERVO_MIN, SERVO_MAX)
        time_ms = clamp(time_ms, 1, 9999)
        return f"#{servo_id:03d}P{position:04d}T{time_ms:04d}!\r\n".encode("ascii")

    @staticmethod
    def _hiwonder_pwm_frame(servo_id: int, position: int, time_ms: int) -> bytes:
        position = clamp(position, SERVO_MIN, SERVO_MAX)
        time_ms = clamp(time_ms, 20, 30000)
        servo_id = clamp(servo_id, 0, 7)
        data = [
            0x55,
            0x55,
            0x08,  # length: len byte + cmd + count + time(2) + one servo tuple(3)
            0x03,  # CMD_MULT_SERVO_MOVE
            0x01,
            time_ms & 0xFF,
            (time_ms >> 8) & 0xFF,
            servo_id & 0xFF,
            position & 0xFF,
            (position >> 8) & 0xFF,
        ]
        return bytes(data)

    def connect(self) -> tuple[bool, str]:
        if self.ser and self.ser.is_open:
            return True, self.port
        last_error = ""
        for port in self._candidate_ports():
            try:
                self.ser = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
                try:
                    self.ser.setDTR(False)
                    self.ser.setRTS(False)
                except OSError:
                    pass
                time.sleep(0.15)
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                self.port = port
                return True, port
            except Exception as exc:
                last_error = str(exc)
        return False, last_error or "no serial port available"

    def _packets_for(self, servo_id: int, position: int, time_ms: int) -> list[bytes]:
        if SERIAL_PROTOCOL in ("hiwonder_pwm", "hiwonder", "pwm_board"):
            return [self._hiwonder_pwm_frame(servo_id, position, time_ms)]
        if SERIAL_PROTOCOL == "lobot":
            return [self._lobot_frame(servo_id, position, time_ms)]
        if SERIAL_PROTOCOL == "pwm":
            return [self._pwm_command(servo_id, position, time_ms)]
        return [
            self._hiwonder_pwm_frame(servo_id, position, time_ms),
            self._pwm_command(servo_id, position, time_ms),
            self._lobot_frame(servo_id, position, time_ms),
        ]

    def _wait_ack(self, servo_id: int, position: int) -> tuple[bool, str]:
        assert self.ser is not None
        deadline = time.monotonic() + SERIAL_ACK_TIMEOUT
        received = bytearray()
        while time.monotonic() < deadline:
            chunk = self.ser.read(128)
            if chunk:
                received.extend(chunk)
                text = received.decode("ascii", "ignore")
                if "ACK" in text:
                    if f"id={servo_id}" in text or "id=" not in text:
                        return True, text.strip()
            else:
                time.sleep(0.01)
        text = received.decode("ascii", "ignore").strip()
        if text:
            return False, f"STM32 ack mismatch: {text}"
        return False, "serial port opened, but STM32 did not ACK"

    def probe(self) -> tuple[bool, str]:
        ok, detail = self.connect()
        if not ok:
            return False, detail
        ok, detail = self.send(YAW_SERVO_ID, SERVO_CENTER, 80, log_action=False)
        if not ok:
            self.disconnect()
            return False, detail
        return True, self.port

    def send(self, servo_id: int, position: int, time_ms: int, log_action: bool = True) -> tuple[bool, str]:
        ok, detail = self.connect()
        if not ok:
            return False, detail
        packets = self._packets_for(servo_id, position, time_ms)
        with self.lock:
            try:
                assert self.ser is not None
                self.ser.reset_input_buffer()
                for packet in packets:
                    self.ser.write(packet)
                    self.ser.flush()
                    time.sleep(0.02)
                ack_detail = ""
                if SERIAL_REQUIRE_ACK:
                    ack_ok, ack_detail = self._wait_ack(servo_id, position)
                    if not ack_ok:
                        port = self.port
                        self.disconnect()
                        action_log(f"serial_no_ack port={port} id={servo_id} pwm={position} detail={ack_detail}")
                        return False, ack_detail
                if log_action:
                    ack_suffix = f" ack={ack_detail}" if ack_detail else ""
                    action_log(f"serial_send port={self.port} id={servo_id} pwm={position} time={time_ms} protocol={SERIAL_PROTOCOL}{ack_suffix}")
                return True, f"{self.port} id={servo_id} pwm={position}"
            except Exception as exc:
                self.disconnect()
                action_log(f"serial_error id={servo_id} pwm={position} error={exc}")
                return False, str(exc)

    def disconnect(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None
        self.port = ""


class SysfsPwmBackend:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.left_chip = ""
        self.right_chip = ""
        self.left_channel = PWM_CH_YAW
        self.right_channel = PWM_CH_PITCH
        self.left_pwm_path = ""
        self.right_pwm_path = ""
        self._ready = False

    @staticmethod
    def _find_chip_by_addr(addr: int) -> str:
        needle = f"-{addr:04x}"
        for chip in sorted(glob.glob("/sys/class/pwm/pwmchip*")):
            device = os.path.realpath(os.path.join(chip, "device"))
            if needle in device.lower():
                return chip
        return ""

    @staticmethod
    def _ensure_dir(path: str) -> None:
        if not os.path.isdir(path):
            raise FileNotFoundError(path)

    @staticmethod
    def _write(path: str, value: int | str) -> None:
        with open(path, "w", encoding="ascii") as fh:
            fh.write(str(value))

    def _prepare_pwm(self, chip: str, channel: int) -> str:
        self._ensure_dir(chip)
        pwm_path = os.path.join(chip, f"pwm{channel}")
        if not os.path.isdir(pwm_path):
            self._write(os.path.join(chip, "export"), channel)
            for _ in range(50):
                if os.path.isdir(pwm_path):
                    break
                time.sleep(0.02)
        if not os.path.isdir(pwm_path):
            raise RuntimeError(f"pwm channel not ready: {chip} pwm{channel}")
        return pwm_path

    def connect(self) -> tuple[bool, str]:
        if self._ready:
            return True, f"{self.left_chip},{self.right_chip}"

        override_left = os.getenv("GIMBAL_PWM_CHIP_LEFT", "").strip()
        override_right = os.getenv("GIMBAL_PWM_CHIP_RIGHT", "").strip()
        chips = [path for path in (override_left, override_right) if path]
        if not chips:
            left = self._find_chip_by_addr(PWM_ADDR_YAW)
            right = self._find_chip_by_addr(PWM_ADDR_PITCH)
            if left:
                chips.append(left)
            if right:
                chips.append(right)

        if not chips:
            chips = sorted(glob.glob("/sys/class/pwm/pwmchip*"))

        if not chips:
            return False, "no pwmchip found"

        try:
            self.left_chip = chips[0]
            self.right_chip = chips[1] if len(chips) > 1 else chips[0]
            self.left_pwm_path = self._prepare_pwm(self.left_chip, self.left_channel)
            self.right_pwm_path = self._prepare_pwm(self.right_chip, self.right_channel if len(chips) > 1 else self.left_channel + 1)
            self._configure(self.left_pwm_path, SERVO_CENTER)
            self._configure(self.right_pwm_path, SERVO_CENTER)
            self._ready = True
            return True, f"{self.left_chip}:{self.left_channel}, {self.right_chip}:{self.right_channel if len(chips) > 1 else self.left_channel + 1}"
        except Exception as exc:
            self.disconnect()
            return False, str(exc)

    def _configure(self, pwm_path: str, pulse_us: int) -> None:
        pulse_us = clamp(pulse_us, SERVO_MIN, SERVO_MAX)
        duty_ns = pulse_us * 1000
        self._write(os.path.join(pwm_path, "period"), PWM_PERIOD_NS)
        self._write(os.path.join(pwm_path, "duty_cycle"), duty_ns)
        self._write(os.path.join(pwm_path, "enable"), 1)

    def set_pulse(self, side: str, pulse_us: int) -> tuple[bool, str]:
        ok, detail = self.connect()
        if not ok:
            return False, detail
        pwm_path = self.left_pwm_path if side == "yaw" else self.right_pwm_path
        try:
            with self.lock:
                self._configure(pwm_path, pulse_us)
            return True, pwm_path
        except Exception as exc:
            self.disconnect()
            return False, str(exc)

    def disconnect(self) -> None:
        for pwm_path in (self.left_pwm_path, self.right_pwm_path):
            if pwm_path and os.path.isdir(pwm_path):
                try:
                    self._write(os.path.join(pwm_path, "enable"), 0)
                except Exception:
                    pass
        self._ready = False
        self.left_chip = ""
        self.right_chip = ""
        self.left_pwm_path = ""
        self.right_pwm_path = ""


class RawI2CPca9685Backend:
    I2C_SLAVE = 0x0703
    MODE1 = 0x00
    MODE2 = 0x01
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.fd_map: dict[tuple[int, int], tuple[int, str]] = {}
        self.side_map: dict[str, tuple[int, int]] = {
            "yaw": (I2C_ADDR_YAW, I2C_CH_YAW),
            "pitch": (I2C_ADDR_PITCH, I2C_CH_PITCH),
        }
        self.ready = False

    @staticmethod
    def _pwm_count(pulse_us: int) -> int:
        pulse_us = clamp(pulse_us, SERVO_MIN, SERVO_MAX)
        return clamp(round(pulse_us * 4096 / 20000), 0, 4095)

    @staticmethod
    def _write_reg(fd: int, reg: int, value: int) -> None:
        os.write(fd, bytes([reg & 0xFF, value & 0xFF]))

    @staticmethod
    def _set_addr(fd: int, addr: int) -> None:
        fcntl.ioctl(fd, RawI2CPca9685Backend.I2C_SLAVE, addr)

    @staticmethod
    def _open_bus(bus: str) -> int:
        return os.open(bus, os.O_RDWR | os.O_CLOEXEC)

    def _init_chip(self, fd: int) -> None:
        self._write_reg(fd, self.MODE1, 0x10)
        self._write_reg(fd, self.PRESCALE, 121)
        self._write_reg(fd, self.MODE2, 0x04)
        self._write_reg(fd, self.MODE1, 0x00)
        time.sleep(0.005)
        self._write_reg(fd, self.MODE1, 0xA1)

    def _set_channel(self, fd: int, channel: int, pulse_us: int) -> None:
        on = 0
        off = self._pwm_count(pulse_us)
        base = self.LED0_ON_L + 4 * channel
        self._write_reg(fd, base + 0, on & 0xFF)
        self._write_reg(fd, base + 1, (on >> 8) & 0xFF)
        self._write_reg(fd, base + 2, off & 0xFF)
        self._write_reg(fd, base + 3, (off >> 8) & 0xFF)

    def connect(self) -> tuple[bool, str]:
        if self.ready and self.fd_map:
            return True, self._connection_detail()

        buses = sorted(glob.glob(I2C_BUS_GLOB))
        if not buses:
            return False, "no i2c bus found"

        addr_map: dict[int, tuple[int, str] | None] = {
            I2C_ADDR_YAW: None,
            I2C_ADDR_PITCH: None,
        }
        for bus in buses:
            for addr in list(addr_map):
                if addr_map[addr] is not None:
                    continue
                try:
                    fd = self._open_bus(bus)
                    try:
                        self._set_addr(fd, addr)
                        self._init_chip(fd)
                        addr_map[addr] = (fd, f"{bus}@0x{addr:02x}")
                    except Exception:
                        os.close(fd)
                except Exception:
                    continue
            if all(addr_map.values()):
                break

        if not all(addr_map.values()):
            for fd, _detail in [item for item in addr_map.values() if item]:
                try:
                    os.close(fd)
                except Exception:
                    pass
            return False, "i2c device not ready"

        self.fd_map = {}
        for addr, item in addr_map.items():
            if not item:
                continue
            fd, detail = item
            self.fd_map[(addr, 0)] = (fd, detail)
        self.ready = True
        return True, self._connection_detail()

    def _connection_detail(self) -> str:
        parts = []
        for side in ("yaw", "pitch"):
            addr, channel = self.side_map[side]
            detail = ""
            for (mapped_addr, _channel), (_fd, mapped_detail) in self.fd_map.items():
                if mapped_addr == addr:
                    detail = mapped_detail
                    break
            axis = "横向" if side == "yaw" else "纵向"
            parts.append(f"{axis}:{detail or f'0x{addr:02x}'}/ch{channel}")
        return ", ".join(parts)

    def set_pulse(self, side: str, pulse_us: int) -> tuple[bool, str]:
        ok, detail = self.connect()
        if not ok:
            return False, detail
        addr, channel = self.side_map["yaw" if side == "yaw" else "pitch"]
        try:
            fd = None
            target = ""
            for (mapped_addr, _channel), (mapped_fd, mapped_detail) in self.fd_map.items():
                if mapped_addr == addr:
                    fd = mapped_fd
                    target = mapped_detail
                    break
            if fd is None:
                raise KeyError(f"i2c addr 0x{addr:02x} not ready")
            with self.lock:
                self._set_channel(fd, channel, pulse_us)
            return True, f"{target}/ch{channel}"
        except Exception as exc:
            self.disconnect()
            return False, str(exc)

    def disconnect(self) -> None:
        for fd, _detail in self.fd_map.values():
            try:
                os.close(fd)
            except Exception:
                pass
        self.fd_map.clear()
        self.ready = False


class GimbalController:
    def __init__(self) -> None:
        self.state = GimbalState()
        self._step = STEP_DEFAULT
        self.i2c = RawI2CPca9685Backend()
        self.serial = SerialLobotBackend()
        self.pwm = SysfsPwmBackend()
        self._backend: str | None = None

    def _try_pwm(self) -> tuple[bool, str]:
        if BACKEND_PREF == "serial":
            return False, "serial preferred"
        return self.pwm.connect()

    def _try_i2c(self) -> tuple[bool, str]:
        if BACKEND_PREF == "serial":
            return False, "serial preferred"
        return self.i2c.connect()

    def _try_serial(self) -> tuple[bool, str]:
        if BACKEND_PREF == "pwm":
            return False, "pwm preferred"
        return self.serial.probe()

    def connect(self) -> bool:
        if self.state.connected:
            return True
        last_error = ""
        if BACKEND_PREF in ("auto", "pwm"):
            ok, detail = self._try_pwm()
            if ok:
                self._backend = "pwm"
                self.state.connected = True
                self.state.backend = "sysfs-pwm"
                self.state.target = detail
                self.state.last_error = ""
                return True
            last_error = detail
            if BACKEND_PREF == "pwm":
                self.state.last_error = last_error
                return False
        if BACKEND_PREF in ("auto", "i2c"):
            ok, detail = self._try_i2c()
            if ok:
                self._backend = "i2c"
                self.state.connected = True
                self.state.backend = "raw-i2c-pca9685"
                self.state.target = detail
                self.state.last_error = ""
                return True
            last_error = detail
            if BACKEND_PREF == "i2c":
                self.state.last_error = last_error
                return False
        if BACKEND_PREF in ("auto", "serial"):
            ok, detail = self._try_serial()
            if ok:
                self._backend = "serial"
                self.state.connected = True
                self.state.backend = f"serial-{SERIAL_PROTOCOL}"
                self.state.target = detail
                self.state.last_error = ""
                return True
            last_error = detail
        self.state.connected = False
        self.state.backend = ""
        self.state.target = ""
        self.state.last_error = last_error or "no backend available"
        return False

    def disconnect(self) -> None:
        self.serial.disconnect()
        self.pwm.disconnect()
        self.i2c.disconnect()
        self._backend = None
        self.state.connected = False
        self.state.backend = ""
        self.state.target = ""

    def _send(self, side: str, value: int, time_ms: int) -> tuple[bool, str]:
        if not self.connect():
            return False, self.state.last_error
        if self._backend == "i2c":
            return self.i2c.set_pulse(side, value)
        if self._backend == "pwm":
            return self.pwm.set_pulse(side, value)
        servo_id = YAW_SERVO_ID if side == "yaw" else PITCH_SERVO_ID
        return self.serial.send(servo_id, value, time_ms)

    def check_alive(self) -> bool:
        if not self.state.connected:
            return False
        if self._backend != "serial":
            return True
        ok, detail = self.serial.send(YAW_SERVO_ID, self.state.yaw, 80, log_action=False)
        if ok:
            self.state.last_error = ""
            return True
        self.state.last_error = detail
        self.disconnect()
        return False

    def move_yaw(self, delta: int) -> tuple[bool, str]:
        target = clamp(self.state.yaw + int(delta), SERVO_MIN, SERVO_MAX)
        ok, detail = self._send("yaw", target, MOVE_TIME_MS)
        if ok:
            self.state.yaw = target
            self.state.last_command = f"yaw={target}"
            return True, detail
        self.state.last_error = detail
        return False, detail

    def move_pitch(self, delta: int) -> tuple[bool, str]:
        target = clamp(self.state.pitch + int(delta), SERVO_MIN, SERVO_MAX)
        ok, detail = self._send("pitch", target, MOVE_TIME_MS)
        if ok:
            self.state.pitch = target
            self.state.last_command = f"pitch={target}"
            return True, detail
        self.state.last_error = detail
        return False, detail

    def center(self) -> tuple[bool, str]:
        ok1, detail1 = self._send("yaw", SERVO_CENTER, MOVE_TIME_MS)
        ok2, detail2 = self._send("pitch", SERVO_CENTER, MOVE_TIME_MS)
        if ok1:
            self.state.yaw = SERVO_CENTER
        if ok2:
            self.state.pitch = SERVO_CENTER
        if ok1 and ok2:
            self.state.last_command = "center"
            return True, self.state.target
        detail = detail1 if not ok1 else detail2
        self.state.last_error = detail
        return False, detail

    def set_step(self, step: int) -> None:
        self._step = clamp(step, 1, 500)

    def step(self) -> int:
        return self._step


class GimbalApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("云台控制")
        self.root.geometry("1080x680")
        self.root.minsize(900, 580)
        self.root.configure(bg="#0d1114")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.controller = GimbalController()
        self.running = True
        self._next_link_check = time.monotonic() + 1.0
        self.log_lines: list[tuple[str, str, str]] = []
        self.step_var = tk.StringVar(value=str(self.controller.step()))
        self.serial_text = tk.StringVar(value="未连接")
        self.pose_text = tk.StringVar(value="等待")
        self.command_text = tk.StringVar(value="-")
        self.error_text = tk.StringVar(value="")
        self.yaw_text = tk.StringVar(value=str(SERVO_CENTER))
        self.pitch_text = tk.StringVar(value=str(SERVO_CENTER))
        self.backend_text = tk.StringVar(value="auto")
        self._build_ui()
        self.root.after(120, self._refresh_ui)

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#171d22", height=56)
        top.pack(side=tk.TOP, fill=tk.X)
        top.pack_propagate(False)
        tk.Label(
            top,
            text="云台控制",
            bg="#171d22",
            fg="#f2f5f2",
            font=("Microsoft YaHei", 16, "bold"),
        ).pack(side=tk.LEFT, padx=(16, 16))
        tk.Label(
            top,
            text="两轴微调 · 自动识别控制后端 · 独立云台软件",
            bg="#171d22",
            fg="#9aa7a1",
            font=("Microsoft YaHei", 10),
        ).pack(side=tk.LEFT)
        tk.Button(
            top,
            text="连接设备",
            command=self.toggle_serial,
            bg="#1f272d",
            fg="#f2f5f2",
            activebackground="#2c3640",
            activeforeground="#3fd47d",
            relief="flat",
            padx=14,
            pady=6,
        ).pack(side=tk.RIGHT, padx=10, pady=10)
        tk.Button(
            top,
            text="回中",
            command=self.center,
            bg="#1f272d",
            fg="#f2f5f2",
            activebackground="#2c3640",
            activeforeground="#3fd47d",
            relief="flat",
            padx=14,
            pady=6,
        ).pack(side=tk.RIGHT, padx=(0, 10), pady=10)

        body = tk.Frame(self.root, bg="#0d1114")
        body.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(body, bg="#0d1114")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 8), pady=12)
        right = tk.Frame(body, bg="#0d1114", width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=12)
        right.pack_propagate(False)

        tiles = tk.Frame(left, bg="#0d1114")
        tiles.pack(fill=tk.X)
        self._tile(tiles, "连接状态", self.serial_text, 0)
        self._tile(tiles, "当前横向", self.yaw_text, 1)
        self._tile(tiles, "当前纵向", self.pitch_text, 2)

        panel = tk.Frame(left, bg="#171d22", bd=0, highlightthickness=1, highlightbackground="#2f3a42")
        panel.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        tk.Label(
            panel,
            text="微调控制",
            bg="#171d22",
            fg="#f2f5f2",
            font=("Microsoft YaHei", 13, "bold"),
        ).pack(anchor="w", padx=16, pady=(16, 6))
        tk.Label(
            panel,
            text="每次只挪一点点，适合把云台慢慢拨到位。",
            bg="#171d22",
            fg="#9aa7a1",
            font=("Microsoft YaHei", 10),
        ).pack(anchor="w", padx=16, pady=(0, 12))

        grid = tk.Frame(panel, bg="#171d22")
        grid.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 14))

        self._control_button(grid, "左微调", lambda: self._step_yaw(-self.controller.step()), 0, 0, "#1f272d")
        self._control_button(grid, "右微调", lambda: self._step_yaw(self.controller.step()), 0, 1, "#1f272d")
        self._control_button(grid, "上微调", lambda: self._step_pitch(-self.controller.step()), 1, 0, "#1f272d")
        self._control_button(grid, "下微调", lambda: self._step_pitch(self.controller.step()), 1, 1, "#1f272d")

        control_row = tk.Frame(panel, bg="#171d22")
        control_row.pack(fill=tk.X, padx=16, pady=(0, 16))
        tk.Label(control_row, text="步长", bg="#171d22", fg="#9aa7a1", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        step_entry = tk.Entry(control_row, textvariable=self.step_var, width=6, justify="center")
        step_entry.pack(side=tk.LEFT, padx=8)
        tk.Button(
            control_row,
            text="应用",
            command=self.apply_step,
            bg="#1f272d",
            fg="#f2f5f2",
            relief="flat",
            padx=12,
        ).pack(side=tk.LEFT)

        log_panel = tk.Frame(left, bg="#171d22", bd=0, highlightthickness=1, highlightbackground="#2f3a42")
        log_panel.pack(fill=tk.BOTH, expand=False, pady=(12, 0))
        tk.Label(
            log_panel,
            text="操作记录",
            bg="#171d22",
            fg="#f2f5f2",
            font=("Microsoft YaHei", 13, "bold"),
        ).pack(anchor="w", padx=16, pady=(16, 8))
        self.log_box = tk.Listbox(
            log_panel,
            height=9,
            bg="#0f1317",
            fg="#dce7f3",
            selectbackground="#2c3640",
            highlightthickness=0,
            relief="flat",
            font=("Microsoft YaHei", 10),
        )
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

        side_panel = tk.Frame(right, bg="#171d22", bd=0, highlightthickness=1, highlightbackground="#2f3a42")
        side_panel.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            side_panel,
            text="状态",
            bg="#171d22",
            fg="#f2f5f2",
            font=("Microsoft YaHei", 13, "bold"),
        ).pack(anchor="w", padx=16, pady=(16, 10))
        tk.Label(
            side_panel,
            textvariable=self.backend_text,
            bg="#0f1317",
            fg="#9fd1ff",
            font=("Microsoft YaHei", 12, "bold"),
            width=18,
            anchor="w",
            padx=10,
            pady=8,
        ).pack(fill=tk.X, padx=16, pady=(0, 10))
        tk.Label(
            side_panel,
            textvariable=self.pose_text,
            bg="#0f1317",
            fg="#dce7f3",
            font=("Microsoft YaHei", 14, "bold"),
            width=18,
            anchor="w",
            padx=10,
            pady=8,
        ).pack(fill=tk.X, padx=16, pady=(0, 10))
        tk.Label(
            side_panel,
            textvariable=self.command_text,
            bg="#0f1317",
            fg="#3fd47d",
            font=("Consolas", 11),
            anchor="w",
            padx=10,
            pady=8,
        ).pack(fill=tk.X, padx=16, pady=(0, 10))
        tk.Label(
            side_panel,
            textvariable=self.error_text,
            bg="#0f1317",
            fg="#ff5b66",
            font=("Microsoft YaHei", 10),
            wraplength=250,
            justify="left",
            anchor="nw",
            padx=10,
            pady=8,
            height=5,
        ).pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

    def _tile(self, parent: tk.Widget, title: str, variable: tk.StringVar, column: int) -> None:
        tile = tk.Frame(parent, bg="#171d22", bd=0, highlightthickness=1, highlightbackground="#2f3a42")
        tile.grid(row=0, column=column, sticky="nsew", padx=4)
        parent.grid_columnconfigure(column, weight=1)
        tk.Label(tile, text=title, bg="#171d22", fg="#9aa7a1", font=("Microsoft YaHei", 10)).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(tile, textvariable=variable, bg="#171d22", fg="#f2f5f2", font=("Microsoft YaHei", 18, "bold")).pack(anchor="w", padx=12, pady=(0, 12))

    def _control_button(self, parent: tk.Widget, text: str, command, row: int, column: int, bg: str) -> None:
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg="#f2f5f2",
            activebackground="#2c3640",
            activeforeground="#3fd47d",
            relief="flat",
            font=("Microsoft YaHei", 13, "bold"),
            height=2,
        )
        btn.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        parent.grid_rowconfigure(row, weight=1)
        parent.grid_columnconfigure(column, weight=1)

    def _log(self, text: str, kind: str = "") -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_lines.insert(0, (stamp, text, kind))
        self.log_lines = self.log_lines[:20]
        self.log_box.delete(0, tk.END)
        for _, line, _kind in self.log_lines:
            self.log_box.insert(tk.END, line)
        self.log_box.yview_moveto(0)

    def apply_step(self) -> None:
        try:
            self.controller.set_step(int(self.step_var.get()))
        except ValueError:
            self.step_var.set(str(self.controller.step()))
            self._log("步长不是数字", "err")
            return
        self.step_var.set(str(self.controller.step()))
        self._log(f"步长已设为 {self.controller.step()}")

    def toggle_serial(self) -> None:
        if self.controller.state.connected:
            self.controller.disconnect()
            self.serial_text.set("未连接")
            self.backend_text.set("auto")
            self._log("设备已断开")
            return
        ok = self.controller.connect()
        self.serial_text.set(self.controller.state.target if ok else "未连接")
        self.backend_text.set(self.controller.state.backend or "auto")
        self.error_text.set(self.controller.state.last_error)
        self._log(
            f"连接{'成功' if ok else '失败'}: {self.controller.state.backend or self.controller.state.last_error}",
            "ok" if ok else "err",
        )

    def _step_yaw(self, delta: int) -> None:
        ok, detail = self.controller.move_yaw(delta)
        self._sync_state()
        self._log(f"横向微调 {delta:+d}" if ok else f"横向微调失败: {detail}", "ok" if ok else "err")

    def _step_pitch(self, delta: int) -> None:
        ok, detail = self.controller.move_pitch(delta)
        self._sync_state()
        self._log(f"纵向微调 {delta:+d}" if ok else f"纵向微调失败: {detail}", "ok" if ok else "err")

    def center(self) -> None:
        ok, detail = self.controller.center()
        self._sync_state()
        self._log("回到中位" if ok else f"回中失败: {detail}", "ok" if ok else "err")

    def _sync_state(self) -> None:
        self.serial_text.set(self.controller.state.target if self.controller.state.connected else "未连接")
        self.backend_text.set(self.controller.state.backend or "auto")
        self.yaw_text.set(str(self.controller.state.yaw))
        self.pitch_text.set(str(self.controller.state.pitch))
        self.command_text.set(self.controller.state.last_command or "-")
        self.error_text.set(self.controller.state.last_error or "")
        self.pose_text.set("已连接" if self.controller.state.connected else "待机")

    def _refresh_ui(self) -> None:
        now = time.monotonic()
        if self.controller.state.connected and now >= self._next_link_check:
            if not self.controller.check_alive():
                self._log(f"连接断开: {self.controller.state.last_error}", "err")
            self._next_link_check = now + 1.0
        self._sync_state()
        if self.running:
            self.root.after(150, self._refresh_ui)

    def close(self) -> None:
        self.running = False
        self.controller.disconnect()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    GimbalApp().run()
