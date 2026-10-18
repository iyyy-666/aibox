from __future__ import annotations

import threading

import feature_demo.workers.robot as robot_workers
import feature_demo.workers.runtime as runtime
import pytest

from feature_demo.adapters.robot import RobotAdapter
from feature_demo.adapters.vision import LegacyVisionAdapter, LegacyVisionSpec
from feature_demo.workers.robot import RobotWorker


class FakeSerial:
    def __init__(self, calls):
        self.calls = calls
        self.connected = False

    def connect(self):
        self.calls.append("connect")
        self.connected = True
        return True

    def disconnect(self):
        self.calls.append("disconnect")
        self.connected = False


class BlockingConnectSerial(FakeSerial):
    def __init__(self, calls, connect_started, release_connect):
        super().__init__(calls)
        self.connect_started = connect_started
        self.release_connect = release_connect

    def connect(self):
        self.calls.append("connect_started")
        self.connect_started.set()
        self.release_connect.wait(timeout=2)
        self.calls.append("connect")
        self.connected = True
        return True


class BlockingDisconnectSerial(FakeSerial):
    def __init__(self, calls, disconnect_started, release_disconnect):
        super().__init__(calls)
        self.disconnect_started = disconnect_started
        self.release_disconnect = release_disconnect
        self.disconnecting = False

    def disconnect(self):
        self.calls.append("disconnect_started")
        self.disconnecting = True
        self.disconnect_started.set()
        self.release_disconnect.wait(timeout=2)
        self.connected = False
        self.disconnecting = False
        self.calls.append("disconnect")


class FakeRobot:
    def __init__(self, serial, calls):
        self.serial = serial
        self.calls = calls

    def stop(self):
        self.calls.append("stop_motion")
        return True

    def execute_pose(self, name):
        self.calls.append(("pose", name))
        return True

    def execute_sequence(self, name):
        self.calls.append(("sequence", name))
        return True

    def move_servo_step(self, servo_id, delta, time_ms):
        self.calls.append(("joint_step", servo_id, delta, time_ms))
        return True

    def gripper_open(self):
        self.calls.append(("gripper", "open"))
        return True

    def prepare_sorting_pose(self):
        self.calls.append("sorting_ready")
        return True

    def execute_sort_transfer(self, side):
        self.calls.append(("sorting", side))
        return True


class StopFailureRobot(FakeRobot):
    def stop(self):
        self.calls.append("stop_motion")
        raise RuntimeError("emergency stop failed")


class StopRejectedRobot(FakeRobot):
    def stop(self):
        self.calls.append("stop_motion")
        return False


class BlockingTransferRobot(FakeRobot):
    def __init__(self, serial, calls):
        super().__init__(serial, calls)
        self.transfer_started = threading.Event()
        self.release_transfer = threading.Event()
        self.stop_called = threading.Event()

    def execute_sort_transfer(self, side):
        self.calls.append(("sorting", side))
        self.transfer_started.set()
        self.release_transfer.wait(timeout=2.0)
        return True

    def stop(self):
        self.calls.append("stop_motion")
        self.stop_called.set()
        return True


class BlockingSequenceRobot(FakeRobot):
    def __init__(self, serial, calls):
        super().__init__(serial, calls)
        self.sequence_started = threading.Event()
        self.stop_called = threading.Event()
        self.release_sequence = threading.Event()

    def execute_sequence(self, name):
        self.calls.append(("sequence", name))
        self.sequence_started.set()
        self.release_sequence.wait(timeout=2.0)
        return not self.stop_called.is_set()

    def stop(self):
        self.calls.append("stop_motion")
        self.stop_called.set()
        self.release_sequence.set()
        return True


class BlockingStopRobot(FakeRobot):
    def __init__(self, serial, calls):
        super().__init__(serial, calls)
        self.stop_started = threading.Event()
        self.release_stop = threading.Event()

    def stop(self):
        self.calls.append("stop_motion")
        self.stop_started.set()
        self.release_stop.wait(timeout=2.0)
        return True


