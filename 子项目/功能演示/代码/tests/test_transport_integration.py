from types import SimpleNamespace
import threading

import pytest

from feature_demo.manager import ModuleManager, ModuleConflictError
from feature_demo.models import ModuleState
from feature_demo.registry import get_module
from feature_demo.resources import ReleaseReport
from feature_demo.workers.runtime import create_worker


def test_transport_registry_reserves_all_shared_hardware_and_keeps_fixed_view():
    module = get_module('voice_transport')
    assert module.visual
    assert set(module.resources) == {'camera', 'gimbal', 'robot', 'microphone', 'asr'}
    assert module.commands == ('start_listening', 'stop_listening')


def test_only_transport_gets_longer_utterance_capture_for_complete_commands():
    from feature_demo.app import _default_worker_factory
    transport = _default_worker_factory(get_module('voice_transport'))
    ordinary = _default_worker_factory(get_module('voice_robot_arm'))
    assert transport._environment['VOICE_MAX_RECORD_SEC'] == '8'
    assert 'VOICE_MAX_RECORD_SEC' not in ordinary._environment


def test_factory_checks_completion_before_any_hardware_initialization(monkeypatch):
    from feature_demo.workers import transport_runtime
    monkeypatch.setattr(transport_runtime, 'build_transport_vision',
                        lambda builder: SimpleNamespace(set_observer=lambda observer: None))
    worker = create_worker('voice_transport', event_sink=lambda event: None,
                           cv2_module=SimpleNamespace(), robot_adapter=SimpleNamespace())
    with pytest.raises(RuntimeError, match='完成反馈'):
        worker.start()
    assert worker.snapshot()['phase'] == 'initialization_error'


class Managed:
    pids = ()
    stopped = False
    allow_exit = False
    def start(self):
        pass
    def command(self, name, payload):
        assert name == 'prepare_exit'
        return {'ok': self.allow_exit, 'message': '机械臂仍在搬运'}
    def stop(self, timeout):
        self.stopped = True
    def snapshot(self):
        return {'alive': True}


def test_manager_does_not_force_kill_a_busy_transport_worker(tmp_path):
    worker = Managed()
    manager = ModuleManager(worker_factory=lambda module: worker,
        verifier=SimpleNamespace(verify=lambda *args: ReleaseReport(ok=True)),
        lock_path=tmp_path / 'lock')
    manager.start_module('voice_transport')
    result = manager.stop_module('voice_transport')
    assert result.state == ModuleState.RUNNING
    assert manager.active_module == 'voice_transport'
    assert not worker.stopped
    with pytest.raises(ModuleConflictError):
        manager.start_module('color_recognition')
    worker.allow_exit = True
    assert manager.stop_module('voice_transport').state == ModuleState.IDLE
    assert worker.stopped


def test_real_process_rejection_is_returned_as_running_not_exit_server_error(tmp_path):
    class Rejecting(Managed):
        def command(self,name,payload):
            raise RuntimeError('机械臂任务尚未安全结束')
    worker=Rejecting()
    manager=ModuleManager(worker_factory=lambda module:worker,
        verifier=SimpleNamespace(verify=lambda *args:ReleaseReport(ok=True)),lock_path=tmp_path/'reject.lock')
    manager.start_module('voice_transport')
    result=manager.stop_module('voice_transport')
    assert result.state==ModuleState.RUNNING
    assert '尚未安全结束' in result.message
    assert not worker.stopped
    manager._process_lock.release()


def test_unified_application_serves_home_and_lists_transport_without_hardware(tmp_path):
    from fastapi.testclient import TestClient
    from feature_demo.app import build_application
    app, manager = build_application(lock_path=tmp_path / 'app.lock')
    with TestClient(app) as client:
        assert client.get('/health').json() == {'ok': True}
        assert client.get('/').status_code == 200
        modules = client.get('/api/modules').json()['modules']
        assert next(m for m in modules if m['module_id'] == 'voice_transport')['visual'] is True
        assert manager.active_module is None


def test_twenty_switches_keep_transport_and_other_modules_isolated(tmp_path):
    created = []
    def factory(module):
        worker = Managed()
        worker.allow_exit = True
        created.append(worker)
        return worker
    manager = ModuleManager(worker_factory=factory,
        verifier=SimpleNamespace(verify=lambda *args: ReleaseReport(ok=True)),
        lock_path=tmp_path / 'switch.lock')
    for name in ['voice_transport', 'color_recognition', 'voice_robot_arm', 'robot_button'] * 5:
        assert manager.start_module(name).state == ModuleState.RUNNING
        assert manager.stop_module(name).state == ModuleState.IDLE
        assert created[-1].stopped
        assert manager.active_module is None


def test_reused_voice_engine_keeps_full_sentence_and_releases_pcm():
    from feature_demo.workers.voice import VoiceWorker
    heard = threading.Event()
    closed = threading.Event()
    events = []
    class Engine:
        def load(self):
            return True
        def set_commands(self, commands):
            self.commands = commands
        def recognize_pair(self, audio):
            return '搬运蓝色物块到传送带上', '搬运'
        def stop(self):
            pass
    class PCM:
        reads = 0
        def read(self):
            if self.reads == 0:
                self.reads += 1
                return 1, b'utterance'
            closed.wait(1)
            return 0, b''
        def close(self):
            closed.set()
    engine = Engine()
    def sink(event):
        events.append(event)
        if event['type'] == 'speech':
            heard.set()
    voice = VoiceWorker('ai_assistant', event_sink=sink,
                        engine_factory=lambda: engine, pcm_factory=PCM)
    try:
        voice.start_listening()
        assert heard.wait(1)
        assert engine.use_command_grammar is False
        assert engine.commands == {}
        assert next(e for e in events if e['type'] == 'speech')['raw'] == '搬运蓝色物块到传送带上'
    finally:
        voice.stop()
    assert closed.is_set()
