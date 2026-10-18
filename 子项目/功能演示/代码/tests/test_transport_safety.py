import threading

import pytest

from feature_demo.workers.transport import TransportWorker
from tests.test_transport import Motion, Vision, Gimbal, Voice, wait_for


def test_initial_stand_unconfirmed_keeps_process_and_ownership():
    class InitialMotion(Motion):
        def command(self, name, payload):
            self.entered.set()
            assert self.release.wait(2)
            return {'ok': True, 'completed': False}
    motion = InitialMotion()
    motion.release.clear()
    worker = TransportWorker(robot=motion, vision=Vision(), gimbal=Gimbal(),
        gimbal_target=(1200, 1110), voice_factory=lambda sink: Voice(sink),
        event_sink=lambda event: None)
    start = threading.Thread(target=worker.start)
    start.start()
    try:
        assert motion.entered.wait(1)
        assert worker.command('prepare_exit', {})['ok'] is False
        assert worker.snapshot()['busy'] is True
        assert not motion.closed
    finally:
        motion.release.set()
        start.join(2)
    wait_for(lambda: worker.snapshot()['locked'])
    assert worker.snapshot()['phase'] == 'fault'
    assert worker.command('prepare_exit', {})['ok'] is False
    with pytest.raises(RuntimeError, match='安全'):
        worker.stop()


def test_detections_during_slow_microphone_close_are_not_usable():
    stopping, release = threading.Event(), threading.Event()
    voices = []
    class SlowVoice(Voice):
        def stop(self):
            stopping.set()
            assert release.wait(2)
    def factory(sink):
        voice = SlowVoice(sink)
        voices.append(voice)
        return voice
    motion = Motion()
    worker = TransportWorker(robot=motion, vision=Vision(), gimbal=Gimbal(),
        gimbal_target=(1200, 1110), voice_factory=factory,
        event_sink=lambda event: None, detection_timeout=.1, stable_hits=2)
    worker.start()
    wait_for(lambda: worker.snapshot()['phase'] == 'waiting')
    worker.command('start_listening', {})
    wait_for(lambda: worker.snapshot()['listening_status'] == '正在监听')
    voices[0].speak('搬运蓝色物块到传送带上')
    try:
        assert stopping.wait(1)
        for _ in range(3):
            worker.observe_blocks([{'color':'blue', 'is_block':True, 'box':[270,200,70,65]}])
        worker.observe_blocks([])
    finally:
        release.set()
    wait_for(lambda: not worker.snapshot()['busy'])
    assert len(motion.calls) == 1
    assert worker.snapshot()['phase'] == 'not_found'
    worker.stop()


def test_listener_error_during_start_is_not_overwritten_as_listening():
    class BrokenVoice(Voice):
        def start_listening(self):
            self.sink({'type':'error', 'message':'麦克风启动后读取失败'})
            return {'ok':True, 'listening':True}
    worker = TransportWorker(robot=Motion(), vision=Vision(), gimbal=Gimbal(),
        gimbal_target=(1200,1110), voice_factory=lambda sink: BrokenVoice(sink),
        event_sink=lambda event: None)
    worker.start()
    wait_for(lambda: worker.snapshot()['phase'] == 'waiting')
    worker.command('start_listening', {})
    worker._start_thread.join(1)
    assert worker.snapshot()['listening_status'] == '监听错误'
    worker.stop()


def test_missing_frame_revokes_stable_confirmation_before_commit():
    voices = []
    def factory(sink):
        voice = Voice(sink)
        voices.append(voice)
        return voice
    motion = Motion()
    worker = TransportWorker(robot=motion, vision=Vision(), gimbal=Gimbal(),
        gimbal_target=(1200,1110), voice_factory=factory,
        event_sink=lambda event: None, detection_timeout=.1, stable_hits=2)
    worker.start()
    wait_for(lambda: worker.snapshot()['phase'] == 'waiting')
    worker.command('start_listening', {})
    wait_for(lambda: worker.snapshot()['listening_status'] == '正在监听')
    voices[0].speak('搬运蓝色物块到传送带上')
    wait_for(lambda: worker.snapshot()['verification_active'])
    # Deterministically schedule the latest camera result before task commit.
    with worker._guard:
        for _ in range(2):
            worker.observe_blocks([{'color':'blue','is_block':True,'box':[270,200,70,65]}])
        assert worker.snapshot()['block_confirmed']
        worker.observe_blocks([])
        assert not worker.snapshot()['block_confirmed']
    wait_for(lambda: not worker.snapshot()['busy'])
    assert len(motion.calls) == 1
    worker.stop()


def test_finished_software_fault_can_exit_only_when_driver_is_idle():
    class SoftwareMotion(Motion):
        completion_basis='software_timing'
        can_release_fault=False
    motion=SoftwareMotion()
    motion.fail=True
    voices=[]
    def factory(sink):
        voice=Voice(sink)
        voices.append(voice)
        return voice
    worker=TransportWorker(robot=motion,vision=Vision(),gimbal=Gimbal(),
        gimbal_target=(1200,1110),voice_factory=factory,event_sink=lambda event:None,stable_hits=2)
    worker.start()
    wait_for(lambda:worker.snapshot()['phase']=='waiting')
    worker.command('start_listening',{})
    wait_for(lambda:worker.snapshot()['listening_status']=='正在监听')
    voices[0].speak('搬运蓝色物块到传送带上')
    wait_for(lambda:worker.snapshot()['verification_active'])
    for _ in range(2):
        worker.observe_blocks([{'color':'blue','is_block':True,'box':[270,200,70,65]}])
    wait_for(lambda:worker.snapshot()['phase']=='fault')
    worker._task_thread.join(1)
    assert worker.command('prepare_exit',{})['ok'] is False
    motion.can_release_fault=True
    assert worker.command('prepare_exit',{})['ok'] is True
    worker.stop()
    assert motion.closed
    assert len(motion.calls)==2  # No recovery or repeated transfer is invented.
