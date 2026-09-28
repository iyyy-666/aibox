from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScanPoint:
    angle_deg: float
    distance_mm: float
    quality: int
    scan_start: bool = False


def _decode_structural_scan_node(data: bytes) -> ScanPoint | None:
    if len(data) != 5:
        return None
    quality_flags, angle_low, angle_high, distance_low, distance_high = data
    start = quality_flags & 0x01
    inverse_start = (quality_flags >> 1) & 0x01
    if start == inverse_start or (angle_low & 0x01) != 1:
        return None
    angle_deg = (((angle_high << 8) | angle_low) >> 1) / 64.0
    distance_mm = ((distance_high << 8) | distance_low) / 4.0
    if not 0 <= angle_deg < 360:
        return None
    return ScanPoint(angle_deg, distance_mm, quality_flags >> 2, bool(start))


def parse_scan_node(data: bytes) -> ScanPoint | None:
    """Decode a structurally valid node, including zero-distance returns."""
    return _decode_structural_scan_node(data)


class A1ScanStreamParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> tuple[ScanPoint, ...]:
        self._buffer.extend(data)
        points: list[ScanPoint] = []
        while len(self._buffer) >= 5:
            point = parse_scan_node(bytes(self._buffer[:5]))
            if point is None:
                del self._buffer[0]
                continue
            del self._buffer[:5]
            points.append(point)
        return tuple(points)


def parse_scan_nodes(data: bytes) -> tuple[ScanPoint, ...]:
    """Decode the five-byte legacy A1/RPLIDAR scan node format."""
    if len(data) % 5:
        raise ValueError("scan node payload length must be a multiple of five")
    points: list[ScanPoint] = []
    for offset in range(0, len(data), 5):
        point = parse_scan_node(data[offset : offset + 5])
        if point is not None:
            points.append(point)
    return tuple(points)
