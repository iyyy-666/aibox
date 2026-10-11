from aibox_studio.runner import RunRequest, Runner
import threading
import time


def test_runner_executes_student_code_in_child_process():
    request = RunRequest(
        code="from aibox import Arm\nArm().open()\nprint('完成')\n",
        allowed_imports=("aibox",),
        capabilities=("arm.open",),
        timeout_seconds=5,
        output_limit_bytes=4096,
    )

    result = Runner().run(request)

    assert result.status == "completed"
    assert result.stdout == "完成\n"
    assert result.events[-1]["action"] == "张开"


def test_runner_stops_before_launch_when_policy_rejects_code():
    request = RunRequest(
        code="import os\nprint(os.getcwd())\n",
        allowed_imports=("aibox",),
        capabilities=(),
        timeout_seconds=5,
        output_limit_bytes=4096,
    )

    result = Runner().run(request)

    assert result.status == "rejected"
    assert result.diagnostics[0].code == "IMPORT_NOT_ALLOWED"
    assert result.stdout == ""


def test_runner_terminates_code_that_exceeds_timeout():
    request = RunRequest(
        code="while True:\n    pass\n",
        allowed_imports=(),
        capabilities=(),
        timeout_seconds=0.2,
        output_limit_bytes=4096,
    )

    result = Runner().run(request)

    assert result.status == "timeout"


def test_runner_can_cancel_an_active_child_process():
    runner = Runner()
    request = RunRequest(
        code="while True:\n    pass\n",
        allowed_imports=(),
        capabilities=(),
        timeout_seconds=10,
        output_limit_bytes=4096,
    )
    result = []
    thread = threading.Thread(target=lambda: result.append(runner.run(request)))
    thread.start()
    deadline = time.monotonic() + 2
    while not runner.is_running and time.monotonic() < deadline:
        time.sleep(0.01)

    runner.cancel()
    thread.join(timeout=2)

    assert thread.is_alive() is False
    assert result[0].status == "cancelled"
