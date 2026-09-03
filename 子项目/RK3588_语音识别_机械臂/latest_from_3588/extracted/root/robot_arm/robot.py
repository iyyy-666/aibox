"""
机械臂控制 - KM1 6轴机械臂高层API
指令格式：
  单舵机: #000P1500T1000!
  全舵机: {G0000#000P1500T1000!#001P1500T1000!...#005P1500T1000!}
  急停:   $DST!
"""
import time
import threading
import json
from pathlib import Path
from serial_driver import SerialDriver
from config import (
    PRESET_POSES,
    ACTION_SEQUENCES,
    NUM_SERVOS,
    SERVO_NAMES,
    PWM_MIN,
    PWM_MAX,
    PWM_CENTER,
    SORTING_READY_PWMS,
    SORTING_GRIP_CLOSED,
    SORTING_GRIP_RELEASE,
    SORTING_RIGHT_BASE,
    SORTING_LEFT_BASE,
    save_custom_pose,
)


class RobotArm:
    """KM1机械臂控制器"""

    def __init__(self, serial_driver: SerialDriver):
        self.ser = serial_driver
        self.current_pose = "未知"
        self._moving = False
        self._mov_end = 0  # 运动预计结束时间戳
        self._rotating = {}  # 多关节旋转: {servo_id: thread}
        self._rot_offsets = [0] * NUM_SERVOS  # 每个舵机的偏移量
        self._servo_pwms = [1500] * NUM_SERVOS  # 当前每个舵机PWM值
        self._gripper_state = ""
        self._action_lock = threading.Lock()
        self._critical_action = False
        self._sorting_stages_file = Path(__file__).parent / "sorting_stages.json"
        self._last_pwms_file = Path(__file__).parent / "last_servo_pwms.json"
        self._load_last_pwms()

    def _load_last_pwms(self) -> None:
        try:
            data = json.loads(self._last_pwms_file.read_text(encoding="utf-8"))
            pwms = data.get("pwms", [])
            if len(pwms) == NUM_SERVOS:
                self._servo_pwms = [
                    max(PWM_MIN, min(PWM_MAX, int(pwm)))
                    for pwm in pwms
                ]
                self._rot_offsets = [pwm - PWM_CENTER for pwm in self._servo_pwms]
        except Exception:
            pass

    def _remember_pwms(self) -> None:
        try:
            self._last_pwms_file.write_text(
                json.dumps(
                    {"pwms": self._servo_pwms, "updated_at": time.time()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ---- 基础舵机控制 ----

    def set_servo(self, servo_id: int, pwm: int, time_ms: int = 500, allow_critical: bool = False) -> bool:
        """
        控制单个舵机
        servo_id: 0=底座, 1=肩部, 2=肘部1, 3=肘部2, 4=腕部, 5=夹爪
        pwm: 500~2500
        time_ms: 运动耗时
        """
        if self._critical_action and not allow_critical:
            return False
        pwm = max(PWM_MIN, min(PWM_MAX, pwm))
        self._servo_pwms[servo_id] = pwm
        self._rot_offsets[servo_id] = pwm - PWM_CENTER
        self._remember_pwms()
        cmd = f"#{servo_id:03d}P{pwm:04d}T{time_ms:04d}!"
        return self.ser.send_command(cmd)

    def set_all_servos(self, pwms: list[int], time_ms: int = 1000, skip_neg1: bool = True, allow_critical: bool = False) -> bool:
        """
        同步控制所有舵机（逐个发送，20ms间隔避免串口堵塞）
        skip_neg1: pwm=-1 的舵机跳过不发送（保持当前位置）
        """
        if self._critical_action and not allow_critical:
            return False
        ok = True
        for i, pwm in enumerate(pwms[:NUM_SERVOS]):
            if skip_neg1 and pwm < 0:
                continue
            pwm = max(PWM_MIN, min(PWM_MAX, pwm))
            self._servo_pwms[i] = pwm
            self._rot_offsets[i] = pwm - PWM_CENTER
            self._remember_pwms()
            if not self.ser.send_command(f"#{i:03d}P{pwm:04d}T{time_ms:04d}!"):
                ok = False
            time.sleep(0.02)
        self._mov_end = time.time() + time_ms / 1000.0 + 1.0  # 运动时间+1s
        return ok

    def set_all_servos_group(self, pwms: list[int], time_ms: int = 1000) -> bool:
        """
        使用群组指令同步控制所有舵机（一条指令包含6个舵机）
        格式: {G0000#000PxxxxTxxxx!#001PxxxxTxxxx!...#005PxxxxTxxxx!}
        """
        parts = ["{G0000"]
        for i, pwm in enumerate(pwms[:NUM_SERVOS]):
            pwm = max(PWM_MIN, min(PWM_MAX, pwm))
            self._servo_pwms[i] = pwm
            self._rot_offsets[i] = pwm - PWM_CENTER
            parts.append(f"#{i:03d}P{pwm:04d}T{time_ms:04d}!")
        parts.append("}")
        cmd = "".join(parts)
        self._remember_pwms()
        return self.ser.send_command(cmd)

    # ---- 预设姿势 ----

    def execute_pose(self, pose_name: str) -> bool:
        """执行预设姿势"""
        if pose_name not in PRESET_POSES:
            print(f"[机械臂] 未知姿势: {pose_name}")
            return False
        if self.is_moving or self.is_rotating:
            print(f"[机械臂] 忙碌中，忽略姿势: {pose_name}")
            return False
        if self.current_pose == pose_name:
            print(f"[机械臂] 已经是姿势: {pose_name}")
            return True

        pose = PRESET_POSES[pose_name]
        with self._action_lock:
            self._moving = True
            try:
                result = self.set_all_servos(pose["pwms"], pose["time"], allow_critical=True)
            finally:
                self._moving = False
        if result:
            self.current_pose = pose_name
            print(f"[机械臂] 执行姿势: {pose_name} - {pose['description']}")
        return result

    def get_pose_list(self) -> list[dict]:
        """获取所有预设姿势"""
        return [
            {"name": name, "pwms": info["pwms"], "time": info.get("time", 1500),
             "description": info.get("description", "")}
            for name, info in PRESET_POSES.items()
        ]

    def _sleep_interruptible(self, seconds: float):
        end = time.time() + seconds
        while self._moving and time.time() < end:
            time.sleep(min(0.1, end - time.time()))
        return self._moving

    def execute_sequence(self, seq_name: str) -> bool:
        """执行多步动作序列（如抓取=弯曲+闭合+上台）"""
        if seq_name not in ACTION_SEQUENCES:
            print(f"[机械臂] 未知序列: {seq_name}")
            return False
        if self.is_moving or self.is_rotating:
            print(f"[机械臂] 忙碌中，忽略序列: {seq_name}")
            return False
        if False and self.current_pose == seq_name:
            print(f"[机械臂] 已经完成序列: {seq_name}")
            return True
        steps = ACTION_SEQUENCES[seq_name]
        print(f"[机械臂] 执行序列: {seq_name} ({len(steps)}步)")
        result = False
        with self._action_lock:
            self._moving = True
            try:
                for i, step in enumerate(steps):
                    if not self._moving:
                        print(f"[机械臂] 序列已停止: {seq_name}")
                        return False
                    print(f"[机械臂]  步骤{i+1}: {step['desc']}")
                    if "sleep" in step:
                        if not self._sleep_interruptible(step["sleep"]):
                            print(f"[机械臂] 序列已停止: {seq_name}")
                            return False
                    else:
                        ok = self.set_all_servos(step["pwms"], step["time"], allow_critical=True)
                        if not ok:
                            print(f"[机械臂] 序列步骤{i+1}发送失败: {seq_name}")
                            return False
                    if not self._sleep_interruptible(0.3):
                        print(f"[机械臂] 序列已停止: {seq_name}")
                        return False
                result = True
            finally:
                self._moving = False
        if result:
            self.current_pose = seq_name
            print(f"[机械臂] 序列完成: {seq_name}")
        return result

    def prepare_sorting_pose(self, time_ms: int = 1200) -> bool:
        """Move to the old grab end position with the gripper open."""
        if self._critical_action or self.is_moving or self.is_rotating:
            return False
        with self._action_lock:
            self._moving = True
            ok = self.set_all_servos(SORTING_READY_PWMS, time_ms, allow_critical=True)
            self._moving = False
        if ok:
            self.current_pose = "分拣待命"
            self._gripper_state = "open"
        return ok

    def execute_sort_transfer(self, side: str) -> bool:
        """Pick one item, move it left/right, release it, and return ready."""
        if side not in {"left", "right"}:
            return False
        if self._critical_action or self.is_moving or self.is_rotating:
            return False

        stages = self.get_sorting_stages(side)
        if len(stages) != 6:
            print(f"[机械臂] {side} 转移阶段未录满 6 个，拒绝执行")
            return False
        steps = [
            (stage["pwms"], int(stage.get("time", 1500)), int(stage.get("time", 1500)) / 1000.0 + 0.25)
            for stage in stages
        ]

        with self._action_lock:
            self._critical_action = True
            self._moving = True
            ok = True
            for idx, (pwms, time_ms, wait_sec) in enumerate(steps, start=1):
                if not self.set_all_servos_group(pwms, time_ms):
                    print(f"[机械臂] {side} 第 {idx} 阶段发送失败")
                    ok = False
                    break
                if not self._sleep_interruptible(wait_sec):
                    print(f"[机械臂] {side} 第 {idx} 阶段等待中断")
                    ok = False
                    break
            if ok and not self._sleep_interruptible(1.0):
                print(f"[机械臂] {side} 第 6 阶段静置中断")
                ok = False
            if ok:
                ready_time_ms = 1200
                if not self.set_all_servos_group(SORTING_READY_PWMS, ready_time_ms):
                    print(f"[机械臂] {side} 回到就绪姿态失败")
                    ok = False
                elif not self._sleep_interruptible(ready_time_ms / 1000.0 + 0.25):
                    print(f"[机械臂] {side} 回到就绪姿态中断")
                    ok = False
            self._moving = False
            self._critical_action = False

        if ok:
            self.current_pose = "分拣待命"
            self._servo_pwms = list(SORTING_READY_PWMS)
            grip = self._servo_pwms[5]
            self._gripper_state = "open" if grip <= 1000 else "half" if grip < 1800 else "close"
        return ok

    def load_sorting_stages(self) -> dict:
        default = {"right": [], "left": []}
        if not self._sorting_stages_file.exists():
            return default
        try:
            data = json.loads(self._sorting_stages_file.read_text(encoding="utf-8"))
        except Exception:
            return default
        return {
            "right": list(data.get("right", []))[:6],
            "left": list(data.get("left", []))[:6],
        }

    def get_sorting_stages(self, side: str | None = None):
        data = self.load_sorting_stages()
        if side:
            stages = data.get(side, [])
            return [
                stage for stage in stages
                if stage.get("pwms") and len(stage.get("pwms", [])) == NUM_SERVOS
            ]
        return data

    def save_sorting_stage(self, side: str, stage: int, time_ms: int = 1500) -> dict:
        if side not in {"left", "right"} or stage < 1 or stage > 6:
            return {"success": False, "error": "side must be left/right and stage must be 1-6"}
        data = self.load_sorting_stages()
        stages = list(data.get(side, []))
        while len(stages) < 6:
            stages.append({})
        stages[stage - 1] = {
            "stage": stage,
            "pwms": list(self._servo_pwms[:NUM_SERVOS]),
            "time": int(time_ms),
            "saved_at": time.time(),
        }
        data[side] = stages
        self._sorting_stages_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "success": True,
            "side": side,
            "stage": stage,
            "pwms": stages[stage - 1]["pwms"],
            "time": int(time_ms),
        }

    def get_sequence_list(self) -> list[str]:
        """获取所有序列名称"""
        return list(ACTION_SEQUENCES.keys())

    def save_pose(self, name: str, pwms: list[int], time_ms: int = 1500) -> bool:
        """保存自定义姿势"""
        if not name or len(pwms) != NUM_SERVOS:
            return False
        save_custom_pose(name, pwms, time_ms)
        self.current_pose = name
        return True

    # ---- 快捷动作 ----

    def stop(self) -> bool:
        """急停"""
        self._moving = False
        self._mov_end = 0
        return self.ser.send_command("$DST!")

    def gripper_open(self, time_ms: int = 500) -> bool:
        """夹爪张开"""
        self._clear_stale_action_lock()
        if self._critical_action:
            return False
        self.stop_rotate(5)
        ok = self.set_servo(5, 800, time_ms, allow_critical=True)
        if ok:
            self._gripper_state = "open"
        return ok

    def gripper_close(self, time_ms: int = 500) -> bool:
        """夹爪闭合"""
        self._clear_stale_action_lock()
        if self._critical_action:
            return False
        self.stop_rotate(5)
        ok = self.set_servo(5, 2200, time_ms, allow_critical=True)
        if ok:
            self._gripper_state = "close"
        return ok

    def gripper_half(self, time_ms: int = 500) -> bool:
        """夹爪半开"""
        self._clear_stale_action_lock()
        if self._critical_action:
            return False
        self.stop_rotate(5)
        ok = self.set_servo(5, 1500, time_ms, allow_critical=True)
        if ok:
            self._gripper_state = "half"
        return ok

    def gripper_step(self, delta: int, time_ms: int = 180) -> bool:
        """夹爪微调"""
        self._clear_stale_action_lock()
        if self._critical_action:
            return False
        self.stop_rotate(5)
        target = max(PWM_MIN, min(PWM_MAX, int(self._servo_pwms[5] + delta)))
        ok = self.set_servo(5, target, time_ms, allow_critical=True)
        if ok:
            if target <= 1000:
                self._gripper_state = "open"
            elif target >= 1900:
                self._gripper_state = "close"
            else:
                self._gripper_state = "half"
        return ok

    def _clear_stale_action_lock(self) -> None:
        if self._critical_action and not self.is_moving and not self.is_rotating:
            self._critical_action = False

    def all_center(self, time_ms: int = 1000) -> bool:
        """全部复位到中心"""
        if self._critical_action:
            return False
        if self.current_pose == "复位" and not self.is_moving:
            print("[机械臂] 已经复位")
            return True
        self._rot_offsets = [0] * NUM_SERVOS
        self._servo_pwms = [1500] * NUM_SERVOS
        ok = self.set_all_servos([1500]*6, time_ms, allow_critical=True)
        if ok:
            self.current_pose = "复位"
            self._gripper_state = "half"
        return ok

    # ---- 手动步进控制 ----

    def move_servo_step(self, servo_id: int, delta: int, time_ms: int = 200) -> bool:
        """
        步进移动单个舵机。
        delta: 正数=增加角度, 负数=减少角度
        """
        self._clear_stale_action_lock()
        if servo_id < 0 or servo_id >= NUM_SERVOS:
            return False
        if self._critical_action:
            return False
        self.stop_rotate(servo_id)
        current = int(self._servo_pwms[servo_id])
        target = max(PWM_MIN, min(PWM_MAX, current + int(delta)))
        ok = self.set_servo(servo_id, target, time_ms, allow_critical=True)
        if ok:
            self.current_pose = "手动微调"
            if servo_id == 5:
                if target <= 1000:
                    self._gripper_state = "open"
                elif target >= 1900:
                    self._gripper_state = "close"
                else:
                    self._gripper_state = "half"
        return ok

    def hold_current_position(self, time_ms: int = 500) -> bool:
        """启动或重连后给舵机发一次当前位置PWM，让舵机上力保持。"""
        self._clear_stale_action_lock()
        if self._critical_action:
            return False
        pwms = list(self._servo_pwms[:NUM_SERVOS])
        ok = self.set_all_servos(pwms, time_ms, allow_critical=True)
        if ok:
            self.current_pose = "上电保持"
        return ok

    # ---- 状态 ----

    @property
    def is_moving(self) -> bool:
        import time
        return time.time() < self._mov_end

    # ---- 关节旋转 ----
    def start_rotate(self, servo_id: int, direction: int) -> bool:
        """启动指定关节旋转: servo_id 0-5, direction 1=+/cw, -1=-/ccw"""
        return self.move_servo_step(servo_id, 60 * (1 if direction > 0 else -1), 180)

    def stop_rotate(self, servo_id: int) -> bool:
        """停止指定关节旋转"""
        if servo_id in self._rotating:
            self._rotating[servo_id] = False
            del self._rotating[servo_id]
        return True

    def _joint_rotate_loop(self, servo_id: int, step: int):
        import time as _t
        off = self._rot_offsets[servo_id]
        while self._rotating.get(servo_id):
            off += step
            off = max(-700, min(700, off))
            self._rot_offsets[servo_id] = off
            pwm = 1500 + off
            self._servo_pwms[servo_id] = pwm
            self.ser.send_command(f"#{servo_id:03d}P{pwm:04d}T100!")
            _t.sleep(0.1)

    @property
    def is_rotating(self) -> bool:
        return len(self._rotating) > 0

    def get_rotating_joints(self) -> list:
        return list(self._rotating.keys())

    def status(self) -> dict:
        return {
            "current_pose": self.current_pose,
            "servo_count": NUM_SERVOS,
            "servo_names": SERVO_NAMES,
            "pwm_range": [PWM_MIN, PWM_MAX],
            "serial_connected": self.ser.connected,
            "is_moving": self.is_moving,
            "is_rotating": self.is_rotating,
            "gripper_state": self._gripper_state,
            "available_poses": [
                {"name": name, "description": info["description"]}
                for name, info in PRESET_POSES.items()
            ],
            "servo_pwms": self._servo_pwms,
            "rot_offsets": self._rot_offsets,
        }

