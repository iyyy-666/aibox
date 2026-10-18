"""One utterance, one confirmed block, one existing transfer sequence."""
from __future__ import annotations

import re
import threading
import time
from typing import Callable


COLOR_LABELS = {'red': '红色', 'green': '绿色', 'yellow': '黄色', 'blue': '蓝色'}
_COLOR_CODES = {label: code for code, label in COLOR_LABELS.items()}
_PREFIX = r'(?:请|麻烦|帮我|请帮我|麻烦帮我)?'
_TARGET = r'(?P<color>红色|绿色|黄色|蓝色)(?:物块|方块|积木)'
_DESTINATION = r'(?:到|至)传送带(?:上)?(?:吧|呀|啊)?'
_PATTERNS = [
    re.compile(_PREFIX + r'搬运' + _TARGET + _DESTINATION),
    re.compile(_PREFIX + r'(?:把|将)' + _TARGET + r'(?:搬运|搬|移)' + _DESTINATION),
]


def parse_transport_command(text: str) -> str | None:
    clean = re.sub(r'[\s，。！？、,.!?；;：:]', '', text or '')
    for pattern in _PATTERNS:
        match = pattern.fullmatch(clean)
        if match:
            return _COLOR_CODES[match['color']]
    return None


class TransportWorker:
    def __init__(self, *, robot, vision, gimbal, gimbal_target,
                 voice_factory: Callable, event_sink: Callable,
                 detection_timeout: float = 4.0, stable_hits: int = 3):
        if detection_timeout <= 0 or stable_hits < 1:
            raise ValueError('检测等待时间和连续确认帧数必须为正数。')
        self._robot = robot
        self._vision = vision
        self._gimbal = gimbal
        self._gimbal_target = gimbal_target
        self._voice_factory = voice_factory
        self._event_sink = event_sink
        self._timeout = detection_timeout
        self._stable_hits = stable_hits
        self._guard = threading.Condition(threading.RLock())
        self._voice_lifecycle = threading.Lock()
        self._voice = None
        self._voice_generation = 0
        self._accepting = False
        self._start_thread = None
        self._task_thread = None
        self._initialization_thread = None
        self._cancel = threading.Event()
        self._target_confirmed = False
        self._candidate = None
        self._hits = 0
        self._started = False
        self._closing = False
        self._busy = False
        self._locked = False
        self._phase = 'initializing'
        self._listening_status = '未监听'
        self._message = '等待初始化。'
        self._raw = ''
        self._color = ''
        self._last_event = {}
        self._vision_started = False
        self._verification_active = False
        self._last_observation = 0.0
        self._camera_error = ''
        self._software_timing = getattr(robot, 'completion_basis', '') == 'software_timing'

    @property
    def last_event(self):
        with self._guard:
            return dict(self._last_event)

    def snapshot(self):
        with self._guard:
            return {'transport': True, 'phase': self._phase,
                    'listening_status': self._listening_status,
                    'raw': self._raw, 'target_color': self._color,
                    'target_label': COLOR_LABELS.get(self._color, '未指定'),
                    'block_confirmed': self._target_confirmed,
                    'verification_active': self._verification_active,
                    'completion_label': '软件时序，未验证物理到位' if self._software_timing else '动作完成反馈',
                    'busy': self._busy, 'locked': self._locked,
                    'message': self._message}

    def _emit(self, event_type='transport_status'):
        # Called under the same lock as state changes: late status cannot reorder.
        with self._guard:
            event = {'type': event_type, **self.snapshot()}
            self._last_event = event
            self._event_sink(event)

    def _state(self, phase, message):
        self._phase, self._message = phase, message
        self._emit()

    @staticmethod
    def _require_completed(result):
        if result.get('ok') is not True or result.get('completed') is not True:
            raise RuntimeError(result.get('message') or '机械臂动作完成状态未确认。')

    def start(self):
        with self._guard:
            if self._started:
                return
            if self._closing:
                raise RuntimeError('模块已关闭。')
            self._state('initializing', '正在检查机械臂完成反馈。')
        try:
            self._robot.preflight()
            with self._guard:
                self._state('positioning', '摄像头定位中。')
            result = self._gimbal.move_to(*self._gimbal_target)
            if result.get('ok') is not True:
                raise RuntimeError(result.get('message') or '摄像头定位失败。')
            self._vision.start()
            self._vision_started = True
            with self._guard:
                self._busy = True
                self._state('standing', '机械臂恢复直立中，初始化尚未完成。')
                # Process readiness is published BEFORE any arm trajectory. Startup
                # watchdogs can only terminate the pre-motion setup phase.
                self._emit('ready')
                self._initialization_thread = threading.Thread(target=self._initialize_motion,
                    name='transport-initialize', daemon=False)
                self._initialization_thread.start()
        except Exception as error:
            with self._guard:
                self._locked = True
                self._state('initialization_error', str(error))
            raise

    def _initialize_motion(self):
        try:
            with self._guard:
                if self._camera_error:
                    self._busy = False
                    self._locked = True
                    self._state('initialization_error', self._camera_error)
                    return
            self._require_completed(self._robot.command('pose', {'name': '直立'}))
            with self._guard:
                self._busy = False
                if self._camera_error:
                    self._locked = True
                    self._state('initialization_error', self._camera_error)
                else:
                    self._started = True
                    self._state('waiting', ('直立动作组时序已执行，未验证物理到位。' if self._software_timing else '初始化完成。') + '请点击开启监听。')
        except Exception as error:
            with self._guard:
                self._locked = True
                self._state('fault', f'初始化直立完成状态未确认：{error}；请人工确认安全状态。')

    def command(self, name, payload):
        if name == 'start_listening':
            return self._start_listening()
        if name == 'stop_listening':
            return self._stop_listening()
        if name == 'prepare_exit':
            with self._guard:
                self._release_finished_fault()
                if self._busy and self._phase in {'standing', 'moving', 'recovering', 'fault'}:
                    return {'ok': False, 'message': '机械臂任务尚未安全结束，请等待完成或人工恢复后退出。'}
                self._closing = True
            self._stop_listening()
            return {'ok': True}
        raise ValueError(f'不支持的搬运命令：{name}')

    def _release_finished_fault(self):
        if self._phase != 'fault' or not self._software_timing:
            return
        if any(thread is not None and thread.is_alive()
               for thread in (self._initialization_thread, self._task_thread)):
            return
        if getattr(self._robot, 'can_release_fault', False):
            self._busy = False
            self._message = '异常任务已结束，允许退出；未确认搬运成功。'

    def _start_listening(self):
        with self._guard:
            if not self._started or self._closing or self._locked or self._busy:
                return {'ok': False, 'message': '当前未就绪或机械臂任务尚未结束。'}
            if self._listening_status in {'正在启动', '正在监听'}:
                return {'ok': True, **self.snapshot()}
            self._voice_generation += 1
            generation = self._voice_generation
            self._accepting = False
            self._listening_status = '正在启动'
            self._message = '正在启动离线语音识别。'
            self._emit()
            self._start_thread = threading.Thread(target=self._open_voice,
                args=(generation,), name='transport-listener-start', daemon=False)
            self._start_thread.start()
        return {'ok': True, **self.snapshot()}

    def _open_voice(self, generation):
        # Serialize open/close. Invalidate generation BEFORE waiting on this lock.
        with self._voice_lifecycle:
            voice = None
            try:
                with self._guard:
                    if generation != self._voice_generation or self._closing:
                        return
                if self._voice is not None:
                    self._voice.stop()
                    self._voice = None
                voice = self._voice_factory(lambda event: self._voice_event(generation, event))
                self._voice = voice
                result = voice.start_listening()
                if result.get('ok') is not True or result.get('listening') is not True:
                    raise RuntimeError(result.get('message') or '语音监听启动失败。')
                with self._guard:
                    if generation == self._voice_generation and not self._closing:
                        self._accepting = True
                        self._listening_status = '正在监听'
                        self._message = '请说：搬运蓝色物块到传送带上。'
                        self._emit()
                        return
                # Stop or a reader error may invalidate startup while load/read
                # succeeds. Never publish listening for that obsolete session.
                voice.stop()
                if self._voice is voice:
                    self._voice = None
            except Exception as error:
                with self._guard:
                    if generation == self._voice_generation:
                        self._accepting = False
                        self._listening_status = '监听错误'
                        self._message = str(error)
                        self._emit()
                if voice is not None:
                    voice.stop()
                    self._voice = None

    def _stop_listening(self):
        with self._guard:
            self._voice_generation += 1
            self._accepting = False
            if self._phase == 'detecting':
                self._cancel.set()
                self._guard.notify_all()
            self._listening_status = '正在停止'
            self._emit()
        try:
            with self._voice_lifecycle:
                if self._voice is not None:
                    self._voice.stop()
                    self._voice = None
        except Exception as error:
            with self._guard:
                self._listening_status = '监听错误'
                self._message = str(error)
                self._emit()
            raise
        with self._guard:
            self._listening_status = '已停止'
            self._emit()
        return {'ok': True, **self.snapshot()}

    def _voice_event(self, generation, event):
        with self._guard:
            if generation != self._voice_generation or self._closing:
                return
            if event.get('type') == 'error':
                self._voice_generation += 1
                self._accepting = False
                self._listening_status = '监听错误'
                self._message = str(event.get('message') or '语音识别失败。')
                self._emit()
                return
            if event.get('type') != 'speech' or not self._accepting or self._busy or self._locked:
                return
            # Parse the actual transcript; legacy short-command correction may lose intent.
            self._raw = str(event.get('raw') or event.get('normalized') or '')
            color = parse_transport_command(self._raw)
            if color is None:
                self._color = ''
                self._target_confirmed = False
                self._message = '识别失败，请重新说出完整搬运指令及一种目标颜色。'
                self._emit()
                return
            self._color = color
            self._accepting = False
            self._busy = True
            self._cancel.clear()
            self._hits = 0
            self._candidate = None
            self._target_confirmed = False
            self._verification_active = False
            self._state('detecting', f'正在识别{COLOR_LABELS[color]}物块。')
            self._task_thread = threading.Thread(target=self._run_task,
                name='transport-task', daemon=False)
            self._task_thread.start()

    def observe_blocks(self, detections):
        with self._guard:
            if self._phase != 'detecting' or self._cancel.is_set() or not self._verification_active:
                return
            self._last_observation = time.monotonic()
            self._target_confirmed = False
            matches = [item for item in detections if item.get('is_block') is True
                       and item.get('color') == self._color]
            # Multiple possible grasp targets are ambiguous at the fixed position.
            if len(matches) != 1:
                self._hits, self._candidate = 0, None
                return
            box = tuple(matches[0].get('box', ()))
            if len(box) != 4:
                self._hits, self._candidate = 0, None
                return
            same = self._candidate is not None and all(
                abs(a - b) <= max(8, box[2] * .15) for a, b in zip(box, self._candidate))
            self._hits = self._hits + 1 if same else 1
            self._candidate = box
            if self._hits >= self._stable_hits:
                self._target_confirmed = True
                self._guard.notify_all()

    def component_event(self, event):
        if event.get('type') in {'ready', 'stopped'}:
            return
        with self._guard:
            if event.get('type') in {'error', 'camera_reconnecting'}:
                self._camera_error = str(event.get('message') or '摄像头不可用。')
                self._target_confirmed = False
                self._hits, self._candidate = 0, None
                if self._phase == 'detecting':
                    self._cancel.set()
                    self._message = str(event.get('message') or '摄像头不可用。')
                    self._guard.notify_all()
            elif event.get('type') == 'camera_recovered':
                self._camera_error = ''
            # Only the transport startup path may report fatal startup errors.
            # Camera errors during a pose must not trigger WorkerProcess kill.
            event_type = 'frame' if event.get('type') == 'frame' else 'transport_status'
            self._event_sink({**event, 'component_type': event.get('type'),
                              'type': event_type, **self.snapshot()})

    def _run_task(self):
        try:
            # One session accepts one command. Close capture outside its callback thread.
            with self._voice_lifecycle:
                if self._voice is not None:
                    self._voice.stop()
                    self._voice = None
            with self._guard:
                self._voice_generation += 1
                if self._listening_status != '监听错误':
                    self._listening_status = '已停止'
                self._verification_active = True
                self._hits, self._candidate = 0, None
                self._target_confirmed = False
                self._emit()
                deadline = time.monotonic() + self._timeout
                while not self._cancel.is_set() and not (
                    self._target_confirmed and time.monotonic() - self._last_observation < .5
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._busy = False
                        self._verification_active = False
                        self._state('not_found', f'未发现对应颜色的物块：{COLOR_LABELS[self._color]}。请重新开启监听。')
                        return
                    self._guard.wait(remaining)
                if self._cancel.is_set():
                    self._busy = False
                    self._verification_active = False
                    self._state('waiting', '本次识别已取消，等待操作。')
                    return
                self._verification_active = False
                self._state('moving', '正在执行搬运。')
            self._require_completed(self._robot.command('sequence', {'name': '搬运'}))
            with self._guard:
                self._state('recovering', '搬运动作组执行结束，正在恢复直立。' if self._software_timing else '搬运已确认完成，正在恢复直立。')
            self._require_completed(self._robot.command('pose', {'name': '直立'}))
            with self._guard:
                self._busy = False
                self._state('completed', ('搬运及直立动作组执行结束，未验证物理到位。' if self._software_timing else '搬运完成，机械臂已恢复直立。') + '请重新开启监听。')
        except Exception as error:
            with self._guard:
                self._locked = True
                self._state('fault', f'执行异常：{error}；请人工确认安全状态。')

    def stop(self):
        with self._guard:
            self._release_finished_fault()
            # Keep control and task ownership if a trajectory might still be active.
            if self._busy and self._phase in {'standing', 'moving', 'recovering', 'fault'}:
                raise RuntimeError('机械臂任务尚未安全结束，暂不能退出。')
            self._closing = True
        self._stop_listening()
        for thread in (self._initialization_thread, self._start_thread, self._task_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5)
                if thread.is_alive():
                    raise TimeoutError('搬运模块后台任务尚未退出。')
        if self._vision_started:
            self._vision.stop()
            self._vision_started = False
        else:
            self._gimbal.close() if hasattr(self._gimbal, 'close') else None
        # No stop_motion()/shutdown(): stopping speech must never interrupt a trajectory.
        self._robot.disconnect()
        with self._guard:
            self._started = False
            self._emit('stopped')
