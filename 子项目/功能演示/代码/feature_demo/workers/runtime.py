from __future__ import annotations

import json
import os
import queue
import sys
import threading
from typing import Callable

from ..adapters.gimbal import GimbalAdapter
from ..adapters.robot import RobotAdapter
from ..adapters.vision import LEGACY_VISION_SPECS, build_vision_adapter
from ..models import PREEMPTIVE_COMMANDS
from .assistant import AssistantWorker
from .robot import ObjectSortingWorker, RobotWorker, SortingController
from .vision import VisionWorker
from .voice import VoiceWorker


def _configured_camera(cv2_module):
    device = os.getenv("AIBOX_CAMERA_DEVICE", "/dev/video41")
    capture = cv2_module.VideoCapture(device, cv2_module.CAP_V4L2)
    capture.set(
        cv2_module.CAP_PROP_FOURCC,
        cv2_module.VideoWriter_fourcc(*"MJPG"),
    )
    capture.set(cv2_module.CAP_PROP_FRAME_WIDTH, 1280)
    capture.set(cv2_module.CAP_PROP_FRAME_HEIGHT, 480)
    capture.set(cv2_module.CAP_PROP_FPS, 30)
    capture.set(cv2_module.CAP_PROP_BUFFERSIZE, 1)
    return capture


def _jpeg_encoder(cv2_module, frame) -> bytes:
    ok, encoded = cv2_module.imencode(
        ".jpg",
        frame,
        [cv2_module.IMWRITE_JPEG_QUALITY, 84],
    )
    if not ok:
        raise RuntimeError("无法编码实时画面。")
    return encoded if isinstance(encoded, bytes) else encoded.tobytes()


def create_vision_worker(
    module_id: str,
    *,
    cv2_module=None,
    adapter_builder: Callable[[str], object] | None = None,
    event_sink: Callable[[dict], None],
    gimbal=None,
) -> VisionWorker:
    if module_id not in LEGACY_VISION_SPECS:
        raise ValueError(f"未知的视觉 Worker：{module_id}")
    if cv2_module is None:
        import cv2 as cv2_module
    builder = adapter_builder or build_vision_adapter
    adapter = builder(module_id)
    directional_gimbal = gimbal if gimbal is not None else GimbalAdapter()
    pause_tracking = getattr(adapter, "stop_tracking", None) if module_id == "palm_tracking" else None
    manual_gimbal_step = (
        getattr(adapter, "manual_gimbal_step", None)
        if module_id == "palm_tracking"
        else None
    )
    return VisionWorker(
        adapter=adapter,
        camera_factory=lambda: _configured_camera(cv2_module),
        encode_frame=lambda frame: _jpeg_encoder(cv2_module, frame),
        event_sink=event_sink,
        gimbal=directional_gimbal,
        pause_tracking=pause_tracking,
        manual_gimbal_step=manual_gimbal_step,
    )


def create_worker(
    module_id: str,
    *,
    event_sink: Callable[[dict], None],
    robot_adapter: RobotAdapter | None = None,
    cv2_module=None,
    adapter_builder: Callable[[str], object] | None = None,
    gimbal=None,
):
    if module_id == "ai_assistant":
        return AssistantWorker(event_sink=event_sink)
    if module_id in {"voice_input_test", "nursery_rhyme"}:
        return VoiceWorker(module_id, event_sink=event_sink)
    if module_id == "voice_robot_arm":
        return VoiceWorker(module_id, event_sink=event_sink, robot_adapter=robot_adapter or RobotAdapter())
    if module_id == "robot_button":
        return RobotWorker(robot_adapter or RobotAdapter(), event_sink=event_sink)
    if module_id != "object_sorting":
        return create_vision_worker(
            module_id,
            cv2_module=cv2_module,
            adapter_builder=adapter_builder,
            event_sink=event_sink,
            gimbal=gimbal,
        )

    builder = adapter_builder or build_vision_adapter
    adapter = builder(module_id)
    try:
        stable_hits = max(1, int(getattr(adapter.module, "STABLE_HITS", 2)))
    except (AttributeError, TypeError, ValueError):
        stable_hits = 2
    def component_event_sink(event: dict) -> None:
        if event.get("type") != "ready":
            event_sink(event)

    robot_worker = RobotWorker(
        robot_adapter or RobotAdapter(), event_sink=component_event_sink
    )
    controller = SortingController(
        robot_worker,
        stable_hits=stable_hits,
        event_sink=component_event_sink,
    )
    set_observer = getattr(adapter, "set_sorting_observer", None)
    if callable(set_observer):
        set_observer(controller.observe_color)
    vision_worker = create_vision_worker(
        module_id,
        cv2_module=cv2_module,
        adapter_builder=lambda _: adapter,
        event_sink=event_sink,
        gimbal=gimbal,
    )
    return ObjectSortingWorker(
        vision_worker,
        robot_worker,
        controller,
        event_sink=event_sink,
    )


def emit_json(event: dict) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run_worker(module_id: str) -> int:
    worker = create_worker(module_id, event_sink=emit_json)
    ordinary_requests: queue.Queue[tuple[str, str, dict] | None] = queue.Queue()
    emit_lock = threading.Lock()
    control_threads: list[threading.Thread] = []

    def emit(event: dict) -> None:
        with emit_lock:
            emit_json(event)

    def execute(request_id: str, command: str, payload: dict) -> None:
        try:
            result = worker.command(command, payload)
            emit(
                {
                    **result,
                    "type": "command_result",
                    "request_id": request_id,
                }
            )
        except Exception as exc:
            emit(
                {
                    "type": "error",
                    "request_id": request_id,
                    "message": str(exc),
                }
            )

    def run_ordinary_commands() -> None:
        while True:
            request = ordinary_requests.get()
            if request is None:
                return
            execute(*request)

    ordinary_thread: threading.Thread | None = None
    try:
        try:
            worker.start()
        except Exception as exc:
            emit({"type": "error", "message": str(exc)})
            return 1
        ordinary_thread = threading.Thread(
            target=run_ordinary_commands,
            name="feature-demo-commands",
            daemon=True,
        )
        ordinary_thread.start()
        for line in sys.stdin:
            request_id = ""
            try:
                request = json.loads(line)
                request_id = str(request.get("request_id", ""))
                command = str(request.get("command", ""))
                payload = request.get("payload") or {}
                if command == "stop":
                    worker.stop()
                    return 0
                command_request = (request_id, command, payload)
                if command in PREEMPTIVE_COMMANDS:
                    thread = threading.Thread(
                        target=execute,
                        args=command_request,
                        name=f"feature-demo-control-{command}",
                        daemon=True,
                    )
                    control_threads.append(thread)
                    thread.start()
                else:
                    ordinary_requests.put(command_request)
            except Exception as exc:
                emit(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "message": str(exc),
                    }
                )
        ordinary_requests.put(None)
        ordinary_thread.join()
        for thread in control_threads:
            thread.join()
    finally:
        if worker.last_event.get("type") != "stopped":
            try:
                worker.stop()
            except Exception as exc:
                emit({"type": "error", "message": str(exc)})
    return 0
