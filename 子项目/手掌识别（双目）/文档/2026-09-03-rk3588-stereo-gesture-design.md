# RK3588 双目手势与统一视觉优化设计

## 目标

在 RK3588 的双目摄像头 `/dev/video41` 上稳定框出手掌，并准确识别石头、剪刀、布。将双目拆分、候选过滤、稳定跟踪和异常恢复沉淀为公共能力，供手掌、颜色、形状、果实、车牌、人脸和相机预览程序复用。

## 运行基线与约束

- 维护基线：`rk3588_vision_voice_opt_20260830/current`。
- 板端环境：aarch64、Python 3.10.12、OpenCV 5.0.0，双目摄像头为 `/dev/video41`。
- `mediapipe` 当前未安装；`mediapipe==0.10.18` 提供 Python 3.10/aarch64 的官方 manylinux wheel。
- 不在应用启动时安装依赖，也不让 MediaPipe 成为其他视觉程序的必需依赖。
- 每个 GUI 应用仍独占摄像头；公共模块不创建后台共享摄像头服务。

## 公共视觉模块

新增独立公共模块，提供以下无 GUI、无业务副作用的接口：

- `split_stereo(frame)`：验证输入宽度后分离左、右目。
- `TargetRoi` 和候选过滤：中心 ROI、最小尺寸、面积比例、长宽比与边界检查。
- `StereoCandidate`：根据左右候选的归一化高度、面积比例和合理水平视差进行匹配，输出匹配状态与评分。
- `BoxTracker`：按 IoU 关联单目标轨迹，处理短暂丢帧。
- `TemporalGestureVote`：最近窗口投票，默认连续 4 帧确认；最多容忍 3 帧不确定或丢失后才清空。
- `CameraHealth`：摄像头打开失败、读帧失败与重连状态的统一辅助函数。

公共模块只共享图像几何和时序逻辑。颜色、形状、果实、车牌、人脸各自的检测模型、阈值与业务结果保持不变。

## 手掌识别管线

1. 采集线程读取 MJPG 双目帧，检测线程取得最新副本并拆分左右目。
2. 左目先经中心 ROI、亮度/运动/肤色轮廓候选筛选；候选只用于缩小或验证区域，不作为最终手掌框。
3. 按需加载 MediaPipe Hands，运行于左目候选区域或左目全帧。由 21 点关键点的外接框加安全边距生成手掌框。
4. 以关节方向、PIP/DIP 弯曲关系和指尖相对掌心的位置判断四根长手指的伸展状态。拇指只提高置信度，不决定三类分类。
5. 分类规则：四根长手指全弯曲为石头；食指与中指伸展、无名指与小指弯曲为剪刀；四根长手指伸展为布；其他状态为未确定。
6. 右目执行轻量候选验证，不进行第二次完整 MediaPipe 推理。匹配条件为接近的归一化高度、相近的面积比例和合理水平视差。匹配成功为高置信，失败时可显示检测框但不确认稳定手势。
7. 跟踪器关联连续手掌框，投票器仅在高置信分类连续达到阈值后显示石头、剪刀或布。短暂丢帧保持已确认结果，超过阈值后清空。

## MediaPipe 与降级

`HandLandmarkDetector` 仅在手掌应用中加载。初始化、推理或关键点校验任何阶段失败时：

- 将原因记录到状态栏和结构化诊断信息。
- 使用改进的传统视觉兜底：肤色与运动掩膜、形态学去噪、轮廓质量过滤、凸包缺陷和几何手势分类。
- 兜底结果也必须经过左右候选验证与时序投票，不能直接触发稳定结果。
- MediaPipe 可恢复时允许重新初始化；频繁失败时采用退避，避免阻塞 UI 或读帧线程。

## 各应用接入

- 手掌：接入全部公共组件与 MediaPipe/传统视觉双后端。
- 颜色、形状、果实、车牌、人脸：复用双目拆分、ROI、稳定过滤、读帧失败重连和统一状态显示；保留原检测器。
- 相机预览：复用安全双目拆分与读帧恢复，仅显示画面，不加载识别模型。
- 启动脚本继续通过环境变量保留每个应用的设备、分辨率、帧率、检测间隔和锁文件行为。

## 部署

1. 在 RK3588 上显式安装并验证 `mediapipe==0.10.18`，不修改其他应用依赖。
2. 部署公共模块、更新后的应用和启动脚本至 `/root/robot_arm` 与 `/usr/local/bin`。
3. 先执行语法检查和导入自检，再逐一启动桌面入口；同一时间只启动一个使用 `/dev/video41` 的 GUI。
4. 若 MediaPipe 安装或导入失败，保留传统视觉可运行状态并报告具体失败原因。

## 测试与验收

- 单元测试：左右目拆分、ROI 边界、候选匹配、IoU 跟踪、投票、短暂丢失、关节状态和三类手势分类。
- 回放测试：保存双目图像，覆盖室内明暗、不同距离、左/右手、旋转姿态、复杂背景和遮挡。检查手掌框和稳定分类。
- 板端测试：验证 MediaPipe 导入、摄像头打开/断开重连、手掌应用三类手势稳定识别及右目校验状态。
- 回归测试：颜色、形状、果实、车牌、人脸和相机预览均能启动、读帧并维持原有识别结果。

## 非目标

- 不增加机械臂动作映射。
- 不自动下载模型或安装系统包。
- 不实现多人手势交互；首版优先稳定跟踪一个主手掌。

## Validation Record

- 2026-09-03 local: 19 automated tests passed with Python 3.14.6, NumPy 2.5.2, and OpenCV 5.0.0.
- 2026-09-03 RK3588: verified Python 3.10.12, OpenCV 5.0.0, and MediaPipe 0.10.18 on aarch64.
- 2026-09-03 RK3588: `vision_targeting.py`, `hand_landmarks.py`, all six recognition applications, and `camera_view_app.py` passed `py_compile`; `/dev/video41` exists.
- 2026-09-03 RK3588: `HandLandmarkDetector` initialized successfully and returned zero detections for a blank frame, as expected.
- Pending physical acceptance: present rock, scissors, and paper in front of the camera to verify the landmark box, stereo verification state, and four-frame stable label under the actual installation lighting.
