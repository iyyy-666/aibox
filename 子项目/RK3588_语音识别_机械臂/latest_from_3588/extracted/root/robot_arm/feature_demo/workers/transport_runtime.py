"""Construct the new module from existing camera, voice and actuator adapters."""
import os

from ..adapters.gimbal import GimbalAdapter
from ..adapters.robot import RobotAdapter
from ..adapters.transport_motion import build_transport_motion
from ..adapters.transport_vision import build_transport_vision
from ..adapters.vision import build_vision_adapter
from .transport import TransportWorker
from .voice import VoiceWorker
from .transport_voice import CachedEngineFactory


def create_transport_worker(*, event_sink, robot_adapter=None, cv2_module=None,
                            adapter_builder=None, gimbal=None):
    from .runtime import create_vision_worker, SORTING_GIMBAL_TARGET
    builder = adapter_builder or build_vision_adapter
    adapter = build_transport_vision(builder)
    positioning = gimbal if gimbal is not None else GimbalAdapter()
    engine_factory = CachedEngineFactory()

    def events(event):
        worker.component_event(event)

    vision = create_vision_worker('color_recognition', event_sink=events,
        cv2_module=cv2_module, adapter_builder=lambda _: adapter, gimbal=positioning)
    worker = TransportWorker(robot=build_transport_motion(robot_adapter or RobotAdapter()),
        vision=vision, gimbal=positioning, gimbal_target=SORTING_GIMBAL_TARGET,
        # Generic voice mode disables the short command grammar and opens only
        # existing ASR/PCM; it has no robot dispatch or assistant model.
        voice_factory=lambda sink: VoiceWorker('ai_assistant', event_sink=sink,
                                               engine_factory=engine_factory),
        event_sink=event_sink,
        detection_timeout=float(os.getenv('AIBOX_TRANSPORT_DETECT_SECONDS', '4')),
        stable_hits=int(os.getenv('AIBOX_TRANSPORT_STABLE_HITS', '3')))
    adapter.set_observer(worker.observe_blocks)
    return worker
