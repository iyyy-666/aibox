"""
串口驱动 - 本地 pyserial 模式（generic usbserial 驱动）
"""
import serial
import threading
from config import SERIAL_PORT, SERIAL_BAUD

class SerialDriver:

    def __init__(self):
        self.ser = None
        self.lock = threading.Lock()
        self.connected = False
        self._last_cmd = ""
        self._port = SERIAL_PORT
        self._baud = SERIAL_BAUD

    def connect(self, port=SERIAL_PORT, baud=SERIAL_BAUD):
        try:
            self._port = port
            self._baud = baud
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.ser = serial.Serial(port, baud, timeout=0.1)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            self.connected = True
            print(f"[串口] 已连接 {port} @ {baud}bps (pyserial)")
            return True
        except Exception as e:
            print(f"[串口] 连接失败: {e}")
            self.connected = False
            return False

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.connected = False
        print("[串口] 已断开")

    def send_command(self, cmd: str) -> bool:
        if not self.connected or not self.ser or not self.ser.is_open:
            print("[串口] 未连接")
            if not self.connect(self._port, self._baud):
                return False
        if not cmd.endswith("\r\n"):
            cmd = cmd.rstrip() + "\r\n"
        with self.lock:
            return self._send_locked(cmd, retry=True)

    def _send_locked(self, cmd: str, retry: bool = True) -> bool:
        try:
            self.ser.write(cmd.encode("utf-8"))
            self.ser.flush()
            self._last_cmd = cmd.strip()
            return True
        except Exception as e:
            print(f"[串口] 发送失败: {e}")
            self.connected = False
            try:
                if self.ser and self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
            if not retry:
                return False
            print("[串口] 尝试自动重连后重发")
            if not self.connect(self._port, self._baud):
                return False
            return self._send_locked(cmd, retry=False)

    def read_line(self) -> str | None:
        if not self.connected or not self.ser:
            return None
        try:
            if self.ser.in_waiting > 0:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    return line
        except Exception:
            pass
        return None

    def read_all(self) -> str:
        if not self.connected or not self.ser:
            return ""
        try:
            if self.ser.in_waiting > 0:
                return self.ser.read(self.ser.in_waiting).decode("utf-8", errors="ignore")
        except Exception:
            pass
        return ""

    @property
    def last_command(self) -> str:
        return self._last_cmd

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "port": SERIAL_PORT,
            "baud": SERIAL_BAUD,
            "last_command": self._last_cmd,
            "method": "pyserial-local",
        }
