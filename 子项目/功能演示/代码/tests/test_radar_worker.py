import queue
import threading
import time

from feature_demo.radar.detection import DetectionRegion
from feature_demo.radar.protocol import ScanPoint
from feature_demo.radar.device import discover_radar_ports
from feature_demo.workers.radar import RadarWorker


class FakeDevice:
    def __init__(self, frames=()):
        self.frames = list(frames)
        self.closed = False
        self._bytes_received = 0
        self._valid_points = 0
        self._complete_rotations = 0
        self._last_frame_size = 0
        self._last_frame_timestamp = 0.0

    def open(self):
        return True

    def iter_scans(self, stop_event):
        while not stop_event.is_set():
            for frame in self.frames:
                if stop_event.is_set():
                    return
                self._record(frame)
                yield frame
                time.sleep(0.001)

    def close(self):
        self.closed = True

    @property
    def diagnostics(self):
        return {
            "descriptor_valid": True,
            "bytes_received": self._bytes_received,
            "valid_points": self._valid_points,
            "complete_rotations": self._complete_rotations,
            "last_frame_size": self._last_frame_size,
            "last_frame_timestamp": self._last_frame_timestamp,
        }

    def _record(self, frame):
        self._bytes_received += len(frame) * 5
        self._valid_points += len(frame)
        self._complete_rotations += 1
        self._last_frame_size = len(frame)
        self._last_frame_timestamp = time.monotonic()


class ControlledDevice(FakeDevice):
    def __init__(self):
        super().__init__()
        self.pending = queue.Queue()

    def push(self, frame, count=1):
        for _ in range(count):
            self.pending.put(frame)

    def iter_scans(self, stop_event):
        while not stop_event.is_set():
            try:
                frame = self.pending.get(timeout=0.01)
            except queue.Empty:
                continue
            self._record(frame)
            yield frame


class FailingDevice(FakeDevice):
    def iter_scans(self, stop_event):
        raise OSError("serial disconnected")


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not met before timeout")


def test_discovery_prefers_stable_serial_ids(monkeypatch):
    monkeypatch.setattr(
        "feature_demo.radar.device.glob.glob",
        lambda pattern: {
            "/dev/serial/by-id/*": ["/dev/serial/by-id/radar"],
            "/dev/ttyUSB*": ["/dev/ttyUSB1"],
            "/dev/ttyACM*": ["/dev/ttyACM0"],
        }[pattern],
    )

    assert discover_radar_ports() == ("/dev/serial/by-id/radar",)


def test_discovery_does_not_probe_known_robot_or_gimbal_serials(monkeypatch):
    monkeypatch.setattr(
        "feature_demo.radar.device.glob.glob",
        lambda pattern: {
            "/dev/serial/by-id/*": [
                "/dev/serial/by-id/usb-WCH.CN_USB_Single_Serial_0004-if00",
                "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00",
                "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0",
            ],
            "/dev/ttyUSB*": [],
            "/dev/ttyACM*": [],
        }[pattern],
    )

    assert discover_radar_ports() == (
        "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0",
    )


def test_worker_starts_without_radar_and_reports_disconnected():
    events = []
    worker = RadarWorker(device_factory=lambda: None, event_sink=events.append)

    worker.start()

    assert events[-1] == {"type": "ready", "connected": False, "message": "雷达未连接"}
    worker.stop()


def test_worker_reports_disconnected_when_serial_read_fails():
    events = []
    worker = RadarWorker(device_factory=FailingDevice, event_sink=events.append)

    worker.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and not any(event.get("type") == "error" for event in events):
        time.sleep(0.01)
    worker.stop()

    assert any(
        event.get("type") == "error" and event.get("connected") is False
        for event in events
    )