class DisconnectAwareRobot(FakeRobot):
    def stop(self):
        self.calls.append(("stop_during_disconnect", self.serial.disconnecting))
        return True


class FakeVisionWorker:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.last_event = {}
        self.observer = None

    def start(self):
        self.started = True
        self.last_event = {"type": "ready"}

    def command(self, name, payload):
        return {"ok": True, "command": name}

    def stop(self):
        self.stopped = True
        self.last_event = {"type": "stopped"}


class StopFailureVisionWorker(FakeVisionWorker):
    def stop(self):
        super().stop()
        raise RuntimeError("camera shutdown failed")


class OrderedVisionWorker(FakeVisionWorker):
    def __init__(self, calls):
        super().__init__()
        self.calls = calls

    def stop(self):
        self.calls.append("vision_stop")
        super().stop()


class StartupOrderedVisionWorker(FakeVisionWorker):
    def __init__(self, calls):
        super().__init__()
        self.calls = calls

    def start(self):
        self.calls.append("vision_start")
        super().start()


class StartupGimbal:
    def __init__(self, calls):
        self.calls = calls

    def move_to(self, yaw, pitch):
        self.calls.append(("gimbal_target", yaw, pitch))
        return {"ok": True, "message": "positioned"}


class FakeSortingAdapter:
    def __init__(self, stable_hits):
        self.module = type("LegacySortingModule", (), {"STABLE_HITS": stable_hits})
        self.observer = None

    def set_sorting_observer(self, observer):
        self.observer = observer

    def process(self, frame):
        return frame, {"result": []}

    def close(self):
        return None


def make_adapter(calls):
    return RobotAdapter(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: FakeRobot(serial, calls),
    )


def test_robot_worker_does_not_open_serial_until_explicit_motion_command():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda _event: None)

    worker.start()

    assert calls == []
    worker.command("pose", {"name": "stand"})
    assert calls[:2] == ["connect", ("pose", "stand")]


def make_worker(calls, robot_type=FakeRobot):
    return RobotWorker(
        RobotAdapter(
            serial_factory=lambda: FakeSerial(calls),
            robot_factory=lambda serial: robot_type(serial, calls),
        ),
        event_sink=lambda event: None,
    )


def test_robot_adapter_surfaces_rejected_emergency_stop():
    calls = []
    adapter = RobotAdapter(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: StopRejectedRobot(serial, calls),
    )
    adapter.connect()

    with pytest.raises(RuntimeError, match="机械臂急停命令执行失败"):
        adapter.stop_motion()


def make_blocking_transfer_worker(calls):
    created = []
    worker = RobotWorker(
        RobotAdapter(
            serial_factory=lambda: FakeSerial(calls),
            robot_factory=lambda serial: created.append(BlockingTransferRobot(serial, calls)) or created[-1],
        ),
        event_sink=lambda event: None,
    )
    return worker, created


def test_robot_serial_is_lazy():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda event: None)

    assert calls == []
    worker.start()

    assert calls == []
    worker.stop()


def test_robot_start_does_not_move_upright():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda event: None)

    worker.start()

    assert calls == []
    worker.stop()


def test_robot_stop_stops_motion_before_disconnect():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda event: None)
    worker.start()
    worker.command("pose", {"name": "stand"})

    worker.stop()

    assert calls.index("stop_motion") < calls.index("disconnect")


def test_robot_worker_maps_existing_commands():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda event: None)
    worker.start()

    assert worker.command("pose", {"name": "直立"})["ok"]
    assert worker.command("sequence", {"name": "搬运"})["ok"]
    assert worker.command("joint_step", {"servo_id": 2, "delta": 30})["ok"]
    assert worker.command("gripper", {"action": "open"})["ok"]
    worker.stop()

    assert ("pose", "直立") in calls
    assert ("sequence", "搬运") in calls
    assert ("joint_step", 2, 30, 200) in calls
    assert ("gripper", "open") in calls


