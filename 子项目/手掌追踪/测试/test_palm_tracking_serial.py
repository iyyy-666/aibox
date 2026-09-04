from palm_tracking_serial import SerialGimbalClient


class FakeSerial:
    def __init__(self, ack: bytes) -> None:
        self.ack = ack
        self.writes: list[bytes] = []
        self.is_open = True

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def flush(self) -> None:
        pass

    def read(self, _size: int) -> bytes:
        if b"\n" not in self.ack:
            data, self.ack = self.ack, b""
            return data
        line, self.ack = self.ack.split(b"\n", 1)
        return line + b"\n"

    def close(self) -> None:
        self.is_open = False


def make_client(fake: FakeSerial) -> SerialGimbalClient:
    return SerialGimbalClient(
        port="fake",
        baud=115200,
        yaw_id=1,
        pitch_id=2,
        pwm_min=500,
        pwm_max=2500,
        serial_factory=lambda *_args, **_kwargs: fake,
    )


def test_move_writes_pwm_frames_and_requires_matching_acks() -> None:
    fake = FakeSerial(b"ACK id=1 pulse=1510\nACK id=2 pulse=1490\n")
    client = make_client(fake)

    ok, _ = client.move(10, -10, time_ms=100)

    assert ok
    assert b"#001P1510T0100!\r\n" in fake.writes
    assert b"#002P1490T0100!\r\n" in fake.writes
    assert client.yaw_pwm == 1510
    assert client.pitch_pwm == 1490


def test_missing_ack_returns_false_and_keeps_last_confirmed_pwm() -> None:
    fake = FakeSerial(b"")
    client = make_client(fake)

    ok, _ = client.move(10, 0)

    assert not ok
    assert client.yaw_pwm == 1500
    assert client.pitch_pwm == 1500
    assert not fake.is_open


def test_pwm_targets_are_clamped_to_safe_range() -> None:
    fake = FakeSerial(b"ACK id=1 pulse=2500\n")
    client = make_client(fake)
    client.yaw_pwm = 2495

    ok, _ = client.move(100, 0)

    assert ok
    assert client.yaw_pwm == 2500
    assert b"#001P2500T0100!\r\n" in fake.writes


def test_move_waits_for_each_axis_ack_before_writing_next_axis() -> None:
    class OrderedFake(FakeSerial):
        def __init__(self) -> None:
            super().__init__(b"")
            self.events: list[str] = []
            self.responses = [b"ACK id=1 pulse=1510\n", b"ACK id=2 pulse=1490\n"]

        def write(self, data: bytes) -> None:
            self.events.append(f"write:{data[1:4].decode()}")
            super().write(data)

        def read(self, _size: int) -> bytes:
            self.events.append("read")
            return self.responses.pop(0) if self.responses else b""

    fake = OrderedFake()
    client = make_client(fake)

    assert client.move(10, -10, time_ms=100)[0]
    assert fake.events[:4] == ["write:001", "read", "write:002", "read"]