def test_worker_reports_ready_only_after_five_valid_rotations():
    events = []
    frame = tuple(ScanPoint(float(angle), 1000.0, 15) for angle in range(260, 281))
    device = FakeDevice([frame])
    worker = RadarWorker(
        device_factory=lambda: device,
        event_sink=events.append,
        minimum_frame_points=1,
        readiness_frames=5,
        sample_period_s=0.001,
    )

    worker.start()
    wait_until(lambda: any(event.get("valid_rotations", 0) >= 5 for event in events))
    worker.stop()

    scans = [event for event in events if event.get("type") == "scan"]
    assert any(event["valid_rotations"] < 5 and event["data_ready"] is False for event in scans)
    assert any(event["valid_rotations"] >= 5 and event["data_ready"] is True for event in scans)
    assert all(event["required_rotations"] == 5 for event in scans)
    assert all(
        key in scans[-1]
        for key in (
            "bytes_per_second",
            "points_per_second",
            "rotations_per_second",
            "last_rotation_points",
            "last_rotation_age_ms",
        )
    )
    assert scans[-1]["last_rotation_points"] == len(frame)


def test_worker_excludes_undersized_rotations_from_readiness():
    events = []
    device = ControlledDevice()
    worker = RadarWorker(
        device_factory=lambda: device,
        event_sink=events.append,
        minimum_frame_points=2,
        readiness_frames=5,
        sample_period_s=0,
    )
    short_frame = (ScanPoint(270, 1000, 15),)
    valid_frame = (ScanPoint(270, 1000, 15), ScanPoint(271, 1000, 15))

    worker.start()
    device.push(short_frame, count=5)
    wait_until(lambda: device.diagnostics["complete_rotations"] == 5)
    device.push(valid_frame, count=5)
    wait_until(lambda: any(event.get("data_ready") is True for event in events))
    worker.stop()

    scans = [event for event in events if event.get("type") == "scan"]
    assert scans[-1]["valid_rotations"] == 5
    assert len(scans) == 5


def test_build_baseline_rejects_disconnected_and_not_ready_states():
    disconnected = RadarWorker(device_factory=lambda: None, event_sink=lambda _event: None)
    disconnected.start()

    assert disconnected.command("build_baseline", {})["error"] == "disconnected"

    device = ControlledDevice()
    worker = RadarWorker(
        device_factory=lambda: device,
        event_sink=lambda _event: None,
        minimum_frame_points=1,
        readiness_frames=5,
    )
    worker.start()
    device.push((ScanPoint(270, 1000, 15),), count=4)
    wait_until(lambda: device.diagnostics["complete_rotations"] == 4)
    result = worker.command("build_baseline", {})
    worker.stop()

    assert result["ok"] is False
    assert result["error"] == "not_ready"
    assert result["valid_rotations"] == 4
    assert result["required_rotations"] == 5


def test_build_baseline_waits_for_twelve_rotations_and_uses_newest_frames():
    events = []
    device = ControlledDevice()
    worker = RadarWorker(
        device_factory=lambda: device,
        event_sink=events.append,
        region=DetectionRegion(260, 280, 500, 1500),
        baseline_frames=12,
        readiness_frames=5,
        minimum_frame_points=1,
        sample_period_s=0.001,
    )
    outside_region = (ScanPoint(10, 1000, 15),)
    inside_region = (ScanPoint(270, 1000, 15),)

    worker.start()
    device.push(outside_region)
    device.push(inside_region, count=4)
    wait_until(lambda: any(event.get("data_ready") is True for event in events))
    result = {}

    def build():
        result.update(worker.command("build_baseline", {}))

    command_thread = threading.Thread(target=build)
    command_thread.start()
    time.sleep(0.02)
    assert command_thread.is_alive()

    device.push(inside_region, count=8)
    command_thread.join(timeout=1)
    worker.stop()

    assert command_thread.is_alive() is False
    assert result["ok"] is True
    assert result["frames"] == 12


