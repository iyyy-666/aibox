from __future__ import annotations

import threading

import feature_demo.workers.robot as robot_workers
import feature_demo.workers.runtime as runtime

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
