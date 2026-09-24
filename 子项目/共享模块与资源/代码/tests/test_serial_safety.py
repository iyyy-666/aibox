from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from serial_driver import SerialDriver


class FakePort:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.is_open = False
        self.dtr = True
        self.rts = True
        self.port = None
        self.writes = []
        self.open_state = None

    def open(self):
        self.open_state = (self.dtr, self.rts, self.port)
        self.is_open = True

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass


def test_connect_disables_reset_lines_before_opening_robot_port(tmp_path):
    created = []

    def factory(**kwargs):
        port = FakePort(**kwargs)
        created.append(port)
        return port

    driver = SerialDriver(
        serial_factory=factory,
        audit_path=tmp_path / "robot-audit.jsonl",
    )

    assert driver.connect("/dev/esp32_arm", 115200)
    assert created[0].open_state == (False, False, "/dev/esp32_arm")


def test_serial_audit_records_open_and_explicit_command(tmp_path):
    audit = tmp_path / "robot-audit.jsonl"
    driver = SerialDriver(serial_factory=lambda **kwargs: FakePort(**kwargs), audit_path=audit)

    assert driver.connect("/dev/esp32_arm", 115200)
    assert driver.send_command("#000P1500T0200!")

    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [item["event"] for item in records] == ["serial_open", "command_write"]
    assert records[1]["command"] == "#000P1500T0200!"


def test_connect_closes_an_open_port_when_buffer_reset_fails(tmp_path):
    class ResetFailurePort(FakePort):
        def reset_input_buffer(self):
            raise OSError("reset failed")

    audit = tmp_path / "robot-audit.jsonl"
    port = ResetFailurePort()
    driver = SerialDriver(serial_factory=lambda **_kwargs: port, audit_path=audit)

    assert not driver.connect("/dev/esp32_arm", 115200)
    assert not port.is_open
    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [item["event"] for item in records] == ["serial_open"]


def test_connect_fails_closed_when_open_cannot_be_audited(tmp_path):
    port = FakePort()
    driver = SerialDriver(serial_factory=lambda **_kwargs: port, audit_path=tmp_path)

    assert not driver.connect("/dev/esp32_arm", 115200)
    assert not port.is_open


def test_flush_failure_never_retries_a_robot_command(tmp_path):
    class FlushFailurePort(FakePort):
        def flush(self):
            raise OSError("flush failed")

    created = []

    def factory(**kwargs):
        port = FlushFailurePort(**kwargs)
        created.append(port)
        return port

    audit = tmp_path / "robot-audit.jsonl"
    driver = SerialDriver(serial_factory=factory, audit_path=audit)
    assert driver.connect("/dev/esp32_arm", 115200)

    assert not driver.send_command("#000P1500T0200!")
    assert sum(len(port.writes) for port in created) == 1
    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [item["event"] for item in records] == ["serial_open", "command_write"]
