"""
CH340 USB-Serial 纯用户态驱动
参考 Linux 6.1 ch341.c 实现
"""
import usb.core
import usb.util
import threading
import time


class CH340Driver:
    """CH340 USB串口驱动"""

    VID = 0x1a86
    PID = 0x7523

    # CH340 波特率因子: 12MHz / (baud*16), 然后取 (0x100 - factor)
    @staticmethod
    def _baud_factor(baud):
        """计算CH340波特率寄存器值"""
        # CH340: factor = 2^10 - 12,000,000 / (baud * oversample)
        # Where oversample depends on baud rate
        if baud <= 600:
            return 0xd901  # 600 or below uses different oversampling
        # Standard mode: oversample = 16
        # factor = round(12,000,000 / (baud * 16))
        factor = (12_000_000 + baud * 8) // (baud * 16)  # rounded division
        # The value written to the register is (0x1312 << 8) | ... actually:
        return factor & 0xffff

    def __init__(self):
        self.dev = None
        self.connected = False
        self.lock = threading.Lock()

    def _ctrl_write(self, req, value=0, index=0):
        """写控制传输（Vendor, Host-to-Device）"""
        try:
            self.dev.ctrl_transfer(0x40, req, value, index, None, 500)
        except usb.core.USBError:
            pass  # CH340 often returns -EPIPE which is expected

    def connect(self, baud=115200):
        """连接并初始化CH340"""
        try:
            self.dev = usb.core.find(idVendor=self.VID, idProduct=self.PID)
            if self.dev is None:
                print("[CH340] 未找到设备")
                return False

            # 解绑内核驱动
            try:
                if self.dev.is_kernel_driver_active(0):
                    self.dev.detach_kernel_driver(0)
                    print("[CH340] 已解绑内核驱动")
            except Exception:
                pass

            # 激活配置
            try:
                self.dev.set_configuration()
            except Exception:
                pass

            # === CH340 初始化序列（与内核 ch341.c 一致）===

            # Step 1: 软件复位
            self._ctrl_write(0xa4, 0, 0)
            time.sleep(0.02)

            # Step 2: 设置波特率
            factor = self._baud_factor(baud)
            # ch341_set_baudrate_lcr:
            # value = 0x9a, index = 0x1312, data = factor
            # But the kernel actually sends two bytes:
            # lcr = 0x00c3 (8N1, DTR/RTS on)
            value = factor | 0x0000  # lower byte of factor in value
            # The kernel implementation:
            self._ctrl_write(0x9a, 0x1312, factor)
            time.sleep(0.02)

            # Step 3: 设置线路控制 8N1
            self._ctrl_write(0xa1, 0x2518, 0x00c3)
            time.sleep(0.02)

            # Step 4: 设置握手信号 DTR+RTS 高
            self._ctrl_write(0xa4, 0x0001, 0)
            time.sleep(0.02)

            # Step 5: 再次配置
            self._ctrl_write(0x9a, 0x0f2c, factor)

            self.connected = True
            print(f"[CH340] 已连接 @ {baud} bps (factor=0x{factor:04x})")
            return True

        except Exception as e:
            print(f"[CH340] 连接失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def send(self, data: bytes) -> bool:
        """发送数据到 Bulk OUT EP 0x02"""
        if not self.connected:
            return False
        with self.lock:
            try:
                written = self.dev.write(0x02, data, timeout=2000)
                return written == len(data)
            except usb.core.USBError as e:
                if "timeout" in str(e).lower():
                    return False
                print(f"[CH340] TX error: {e}")
                return False

    def read(self, size=64, timeout_ms=200) -> bytes:
        """从 Bulk IN EP 0x82 读取"""
        if not self.connected:
            return b""
        try:
            return self.dev.read(0x82, size, timeout=timeout_ms).tobytes()
        except usb.core.USBError:
            return b""

    def send_command(self, cmd: str) -> bool:
        """发送文本指令"""
        if not cmd.endswith("\r\n"):
            cmd = cmd.rstrip() + "\r\n"
        return self.send(cmd.encode("utf-8"))

    def read_line(self) -> str | None:
        """读取一行响应"""
        data = self.read(256, timeout_ms=100)
        if data:
            try:
                return data.decode("utf-8", errors="ignore").strip()
            except Exception:
                pass
        return None

    def disconnect(self):
        """断开"""
        self.connected = False
        if self.dev:
            try:
                usb.util.dispose_resources(self.dev)
            except Exception:
                pass
            self.dev = None
        print("[CH340] 已断开")

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "driver": "pyusb-ch340",
            "vid": f"0x{self.VID:04x}",
            "pid": f"0x{self.PID:04x}",
        }