def test_upright_pose_releases_serial_and_ignores_repeat_until_other_motion():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda event: None)
    worker.start()

    first = worker.command("pose", {"name": "直立"})
    calls_after_first = list(calls)
    second = worker.command("pose", {"name": "直立"})
    worker.stop()

    assert first["ok"] is True
    assert second["ok"] is True
    assert calls_after_first == ["connect", ("pose", "直立"), "disconnect"]
    assert calls == ["connect", ("pose", "直立"), "disconnect"]


def test_explicit_stop_remains_available_while_upright_is_held():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda event: None)
    worker.start()
    worker.command("pose", {"name": "直立"})

    result = worker.command("stop_motion", {})
    worker.disconnect()

    assert result["ok"] is True
    assert calls == [
        "connect",
        ("pose", "直立"),
        "disconnect",
        "connect",
        "stop_motion",
        "disconnect",
    ]


def test_shutdown_interrupts_motion_started_after_upright_without_deadlock():
    calls = []
    created = []
    adapter = RobotAdapter(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: created.append(BlockingSequenceRobot(serial, calls))
        or created[-1],
    )
    worker = RobotWorker(adapter, event_sink=lambda event: None)
    worker.start()
    worker.command("pose", {"name": "直立"})

    motion = threading.Thread(
        target=lambda: worker.command("sequence", {"name": "搬运"})
    )
    motion.start()
    assert created[-1].sequence_started.wait(timeout=1)

    closing = threading.Thread(target=worker.stop)
    closing.start()
    try:
        assert created[-1].stop_called.wait(timeout=1)
        motion.join(timeout=1)
        closing.join(timeout=1)
    finally:
        created[-1].release_sequence.set()
        motion.join(timeout=1)
        closing.join(timeout=1)

    assert not motion.is_alive()
    assert not closing.is_alive()
    assert calls.index("stop_motion") < len(calls) - 1
    assert calls[-1] == "disconnect"


def test_successful_sorting_motion_clears_upright_deduplication():
    calls = []
    adapter = make_adapter(calls)

    assert adapter.command("pose", {"name": "直立"})["ok"] is True
    assert adapter.command("sorting_transfer", {"side": "left"})["ok"] is True
    assert adapter.command("pose", {"name": "直立"})["ok"] is True
    adapter.shutdown()

    assert calls.count(("pose", "直立")) == 2


def test_explicit_stop_cannot_be_disconnected_before_its_command_is_sent():
    calls = []
    created = []
    robot_created = threading.Event()

    def make_robot(serial):
        created.append(BlockingStopRobot(serial, calls))
        robot_created.set()
        return created[-1]

    adapter = RobotAdapter(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=make_robot,
    )
    adapter.command("pose", {"name": "直立"})
    robot_created.clear()

    explicit = threading.Thread(target=adapter.stop_motion)
    closing = threading.Thread(target=adapter.shutdown)
    explicit.start()
    assert robot_created.wait(timeout=1)
    stopping_robot = created[-1]
    assert stopping_robot.stop_started.wait(timeout=1)
    closing.start()

    assert calls.count("disconnect") == 1
    stopping_robot.release_stop.set()
    explicit.join(timeout=1)
    closing.join(timeout=1)

    assert not explicit.is_alive()
    assert not closing.is_alive()
    assert calls.index("stop_motion") < len(calls) - 1
    assert calls[-1] == "disconnect"


