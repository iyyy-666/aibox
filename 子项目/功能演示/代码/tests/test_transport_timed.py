from types import SimpleNamespace
import pytest
from feature_demo.adapters.transport_motion import LegacyTimedCompletion, TransportMotionAdapter


def config():
    return SimpleNamespace(PRESET_POSES={'直立': {'time':1500}},
        ACTION_SEQUENCES={'搬运':[{'time':1000}, {'sleep':1.5}, {'time':2200}]})


def test_authorized_software_completion_waits_configured_last_step_only_after_success():
    waits, calls = [], []
    completion = LegacyTimedCompletion(config_loader=config, waiter=waits.append)
    class Robot:
        def wait_for_motion_idle(self):
            calls.append(('wait_idle', {}))
            return True
        def command(self, name, payload):
            calls.append((name, payload))
            return {'ok':True}
    motion = TransportMotionAdapter(Robot(), completion=completion, completion_basis='software_timing')
    result = motion.command('sequence', {'name':'搬运'})
    assert waits == [1.0]
    assert calls == [('sequence', {'name':'搬运'}), ('wait_idle', {})]
    assert result['completed'] is True
    assert result['physical_verified'] is False
    assert result['completion_basis'] == 'software_timing'
    motion.command('pose', {'name':'直立'})
    assert waits == [1.0, 1.5]


def test_failed_serial_send_never_becomes_timed_success():
    waits = []
    completion = LegacyTimedCompletion(config_loader=config, waiter=waits.append)
    motion = TransportMotionAdapter(SimpleNamespace(command=lambda *a: {'ok':False}),
                                   completion=completion, completion_basis='software_timing')
    assert motion.command('sequence', {'name':'搬运'})['completed'] is False
    assert waits == []


def test_bad_timing_config_is_rejected_before_motion():
    bad = config()
    bad.PRESET_POSES['直立']['time'] = float('nan')
    calls = []
    motion = TransportMotionAdapter(SimpleNamespace(command=lambda *a: calls.append(a)),
        completion=LegacyTimedCompletion(config_loader=lambda:bad, waiter=lambda sec:None))
    with pytest.raises(ValueError):
        motion.command('pose', {'name':'直立'})
    assert calls == []


def test_software_idle_timeout_never_sends_recovery_pose():
    class Robot:
        def command(self,*args):
            return {'ok':True}
        def wait_for_motion_idle(self):
            return False
    motion=TransportMotionAdapter(Robot(),completion=LegacyTimedCompletion(config_loader=config,waiter=lambda sec:None),completion_basis='software_timing')
    with pytest.raises(RuntimeError,match='忙碌'):
        motion.command('sequence',{'name':'搬运'})


def test_adapter_waits_original_busy_flag_without_sending_commands(monkeypatch):
    import feature_demo.adapters.robot as module
    checks=[]
    class Driver:
        _moving=False
        is_rotating=False
        @property
        def is_moving(self):
            checks.append(True)
            return len(checks)<3
    adapter=module.RobotAdapter()
    adapter._robot=Driver()
    waits=[]
    monkeypatch.setattr(module.time,'sleep',waits.append)
    assert adapter.wait_for_motion_idle() is True
    assert len(checks)==3
    assert waits==[.02,.02]
