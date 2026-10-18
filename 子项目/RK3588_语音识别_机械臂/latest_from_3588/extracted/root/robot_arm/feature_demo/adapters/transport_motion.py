"""Completion gate for transport only; existing robot behavior is unchanged."""
from __future__ import annotations

import importlib
import os
import math
import time


class TransportMotionAdapter:
    """Reuse RobotAdapter, but never treat a serial write as physical completion.

    completion is a NEW integration hook, not an assumed legacy robot method.
    It receives (command, payload, result) and must verify actual completion.
    Software timing is separately opt-in, under the user's 2026-10-18 approval.
    """
    def __init__(self, robot, *, completion=None, completion_basis='feedback'):
        self._robot = robot
        self._completion = completion
        self.completion_basis = completion_basis

    def preflight(self):
        if self._completion is None:
            raise RuntimeError('当前机械臂驱动只返回发送结果，缺少可靠的动作完成反馈；'
                               '初始化和自动搬运已拦截，请先接入并验证完成判断。')
        validate = getattr(self._completion, 'validate', None)
        if callable(validate):
            validate()

    def command(self, name, payload):
        self.preflight()
        if (name, payload.get('name')) not in {('pose', '直立'), ('sequence', '搬运')}:
            raise ValueError('本模块只允许已有直立姿态和通用搬运动作。')
        result = self._robot.command(name, payload)
        if (self.completion_basis == 'software_timing' and name == 'sequence'
                and result.get('ok') is True and not self._robot.wait_for_motion_idle()):
            raise RuntimeError('原驱动仍处于忙碌状态，禁止接续直立。')
        completed = result.get('ok') is True and self._completion(name, payload, result) is True
        return {**result, 'completed': completed, 'completion_basis':self.completion_basis,
                'physical_verified':completed and self.completion_basis == 'feedback'}

    def disconnect(self):
        self._robot.disconnect()

    @property
    def can_release_fault(self):
        return self.completion_basis == 'software_timing' and self._robot.motion_idle


def build_transport_motion(robot):
    # Explicit extension for the real feedback implementation after hardware audit.
    # Never infer completion from ok, is_moving, estimated PWM or elapsed seconds.
    target = os.getenv('AIBOX_TRANSPORT_COMPLETION_PLUGIN', '').strip()
    completion = None
    basis = 'feedback'
    if target:
        module_name, attribute = target.split(':', 1)
        completion = getattr(importlib.import_module(module_name), attribute)
        if not callable(completion):
            raise ValueError('动作完成反馈插件必须为可调用函数。')
    elif os.getenv('AIBOX_TRANSPORT_COMPLETION_MODE') == 'legacy_timed':
        completion = LegacyTimedCompletion()
        basis = 'software_timing'
    return TransportMotionAdapter(robot, completion=completion, completion_basis=basis)


def _timing_config():
    from .robot import _legacy_factories
    _legacy_factories()  # Establish the same legacy root as RobotAdapter.
    return importlib.import_module('config')


class LegacyTimedCompletion:
    """User-authorized software criterion; NEVER reports physical verification.

    The existing synchronous sequence handles its saved steps. After it returns,
    wait the full configured final command duration, rather than assuming the
    last serial write has already finished. No trajectories are changed.
    """
    def __init__(self, *, config_loader=_timing_config, waiter=time.sleep):
        self._loader, self._waiter = config_loader, waiter
        self._durations = None

    def validate(self):
        if self._durations is not None:
            return
        config = self._loader()
        pose = float(config.PRESET_POSES['直立']['time']) / 1000
        steps = config.ACTION_SEQUENCES['搬运']
        final = steps[-1]
        transfer = float(final.get('time', 0)) / 1000 if 'time' in final else float(final['sleep'])
        if not all(math.isfinite(value) and 0 < value <= 30 for value in (pose, transfer)):
            raise ValueError('既有动作时长配置无效，拒绝执行。')
        self._durations = {('pose','直立'):pose, ('sequence','搬运'):transfer}

    def __call__(self, command, payload, result):
        self.validate()
        if result.get('ok') is not True:
            return False
        # Sequence has already returned AND the original driver is idle. The
        # requested recovery pause is exactly one additional second.
        self._waiter(1.0 if command == 'sequence' else self._durations[(command, payload['name'])])
        return True
