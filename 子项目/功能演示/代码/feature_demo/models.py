from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


PREEMPTIVE_COMMANDS = frozenset(
    {
        "interrupt",
        "stop_listening",
        "stop_motion",
        "stop_playback",
        "stop_sorting",
        "stop_tracking",
    }
)


class ModuleState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
    CLEANUP_FAILED = "cleanup_failed"


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    module_id: str
    name: str
    description: str
    category: str
    worker: str
    resources: tuple[str, ...]
    commands: tuple[str, ...]
    visual: bool = False