def test_shutdown_serializes_disconnect_before_a_concurrent_explicit_stop():
    calls = []
    disconnect_started = threading.Event()
    release_disconnect = threading.Event()
    serials = []

    def make_serial():
        if not serials:
            serial = FakeSerial(calls)
        else:
            serial = BlockingDisconnectSerial(
                calls, disconnect_started, release_disconnect
            )
        serials.append(serial)
        return serial

    adapter = RobotAdapter(
        serial_factory=make_serial,
        robot_factory=lambda serial: DisconnectAwareRobot(serial, calls),
    )
    adapter.command("pose", {"name": "直立"})
    adapter.connect()
    closing = threading.Thread(target=adapter.shutdown)
    closing.start()
    assert disconnect_started.wait(timeout=1)

    stopping = threading.Thread(target=adapter.stop_motion)
    stopping.start()
    assert not any(
        call == ("stop_during_disconnect", True) for call in calls
    )
    release_disconnect.set()
    closing.join(timeout=1)
    stopping.join(timeout=1)

    assert not closing.is_alive()
    assert not stopping.is_alive()
    assert ("stop_during_disconnect", True) not in calls
    assert ("stop_during_disconnect", False) in calls


def test_shutdown_cannot_finish_while_an_accepted_motion_is_connecting():
    calls = []
    connect_started = threading.Event()
    release_connect = threading.Event()
    robot_created = threading.Event()
    created = []

    def make_robot(serial):
        created.append(BlockingSequenceRobot(serial, calls))
        robot_created.set()
        return created[-1]

    adapter = RobotAdapter(
        serial_factory=lambda: BlockingConnectSerial(
            calls, connect_started, release_connect
        ),
        robot_factory=make_robot,
    )

    motion = threading.Thread(
        target=lambda: adapter.command("sequence", {"name": "搬运"})
    )
    motion.start()
    assert connect_started.wait(timeout=1)
    closing = threading.Thread(target=adapter.shutdown)
    closing.start()

    assert closing.is_alive()
    release_connect.set()
    try:
        assert robot_created.wait(timeout=1)
        assert created[-1].sequence_started.wait(timeout=1)
        assert created[-1].stop_called.wait(timeout=1)
        motion.join(timeout=1)
        closing.join(timeout=1)
    finally:
        if created:
            created[-1].release_sequence.set()
        motion.join(timeout=1)
        closing.join(timeout=1)

    assert not motion.is_alive()
    assert not closing.is_alive()


def test_runtime_dispatches_robot_button_without_opening_serial():
    calls = []

    assert callable(getattr(runtime, "create_worker", None))
    worker = runtime.create_worker(
        "robot_button",
        event_sink=lambda event: None,
        robot_adapter=make_adapter(calls),
    )

    assert isinstance(worker, RobotWorker)
    assert calls == []
    worker.start()
    assert calls == []
    worker.stop()


def test_object_sorting_requires_prepare_then_maps_stable_red_and_blue_to_fixed_sides():
    calls = []
    robot_worker = make_worker(calls)
    controller = robot_workers.SortingController(robot_worker, event_sink=lambda event: None)
    worker = robot_workers.ObjectSortingWorker(FakeVisionWorker(), robot_worker, controller, event_sink=lambda event: None)
    worker.start()

    assert worker.command("start_sorting", {})["ok"] is False
    assert worker.command("prepare", {})["ok"] is True
    assert worker.command("start_sorting", {})["ok"] is True
    controller.observe_color("red")
    controller.observe_color("red")
    assert worker.command("start_sorting", {})["ok"] is True
    controller.observe_color("blue")
    controller.observe_color("blue")

    assert ("sorting", "left") in calls
    assert ("sorting", "right") in calls
    worker.stop()


def test_object_sorting_moves_gimbal_to_demo_pose_before_starting_camera():
    calls = []
    robot_worker = make_worker(calls)
    worker = robot_workers.ObjectSortingWorker(
        StartupOrderedVisionWorker(calls),
        robot_worker,
        robot_workers.SortingController(robot_worker, event_sink=lambda event: None),
        event_sink=lambda event: None,
        startup_gimbal=StartupGimbal(calls),
        gimbal_target=(1200, 1110),
    )

    worker.start()

    assert calls[:2] == [("gimbal_target", 1200, 1110), "vision_start"]
    worker.stop()


