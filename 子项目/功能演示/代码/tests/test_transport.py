"""Transport must never turn stale speech or unconfirmed motion into a move."""
import threading
import time

import pytest

from feature_demo.workers.transport import TransportWorker, parse_transport_command


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        threading.Event().wait(.005)
    assert predicate()


class Motion:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = False
        self.closed = False

    def preflight(self):
        pass

    def command(self, name, payload):
        self.calls.append((name, payload))
        if name == 'sequence':
            self.entered.set()
            assert self.release.wait(2)
            if self.fail:
                return {'ok': False, 'completed': False, 'message': '动作未完成'}
        return {'ok': True, 'completed': True}

    def disconnect(self):
        self.closed = True


class Voice:
    def __init__(self, sink):
        self.sink = sink
        self.starts = 0
        self.stops = 0

    def start_listening(self):
        self.starts += 1
        self.sink({'type': 'listening'})
        return {'ok': True, 'listening': True}

    def stop(self):
        self.stops += 1

    def speak(self, text):
        self.sink({'type': 'speech', 'raw': text, 'normalized': text})


class Vision:
    def start(self):
        pass

    def stop(self):
        pass


class Gimbal:
    def __init__(self):
        self.targets = []

    def move_to(self, *target):
        self.targets.append(target)
        return {'ok': True}


@pytest.fixture
def rig():
    motion, gimbal, events, voices = Motion(), Gimbal(), [], []
    def factory(sink):
        voice = Voice(sink)
        voices.append(voice)
        return voice
    worker = TransportWorker(robot=motion, vision=Vision(), gimbal=gimbal,
                             gimbal_target=(1200, 1110), voice_factory=factory,
                             event_sink=events.append, detection_timeout=.12,
                             stable_hits=2)
    worker.start()
    wait_for(lambda: worker.snapshot()['phase'] == 'waiting')
    yield worker, motion, gimbal, events, voices
    motion.release.set()
    if worker.snapshot()['locked']:
        with pytest.raises(RuntimeError, match='安全'):
            worker.stop()
    else:
        worker.stop()


@pytest.mark.parametrize(('text', 'color'), [
    ('搬运蓝色物块到传送带上。', 'blue'),
    ('请把红色物块搬运到传送带上', 'red'),
    ('帮我将绿色方块搬到传送带', 'green'),
    ('麻烦搬运黄色积木至传送带上吧！', 'yellow'),
])
def test_complete_intent_and_one_color_are_required(text, color):
    assert parse_transport_command(text) == color


@pytest.mark.parametrize('text', ['蓝色', '搬运物块', '搬运红色物块',
    '不要搬运红色物块到传送带上', '搬运红色和蓝色物块到传送带上',
    '能否搬运蓝色物块到传送带上', '搬运蓝色物块到传送带上然后搬运红色物块',
    '搬运紫色物块到传送带上', '取消搬运蓝色物块到传送带上'])
def test_incomplete_ambiguous_or_negated_commands_are_rejected(text):
    assert parse_transport_command(text) is None


def test_entry_positions_camera_and_stands_without_listening(rig):
    worker, motion, gimbal, _, voices = rig
    assert gimbal.targets == [(1200, 1110)]
    assert motion.calls == [('pose', {'name': '直立'})]
    assert voices == []
    assert worker.snapshot()['listening_status'] == '未监听'


def start_voice(rig):
    worker, _, _, _, voices = rig
    assert worker.command('start_listening', {})['ok']
    wait_for(lambda: worker.snapshot()['listening_status'] == '正在监听')
    return voices[-1]


def observe(worker, color='blue', **overrides):
    if worker.snapshot()['phase'] == 'detecting' and not worker.snapshot()['verification_active']:
        wait_for(lambda: worker.snapshot()['verification_active'] or worker.snapshot()['phase'] != 'detecting')
    detection = {'color': color, 'is_block': True, 'box': [270, 200, 70, 65]}
    worker.observe_blocks([dict(detection, **overrides)])


@pytest.mark.parametrize(('text', 'color'), [
    ('搬运蓝色物块到传送带上', 'blue'), ('搬运红色物块到传送带上', 'red'),
    ('搬运绿色物块到传送带上', 'green'), ('搬运黄色物块到传送带上', 'yellow')])
def test_one_command_uses_one_shared_motion_and_only_then_stands(rig, text, color):
    worker, motion, *_ = rig
    voice = start_voice(rig)
    voice.speak(text)
    observe(worker, color)
    observe(worker, color)
    wait_for(lambda: worker.snapshot()['phase'] == 'completed')
    assert motion.calls == [('pose', {'name': '直立'}),
                            ('sequence', {'name': '搬运'}), ('pose', {'name': '直立'})]
    assert worker.snapshot()['target_color'] == color


