from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gimbal_service import GimbalService


class FakeSerial:
    def __init__(self) -> None:
        self.writes = []
        self.is_open = True

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        pass

    def read(self, _size: int) -> bytes:
        command = self.writes[-1].decode("ascii")
        return f"ACK id={int(command[1:4])} pulse={int(command[5:9])}\n".encode("ascii")

    def close(self) -> None:
        self.is_open = False


def test_click_moves_only_one_clamped_step_and_persists_position(tmp_path) -> None:
    fake = FakeSerial()
    service = GimbalService(
        state_path=tmp_path / "position.json",
        serial_factory=lambda *_args, **_kwargs: fake,
        initial_yaw=1170,
        initial_pitch=1110,
    )

    ok, detail = service.move("yaw", 1, step_pwm=20)

    assert ok, detail
    assert fake.writes == [b"#001P1190T0350!\r\n"]
    assert service.position == (1190, 1110)
    assert '"yaw": 1190' in (tmp_path / "position.json").read_text(encoding="utf-8")


def test_default_click_step_is_40_pwm(tmp_path) -> None:
    fake = FakeSerial()
    service = GimbalService(
        state_path=tmp_path / "position.json",
        serial_factory=lambda *_args, **_kwargs: fake,
        initial_yaw=1170,
        initial_pitch=1110,
    )

    ok, detail = service.move("pitch", 1)

    assert ok, detail
    assert fake.writes == [b"#002P1150T0350!\r\n"]