def test_object_sorting_maps_legacy_red_and_blue_labels_to_fixed_sides():
    calls = []
    robot_worker = make_worker(calls)
    controller = robot_workers.SortingController(robot_worker, stable_hits=2, event_sink=lambda event: None)
    robot_worker.start()

    controller.prepare()
    controller.start()
    controller.observe_color("Red")
    controller.observe_color("Red")
    controller.start()
    controller.observe_color("Blue")
    controller.observe_color("Blue")

    assert ("sorting", "left") in calls
    assert ("sorting", "right") in calls
    robot_worker.stop()


def test_sorting_adapter_notifies_empty_detection_to_reset_stability():
    calls = []
    robot_worker = make_worker(calls)
    controller = robot_workers.SortingController(robot_worker, stable_hits=2, event_sink=lambda event: None)
    detections = iter([("Red", (0, 0, 1, 1), 1.0), None, ("Red", (0, 0, 1, 1), 1.0)])
    module = type("LegacySortingModule", (), {"split_stereo": staticmethod(lambda frame: (frame, None))})
    instance = type(
        "LegacySortingInstance",
        (),
        {
            "_detect_color": lambda self, frame: next(detections),
            "_annotate": lambda self, frame, detected: frame,
        },
    )()
    adapter = LegacyVisionAdapter("object_sorting", module, instance, LegacyVisionSpec("sorting_app.py", "SortingApp", "sorting"))
    adapter.set_sorting_observer(controller.observe_color)
    robot_worker.start()
    controller.prepare()
    controller.start()

    adapter.process(object())
    adapter.process(object())
    adapter.process(object())

    assert ("sorting", "left") not in calls
    assert controller.snapshot()["candidate_count"] == 1
    robot_worker.stop()


def test_stop_motion_preempts_blocking_transfer_before_disconnect():
    calls = []
    worker, created = make_blocking_transfer_worker(calls)
    worker.start()
    worker.command("pose", {"name": "stand"})
    robot = created[0]
    transfer = threading.Thread(target=lambda: worker.command("sorting_transfer", {"side": "left"}))
    transfer.start()
    assert robot.transfer_started.wait(timeout=1.0)

    stopper = threading.Thread(target=worker.stop)
    stopper.start()
    assert robot.stop_called.wait(timeout=0.5)
    assert "disconnect" not in calls
    robot.release_transfer.set()
    transfer.join(timeout=1.0)
    stopper.join(timeout=1.0)

    assert not transfer.is_alive()
    assert not stopper.is_alive()
    assert calls.index("stop_motion") < calls.index("disconnect")


def test_stop_motion_preempts_blocking_sequence_through_robot_worker():
    calls = []
    created = []
    worker = RobotWorker(
        RobotAdapter(
            serial_factory=lambda: FakeSerial(calls),
            robot_factory=lambda serial: created.append(
                BlockingSequenceRobot(serial, calls)
            )
            or created[-1],
        ),
        event_sink=lambda event: None,
    )
    worker.start()
    worker.command("pose", {"name": "stand"})
    robot = created[0]
    sequence = threading.Thread(
        target=lambda: worker.command("sequence", {"name": "搬运"})
    )
    sequence.start()
    assert robot.sequence_started.wait(timeout=1.0)

    stopper = threading.Thread(target=worker.stop_motion)
    stopper.start()
    try:
        assert robot.stop_called.wait(timeout=0.2)
    finally:
        robot.release_sequence.set()
        sequence.join(timeout=1.0)
        stopper.join(timeout=1.0)
        worker.disconnect()

    assert not sequence.is_alive()
    assert not stopper.is_alive()


