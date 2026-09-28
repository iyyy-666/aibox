import threading
import time

import pytest

from feature_demo.radar.detection import (
    BaselineComparator,
    ConfirmationState,
    DetectionRegion,
)
from feature_demo.radar.protocol import (
    A1ScanStreamParser,
    ScanPoint,
    parse_scan_node,
    parse_scan_nodes,
)
from feature_demo.radar.device import A1M8Device, RadarProtocolError


def node(angle: float, distance: int, quality: int = 15, *, start: bool = False) -> bytes:
    angle_raw = int(round(angle * 64)) << 1
    flags = 1 if start else 2
    return bytes((quality << 2 | flags, angle_raw & 0xFF | 1, (angle_raw >> 8) & 0xFF, distance * 4 & 0xFF, distance * 4 >> 8))


def test_parse_scan_nodes_decodes_angle_and_distance():
    points = parse_scan_nodes(node(270.0, 1000))

    assert points == (ScanPoint(angle_deg=270.0, distance_mm=1000.0, quality=15),)


def test_parse_scan_nodes_preserves_scan_start_and_rejects_bad_flags():
    points = parse_scan_nodes(node(1.0, 500, start=True) + bytes.fromhex("3c000000d0"))

    assert points[0].scan_start is True
    assert len(points) == 1


def test_stream_parser_handles_split_nodes_and_recovers_alignment():
    parser = A1ScanStreamParser()
    first = node(10.0, 500, start=True)
    second = node(20.0, 700)

    assert parser.feed(b"\xff" + first[:3]) == ()
    points = parser.feed(first[3:] + second)

    assert [(p.angle_deg, p.distance_mm) for p in points] == [(10.0, 500.0), (20.0, 700.0)]


def test_stream_parser_discards_one_bad_byte_then_finds_next_node():
    parser = A1ScanStreamParser()

    points = parser.feed(node(30.0, 600) + b"\x00" + node(40.0, 800))

    assert [point.angle_deg for point in points] == [30.0, 40.0]


def test_stream_parser_consumes_zero_distance_nodes_and_preserves_rotation_starts():
    parser = A1ScanStreamParser()
    records = []
    for rotation in range(10):
        records.extend(
            (
                node(float(rotation), 0, start=True),
                node(10.0 + rotation, 800),
                node(20.0 + rotation, 0),
                node(30.0 + rotation, 1200),
            )
        )

    points = parser.feed(b"".join(records))

    assert len(points) == len(records)
    assert [point.scan_start for point in points] == [True, False, False, False] * 10
    assert [point.distance_mm for point in points[::4]] == [0.0] * 10
    assert [point.angle_deg for point in points[1:4]] == [10.0, 20.0, 30.0]


def test_region_filters_points_without_assuming_a_quadrant():
    region = DetectionRegion(260, 280, 500, 1500)
    points = (ScanPoint(270, 1000, 10), ScanPoint(250, 1000, 10), ScanPoint(270, 2000, 10))

    assert region.select(points) == (points[0],)


def test_baseline_uses_multiple_frames_and_detects_distance_change():
    region = DetectionRegion(260, 280, 500, 1500)
    comparator = BaselineComparator(region, change_distance_mm=100, change_ratio=0.2)
    frames = [(ScanPoint(270, distance, 10),) for distance in (1000, 1010, 990)]

    comparator.build_baseline(frames)

    result = comparator.compare((ScanPoint(270, 1250, 10),))
    assert result.data_valid is True
    assert result.has_change is True
    assert result.change_ratio == 1.0


def test_comparison_matches_nearby_angle_with_default_tolerance():
    region = DetectionRegion(260, 280, 500, 1500)
    comparator = BaselineComparator(region, change_distance_mm=100, change_ratio=0.2)
    comparator.build_baseline(((ScanPoint(270, 1000, 10),),))

    result = comparator.compare((ScanPoint(271.5, 1300, 10),))

    assert result.data_valid is True
    assert result.has_change is True
    assert result.changed_points == 1
    assert result.compared_points == 1


def test_comparison_marks_point_beyond_configured_angle_tolerance_as_invalid():
    region = DetectionRegion(260, 280, 500, 1500)
    comparator = BaselineComparator(
        region,
        change_distance_mm=100,
        change_ratio=0.2,
        angle_match_tolerance_deg=1.0,
    )
    comparator.build_baseline(((ScanPoint(270, 1000, 10),),))

    result = comparator.compare((ScanPoint(271.5, 1300, 10),))

    assert result.data_valid is False
    assert result.has_change is False
    assert result.compared_points == 0


def test_comparison_matches_nearby_angles_across_zero_degrees():
    region = DetectionRegion(350, 10, 500, 1500)
    comparator = BaselineComparator(region, change_distance_mm=100, change_ratio=0.2)
    comparator.build_baseline(((ScanPoint(359, 1000, 10),),))

    result = comparator.compare((ScanPoint(0.5, 1300, 10),))

    assert result.data_valid is True
    assert result.has_change is True
    assert result.compared_points == 1


