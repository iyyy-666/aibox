from __future__ import annotations

import glob
import time
from threading import Event
from typing import Iterator

from .protocol import A1ScanStreamParser, ScanPoint


SCAN_DESCRIPTOR = bytes.fromhex("a55a0500004081")


class RadarProtocolError(RuntimeError):
    pass


EXCLUDED_SERIAL_MARKERS = (
    "usb-WCH.CN_USB_Single_Serial_0004",
    "usb-1a86_USB_Single_Serial_5C67040336",
    "usb-1a86_USB_Serial",
)


def discover_radar_ports() -> tuple[str, ...]:
    patterns = ("/dev/serial/by-id/*", "/dev/ttyUSB*", "/dev/ttyACM*")
    result: list[str] = []
    stable = [
        path
        for path in sorted(glob.glob(patterns[0]))
        if not any(marker in path for marker in EXCLUDED_SERIAL_MARKERS)
    ]
    for path in stable:
        if path not in result:
            result.append(path)
    for pattern in patterns[1:]:
        for path in sorted(glob.glob(pattern)):
            if pattern == "/dev/ttyACM*":
                continue
            if stable:
                continue
            if path not in result:
                result.append(path)
    return tuple(result)


class A1M8Device:
    def __init__(
        self,
        ports: tuple[str, ...] | None = None,
        *,
        serial_factory=None,
        motor_start_delay_s: float = 1.0,
        descriptor_timeout_s: float = 1.0,
    ) -> None:
        self.ports = ports or discover_radar_ports()
        self._serial_factory = serial_factory
        self._serial = None
        self.port: str | None = None
        self._motor_start_delay_s = max(0.0, float(motor_start_delay_s))
        self._descriptor_timeout_s = max(0.0, float(descriptor_timeout_s))
        self._descriptor_valid = False
        self._bytes_received = 0
        self._structural_points = 0
        self._valid_points = 0
        self._complete_rotations = 0
        self._last_frame_size = 0
        self._last_frame_positive_points = 0
        self._last_frame_timestamp = 0.0

    @property
    def diagnostics(self) -> dict:
        return {
            "descriptor_valid": self._descriptor_valid,
            "bytes_received": self._bytes_received,
            "structural_points": self._structural_points,
            "valid_points": self._valid_points,
            "complete_rotations": self._complete_rotations,
            "last_frame_size": self._last_frame_size,
            "last_frame_positive_points": self._last_frame_positive_points,
            "last_frame_timestamp": self._last_frame_timestamp,
        }

    def open(self) -> bool:
        self._descriptor_valid = False
        if self._serial_factory is not None:
            factory = self._serial_factory
        else:
            try:
                import serial
            except ImportError:
                return False
            factory = serial.Serial
        for port in self.ports:
            candidate = None
            try:
                candidate = factory(
                    None,
                    115200,
                    timeout=0.25,
                    rtscts=False,
                    dsrdtr=False,
                )
                candidate.rtscts = False
                candidate.dsrdtr = False
                candidate.dtr = False
                candidate.rts = False
                candidate.port = port
                candidate.open()
                reset_input_buffer = getattr(candidate, "reset_input_buffer", None)
                if callable(reset_input_buffer):
                    reset_input_buffer()
                if self._motor_start_delay_s:
                    time.sleep(self._motor_start_delay_s)
                candidate.write(bytes.fromhex("a520"))
                candidate.flush()
                self._serial = candidate
                self.port = port
                return True
            except Exception:
                try:
                    candidate.close()
                except Exception:
                    pass
        return False

    def _read_exact(self, size: int, stop_event: Event) -> bytes:
        serial_port = self._serial
        if serial_port is None:
            return b""
        data = bytearray()
        deadline = time.monotonic() + self._descriptor_timeout_s
        while (
            len(data) < size
            and not stop_event.is_set()
            and time.monotonic() < deadline
        ):
            chunk = serial_port.read(size - len(data))
            if not chunk:
                continue
            self._bytes_received += len(chunk)
            data.extend(chunk)
        return bytes(data)

    def iter_scans(self, stop_event: Event) -> Iterator[tuple[ScanPoint, ...]]:
        serial_port = self._serial
        if serial_port is None:
            return
        self._descriptor_valid = False
        descriptor = self._read_exact(len(SCAN_DESCRIPTOR), stop_event)
        if not descriptor:
            raise RadarProtocolError("未收到扫描响应描述头")
        if descriptor != SCAN_DESCRIPTOR:
            raise RadarProtocolError("扫描响应描述头无效")
        self._descriptor_valid = True

        parser = A1ScanStreamParser()
        scan: list[ScanPoint] = []
        synchronized = False
        while not stop_event.is_set():
            chunk = serial_port.read(125)
            if not chunk:
                continue
            self._bytes_received += len(chunk)
            points = parser.feed(chunk)
            self._structural_points += len(points)
            self._valid_points += sum(point.distance_mm > 0 for point in points)
            for point in points:
                if point.scan_start:
                    if synchronized and scan:
                        frame = tuple(scan)
                        scan = [point]
                        self._complete_rotations += 1
                        self._last_frame_size = len(frame)
                        self._last_frame_positive_points = sum(
                            point.distance_mm > 0 for point in frame
                        )
                        self._last_frame_timestamp = time.monotonic()
                        yield frame
                    else:
                        synchronized = True
                        scan = [point]
                elif synchronized:
                    scan.append(point)

    def close(self) -> None:
        serial_port = self._serial
        self._serial = None
        if serial_port is None:
            return
        try:
            serial_port.write(bytes.fromhex("a525"))
            serial_port.flush()
        except Exception:
            pass
        try:
            serial_port.close()
        finally:
            self.port = None