def test_queued_motion_cannot_block_stop_from_preempting_active_motion():
    calls = []
    created = []
    worker = RobotWorker(
        RobotAdapter(
            serial_factory=lambda: FakeSerial(calls),
            robot_factory=lambda serial: created.append(
                BlockingSequenceRobot(serial, calls)
            )
            or created[-1],
        ),
        event_sink=lambda event: None,
    )
    worker.start()
    active = threading.Thread(
        target=lambda: worker.command("sequence", {"name": "搬运"})
    )
    active.start()
    assert created[0].sequence_started.wait(timeout=1)

    queued_started = threading.Event()

    def queue_motion():
        queued_started.set()
        worker.command("pose", {"name": "直立"})

    queued = threading.Thread(target=queue_motion)
    queued.start()
    assert queued_started.wait(timeout=1)
    threading.Event().wait(0.05)

    stopper = threading.Thread(target=worker.stop_motion)
    stopper.start()
    try:
        assert created[0].stop_called.wait(timeout=0.5)
    finally:
        created[0].release_sequence.set()
        active.join(timeout=1)
        queued.join(timeout=1)
        stopper.join(timeout=1)
        worker.disconnect()

    assert not active.is_alive()
    assert not queued.is_alive()
    assert not stopper.is_alive()


def test_object_sorting_stop_requests_robot_stop_before_vision_shutdown():
    calls = []
    robot_worker = make_worker(calls)
    worker = robot_workers.ObjectSortingWorker(
        OrderedVisionWorker(calls),
        robot_worker,
        robot_workers.SortingController(robot_worker, event_sink=lambda event: None),
        event_sink=lambda event: None,
    )
    worker.start()
    worker.command("prepare", {})

    worker.stop()

    assert calls.index("stop_motion") < calls.index("vision_stop") < calls.index("disconnect")


def test_runtime_uses_legacy_sorting_stable_hits_setting():
    adapter = FakeSortingAdapter(stable_hits=4)

    worker = runtime.create_worker(
        "object_sorting",
        cv2_module=object(),
        adapter_builder=lambda module_id: adapter,
        event_sink=lambda event: None,
        gimbal=object(),
    )

    assert worker._controller.stable_hits == 4


def test_object_sorting_pause_and_stop_reset_detection_and_stop_motion():
    calls = []
    robot_worker = make_worker(calls)
    assert callable(getattr(robot_workers, "SortingController", None))
    assert callable(getattr(robot_workers, "ObjectSortingWorker", None))
    controller = robot_workers.SortingController(robot_worker, stable_hits=2, event_sink=lambda event: None)
    worker = robot_workers.ObjectSortingWorker(FakeVisionWorker(), robot_worker, controller, event_sink=lambda event: None)
    worker.start()
    worker.command("prepare", {})
    worker.command("start_sorting", {})
    controller.observe_color("red")

    assert worker.command("pause_sorting", {})["paused"] is True
    assert worker.command("stop_sorting", {})["ok"] is True
    assert controller.snapshot() == {"prepared": False, "sorting": False, "paused": False, "candidate_color": "", "candidate_count": 0}
    assert "stop_motion" in calls
    worker.stop()


def test_robot_stop_disconnects_when_stop_motion_raises():
    calls = []
    worker = make_worker(calls, robot_type=StopFailureRobot)
    worker.start()
    worker.command("pose", {"name": "stand"})

    try:
        worker.stop()
    except RuntimeError as exc:
        assert str(exc) == "emergency stop failed"
    else:
        raise AssertionError("stop() should surface the stop_motion failure")

    assert calls.index("stop_motion") < calls.index("disconnect")


def test_object_sorting_releases_robot_when_vision_stop_fails():
    calls = []
    robot_worker = make_worker(calls)
    controller = robot_workers.SortingController(robot_worker, stable_hits=2, event_sink=lambda event: None)
    worker = robot_workers.ObjectSortingWorker(
        StopFailureVisionWorker(),
        robot_worker,
        controller,
        event_sink=lambda event: None,
    )
    worker.start()
    robot_worker.command("sorting_ready", {})

    try:
        worker.stop()
    except RuntimeError as exc:
        assert str(exc) == "camera shutdown failed"
    else:
        raise AssertionError("stop() should surface the vision shutdown failure")

    assert calls.index("stop_motion") < calls.index("disconnect")