def test_comparison_uses_each_current_sample_at_most_once():
    region = DetectionRegion(260, 280, 500, 1500)
    comparator = BaselineComparator(region, change_distance_mm=100, change_ratio=0.2)
    comparator.build_baseline(
        ((ScanPoint(270, 1000, 10), ScanPoint(271, 1000, 10)),)
    )

    result = comparator.compare((ScanPoint(270.5, 1300, 10),))

    assert result.data_valid is True
    assert result.changed_points == 1
    assert result.compared_points == 1


def test_comparison_maximizes_nearby_match_count():
    region = DetectionRegion(0, 20, 500, 1500)
    comparator = BaselineComparator(region, change_distance_mm=100, change_ratio=0.2)
    comparator.build_baseline(
        ((ScanPoint(10, 1000, 10), ScanPoint(12, 1000, 10)),)
    )

    result = comparator.compare(
        (ScanPoint(8, 1300, 10), ScanPoint(10, 1300, 10))
    )

    assert result.data_valid is True
    assert result.changed_points == 2
    assert result.compared_points == 2


def test_comparison_minimizes_distance_among_maximum_matchings():
    region = DetectionRegion(0, 20, 500, 1500)
    comparator = BaselineComparator(
        region,
        change_distance_mm=100,
        change_ratio=0.1,
        angle_match_tolerance_deg=11.0,
    )
    comparator.build_baseline(
        ((ScanPoint(0, 1000, 10), ScanPoint(10, 1400, 10)),)
    )

    result = comparator.compare(
        (ScanPoint(9, 1000, 10), ScanPoint(11, 1400, 10))
    )

    assert result.data_valid is True
    assert result.has_change is False
    assert result.changed_points == 0
    assert result.compared_points == 2


@pytest.mark.parametrize(
    "tolerance",
    (float("nan"), float("inf"), float("-inf"), -0.5, 180.5),
)
def test_comparator_rejects_invalid_angle_match_tolerance(tolerance):
    region = DetectionRegion(0, 20, 500, 1500)

    with pytest.raises(ValueError, match="between 0 and 180"):
        BaselineComparator(
            region,
            change_distance_mm=100,
            change_ratio=0.2,
            angle_match_tolerance_deg=tolerance,
        )


def test_comparison_marks_empty_current_region_as_invalid():
    region = DetectionRegion(260, 280, 500, 1500)
    comparator = BaselineComparator(region, change_distance_mm=100, change_ratio=0.2)
    comparator.build_baseline(((ScanPoint(270, 1000, 10),),))

    result = comparator.compare((ScanPoint(10, 1000, 10),))

    assert result.data_valid is False
    assert result.has_change is False
    assert result.change_ratio == 0.0
    assert result.changed_points == 0
    assert result.compared_points == 0


def test_confirmation_requires_consecutive_frames_in_each_direction():
    state = ConfirmationState(required_frames=3)

    assert [state.update(value) for value in (True, False, True, True, True)] == [False, False, False, False, True]
    assert state.update(False) is False
    assert state.update(False) is False
    assert state.update(False) is True


class FakeSerial:
    def __init__(
        self,
        port=None,
        *_args,
        reads=(),
        stale_reads=(),
        scan_reads=(),
        **kwargs,
    ):
        self.writes = []
        self.reads = list(stale_reads)
        self.scan_reads = list(reads) + list(scan_reads)
        self.events = []
        self.closed = False
        self.is_open = port is not None
        self.port = port
        self.open_dtr = None
        self.dtr = True
        self.rts = True
        self.rtscts = kwargs.get("rtscts", True)
        self.dsrdtr = kwargs.get("dsrdtr", True)

    def reset_input_buffer(self):
        self.events.append("reset_input_buffer")
        self.reads.clear()

    def write(self, payload):
        self.writes.append(payload)
        self.events.append(("write", payload))
        if payload == bytes.fromhex("a520"):
            self.reads.extend(self.scan_reads)
            self.scan_reads.clear()

    def flush(self):
        pass

    def read(self, size):
        if self.reads:
            chunk = self.reads.pop(0)
            if len(chunk) > size:
                self.reads.insert(0, chunk[size:])
            return chunk[:size]
        return b""

    def close(self):
        self.closed = True

    def open(self):
        self.open_dtr = self.dtr
        self.is_open = True
        self.events.append("open")


def test_device_starts_scanning_without_info_query():
    serial = FakeSerial()
    device = A1M8Device(
        ports=("/dev/radar",),
        serial_factory=lambda *_args, **_kwargs: serial,
        motor_start_delay_s=0,
    )

    assert device.open() is True
    assert serial.writes == [bytes.fromhex("a520")]
    assert serial.dtr is False
    assert serial.rts is False
    assert serial.rtscts is False
    assert serial.dsrdtr is False
    assert serial.is_open is True
    assert serial.port == "/dev/radar"
    assert serial.open_dtr is False

    device.close()
    assert serial.writes[-1] == bytes.fromhex("a525")