def test_start_is_idempotent_and_old_callback_after_stop_restart_is_ignored(rig):
    worker, motion, _, _, voices = rig
    old_voice = start_voice(rig)
    worker.command('start_listening', {})
    assert len(voices) == 1
    worker.command('stop_listening', {})
    assert old_voice.stops == 1
    assert worker.snapshot()['listening_status'] == '已停止'
    start_voice(rig)
    old_voice.speak('搬运蓝色物块到传送带上')
    observe(worker)
    observe(worker)
    assert len(motion.calls) == 1


@pytest.mark.parametrize('bad', ['搬运物块', '蓝色', '不要搬运蓝色物块到传送带上'])
def test_invalid_speech_never_creates_a_task(rig, bad):
    worker, motion, *_ = rig
    start_voice(rig).speak(bad)
    observe(worker)
    observe(worker)
    assert not worker.snapshot()['busy']
    assert len(motion.calls) == 1


@pytest.mark.parametrize('case', ['wrong_color', 'pixels_only', 'no_target', 'old_frame'])
def test_target_timeout_never_moves_and_allows_a_fresh_command(rig, case):
    worker, motion, *_ = rig
    if case == 'old_frame':
        observe(worker)
        observe(worker)
    voice = start_voice(rig)
    voice.speak('搬运蓝色物块到传送带上')
    if case == 'wrong_color':
        observe(worker, 'red')
        observe(worker, 'red')
    elif case == 'pixels_only':
        observe(worker, is_block=False)
        observe(worker, is_block=False)
    wait_for(lambda: worker.snapshot()['phase'] == 'not_found')
    assert len(motion.calls) == 1
    assert '蓝色' in worker.snapshot()['message']
    assert not worker.snapshot()['busy']
    start_voice(rig).speak('搬运黄色物块到传送带上')
    assert worker.snapshot()['phase'] == 'detecting'


def test_stop_during_detection_cancels_without_motion(rig):
    worker, motion, *_ = rig
    start_voice(rig).speak('搬运蓝色物块到传送带上')
    worker.command('stop_listening', {})
    observe(worker)
    observe(worker)
    wait_for(lambda: not worker.snapshot()['busy'])
    assert len(motion.calls) == 1


def test_stop_and_exit_during_motion_do_not_interrupt_or_disconnect(rig):
    worker, motion, *_ = rig
    motion.release.clear()
    voice = start_voice(rig)
    voice.speak('搬运蓝色物块到传送带上')
    observe(worker)
    observe(worker)
    assert motion.entered.wait(1)
    voice.speak('搬运红色物块到传送带上')
    worker.command('stop_listening', {})
    result = worker.command('prepare_exit', {})
    assert result['ok'] is False
    assert not motion.closed
    assert len(motion.calls) == 2
    motion.release.set()
    wait_for(lambda: worker.snapshot()['phase'] == 'completed')
    assert worker.snapshot()['listening_status'] == '已停止'
    assert worker.command('prepare_exit', {})['ok']


def test_failed_transfer_locks_and_never_stands_or_accepts_another_task(rig):
    worker, motion, *_ = rig
    motion.fail = True
    voice = start_voice(rig)
    voice.speak('搬运蓝色物块到传送带上')
    observe(worker)
    observe(worker)
    wait_for(lambda: worker.snapshot()['phase'] == 'fault')
    voice.speak('搬运红色物块到传送带上')
    assert len(motion.calls) == 2
    assert worker.snapshot()['locked']


def test_legacy_success_without_completion_is_not_success():
    from feature_demo.adapters.transport_motion import TransportMotionAdapter
    calls = []
    class Legacy:
        def command(self, *args):
            calls.append(args)
            return {'ok': True}
    motion = TransportMotionAdapter(Legacy())
    with pytest.raises(RuntimeError, match='完成'):
        motion.command('pose', {'name': '直立'})
    assert calls == []  # Unsupported completion is detected BEFORE sending motion.


def test_duplicate_callback_while_busy_never_queues_another_transfer(rig):
    worker, motion, *_ = rig
    voice = start_voice(rig)
    motion.release.clear()
    voice.speak('搬运蓝色物块到传送带上')
    voice.speak('搬运蓝色物块到传送带上')
    observe(worker)
    observe(worker)
    assert motion.entered.wait(1)
    voice.speak('搬运蓝色物块到传送带上')
    motion.release.set()
    wait_for(lambda: worker.snapshot()['phase'] == 'completed')
    assert len(motion.calls) == 3


def test_voice_failure_clears_true_listening_state(rig):
    worker, *_ = rig
    voice = start_voice(rig)
    voice.sink({'type': 'error', 'message': '麦克风断开'})
    assert worker.snapshot()['listening_status'] == '监听错误'
    assert worker.snapshot()['message'] == '麦克风断开'
