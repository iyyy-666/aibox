"""Raw A1M8 scan parsing and fixed-region object detection."""

from .detection import (
    BaselineComparator,
    ConfirmationState,
    DetectionRegion,
    DetectionResult,
)
from .protocol import ScanPoint, parse_scan_nodes

__all__ = [
    "BaselineComparator",
    "ConfirmationState",
    "DetectionRegion",
    "DetectionResult",
    "ScanPoint",
    "parse_scan_nodes",
]