def test_device_clears_stale_input_before_requesting_scan_descriptor():
    descriptor = bytes.fromhex("a55a0500004081")
    payload = node(0.0, 500, start=True) + node(90.0, 600) + node(1.0, 550, start=True)
    serial = FakeSerial(
        stale_reads=[bytes.fromhex("deadbeef")],
        scan_reads=[descriptor + payload],
    )
    device = A1M8Device(
        ports=("/dev/radar",),
        serial_factory=lambda *_args, **_kwargs: serial,
        motor_start_delay_s=0,
    )

    assert device.open() is True
    frame = next(device.iter_scans(threading.Event()))

    assert serial.events[:3] == [
        "open",
        "reset_input_buffer",
        ("write", bytes.fromhex("a520")),
    ]
    assert [point.angle_deg for point in frame] == [0.0, 90.0]
    assert device.diagnostics["descriptor_valid"] is True


def test_device_consumes_split_descriptor_and_yields_only_complete_rotation():
    descriptor = bytes.fromhex("a55a0500004081")
    payload = node(0.0, 500, start=True) + node(90.0, 600) + node(1.0, 550, start=True)
    serial = FakeSerial(reads=[descriptor[:3], descriptor[3:] + payload])
    device = A1M8Device(
        ports=("/dev/radar",),
        serial_factory=lambda *_args, **_kwargs: serial,
        motor_start_delay_s=0,
    )
    stop = threading.Event()

    assert device.open() is True
    frame = next(device.iter_scans(stop))

    assert [point.angle_deg for point in frame] == [0.0, 90.0]
    assert serial.writes == [bytes.fromhex("a520")]
    assert device.diagnostics["descriptor_valid"] is True
    assert device.diagnostics["bytes_received"] == len(descriptor) + len(payload)
    assert device.diagnostics["valid_points"] == 3
    assert device.diagnostics["complete_rotations"] == 1
    assert device.diagnostics["last_frame_size"] == 2
    assert device.diagnostics["last_frame_timestamp"] > 0


def test_device_rejects_invalid_descriptor():
    serial = FakeSerial(reads=[bytes.fromhex("a55a0500004080")])
    device = A1M8Device(
        ports=("/dev/radar",),
        serial_factory=lambda *_args, **_kwargs: serial,
        motor_start_delay_s=0,
    )

    assert device.open() is True
    with pytest.raises(RadarProtocolError, match="扫描响应描述头无效"):
        next(device.iter_scans(threading.Event()))


def test_device_reports_when_no_descriptor_was_received():
    device = A1M8Device(
        ports=("/dev/radar",),
        serial_factory=lambda *_args, **_kwargs: FakeSerial(),
        motor_start_delay_s=0,
        descriptor_timeout_s=0.01,
    )
    stop = threading.Event()

    assert device.open() is True
    started_at = time.monotonic()
    with pytest.raises(RadarProtocolError, match="未收到扫描响应描述头"):
        next(device.iter_scans(stop))
    assert time.monotonic() - started_at < 0.25
    assert stop.is_set() is False


def test_device_resets_descriptor_valid_when_reopened():
    descriptor = bytes.fromhex("a55a0500004081")
    payload = node(0.0, 500, start=True) + node(1.0, 550, start=True)
    serial = FakeSerial(reads=[descriptor + payload])
    device = A1M8Device(
        ports=("/dev/radar",),
        serial_factory=lambda *_args, **_kwargs: serial,
        motor_start_delay_s=0,
    )

    assert device.open() is True
    iterator = device.iter_scans(threading.Event())
    next(iterator)
    iterator.close()
    assert device.diagnostics["descriptor_valid"] is True

    device.close()
    serial.scan_reads = [bytes.fromhex("a55a0500004080")]
    assert device.open() is True
    assert device.diagnostics["descriptor_valid"] is False
    with pytest.raises(RadarProtocolError, match="扫描响应描述头无效"):
        next(device.iter_scans(threading.Event()))
    assert device.diagnostics["descriptor_valid"] is False


def test_device_discards_points_before_first_rotation_start():
    descriptor = bytes.fromhex("a55a0500004081")
    payload = (
        node(270.0, 400)
        + node(0.0, 500, start=True)
        + node(90.0, 600)
        + node(1.0, 550, start=True)
    )
    serial = FakeSerial(reads=[descriptor + payload])
    device = A1M8Device(
        ports=("/dev/radar",),
        serial_factory=lambda *_args, **_kwargs: serial,
        motor_start_delay_s=0,
    )

    assert device.open() is True
    frame = next(device.iter_scans(threading.Event()))

    assert [point.angle_deg for point in frame] == [0.0, 90.0]