def test_stop_wakes_a_baseline_command_waiting_for_more_rotations():
    events = []
    device = ControlledDevice()
    worker = RadarWorker(
        device_factory=lambda: device,
        event_sink=events.append,
        baseline_frames=12,
        readiness_frames=5,
        minimum_frame_points=1,
        sample_period_s=0,
    )
    frame = (ScanPoint(270, 1000, 15),)
    result = {}

    worker.start()
    device.push(frame, count=5)
    wait_until(lambda: any(event.get("data_ready") is True for event in events))
    command_thread = threading.Thread(
        target=lambda: result.update(worker.command("build_baseline", {})),
        daemon=True,
    )
    command_thread.start()
    wait_until(command_thread.is_alive)

    worker.stop()
    command_thread.join(timeout=0.2)

    assert command_thread.is_alive() is False
    assert result["error"] == "disconnected"


def test_build_baseline_reports_empty_detection_region():
    events = []
    device = ControlledDevice()
    worker = RadarWorker(
        device_factory=lambda: device,
        event_sink=events.append,
        region=DetectionRegion(260, 280, 500, 1500),
        baseline_frames=5,
        readiness_frames=5,
        minimum_frame_points=1,
        sample_period_s=0.001,
    )

    worker.start()
    device.push((ScanPoint(10, 1000, 15),), count=5)
    wait_until(lambda: any(event.get("data_ready") is True for event in events))
    result = worker.command("build_baseline", {})
    worker.stop()

    assert result["ok"] is False
    assert result["error"] == "region_empty"


def test_invalid_region_frame_does_not_advance_confirmation():
    events = []
    device = ControlledDevice()
    worker = RadarWorker(
        device_factory=lambda: device,
        event_sink=events.append,
        region=DetectionRegion(260, 280, 500, 1500),
        baseline_frames=5,
        readiness_frames=5,
        minimum_frame_points=1,
        confirmation_frames=3,
        sample_period_s=0,
    )
    baseline = (ScanPoint(270, 1000, 15),)
    changed = (ScanPoint(270, 1500, 15),)
    outside_region = (ScanPoint(10, 1000, 15),)

    worker.start()
    try:
        device.push(baseline, count=5)
        wait_until(lambda: any(event.get("data_ready") is True for event in events))
        assert worker.command("build_baseline", {})["ok"] is True
        assert worker.command("start_detection", {})["ok"] is True

        device.push(changed)
        wait_until(
            lambda: any(
                event.get("type") == "detection"
                and event.get("radar_data_valid") is True
                and event.get("confirmation") == 1
                for event in events
            )
        )
        device.push(outside_region)
        wait_until(
            lambda: any(
                event.get("type") == "detection"
                and event.get("radar_data_valid") is False
                for event in events
            )
        )
        invalid_event = next(
            event
            for event in reversed(events)
            if event.get("type") == "detection"
            and event.get("radar_data_valid") is False
        )
        assert invalid_event["confirmation"] == 1

        device.push(changed, count=2)
        wait_until(lambda: any(event.get("result") == "有物块" for event in events))
    finally:
        worker.stop()


def test_worker_builds_baseline_detects_object_and_stops_reader():
    events = []
    empty = (ScanPoint(270, 1000, 15),)
    occupied = (ScanPoint(270, 1500, 15),)
    device = FakeDevice([empty])
    worker = RadarWorker(
        device_factory=lambda: device,
        event_sink=events.append,
        region=DetectionRegion(260, 280, 500, 1500),
        baseline_frames=3,
        readiness_frames=3,
        minimum_frame_points=1,
        confirmation_frames=3,
        sample_period_s=0.001,
    )

    worker.start()
    try:
        wait_until(lambda: any(event.get("data_ready") is True for event in events))
        assert worker.command("build_baseline", {})["ok"] is True
        device.frames = [occupied]
        assert worker.command("start_detection", {})["ok"] is True
        wait_until(lambda: any(event.get("result") == "有物块" for event in events))
    finally:
        worker.stop()

    assert any(event.get("result") == "有物块" for event in events)
    assert device.closed is True
    assert worker.reader_alive is False
