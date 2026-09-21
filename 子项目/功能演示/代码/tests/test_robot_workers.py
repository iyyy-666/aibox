from __future__ import annotations

import feature_demo.workers.robot as robot_workers
import feature_demo.workers.runtime as runtime

from feature_demo.adapters.robot import RobotAdapter
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


def make_worker(calls, robot_type=FakeRobot):
    return RobotWorker(
        RobotAdapter(
            serial_factory=lambda: FakeSerial(calls),
            robot_factory=lambda serial: robot_type(serial, calls),
        ),
        event_sink=lambda event: None,
    )


def test_robot_serial_is_lazy():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda event: None)

    assert calls == []
    worker.start()

    assert calls == ["connect"]
    worker.stop()


def test_robot_start_does_not_move_upright():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda event: None)

    worker.start()

    assert calls == ["connect"]
    worker.stop()


def test_robot_stop_stops_motion_before_disconnect():
    calls = []
    worker = RobotWorker(make_adapter(calls), event_sink=lambda event: None)
    worker.start()

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
    assert calls == ["connect"]
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

    try:
        worker.stop()
    except RuntimeError as exc:
        assert str(exc) == "camera shutdown failed"
    else:
        raise AssertionError("stop() should surface the vision shutdown failure")

    assert calls.index("stop_motion") < calls.index("disconnect")
