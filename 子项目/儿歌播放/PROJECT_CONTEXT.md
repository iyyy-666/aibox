# 儿歌播放 - Project Context

更新时间：2026-08-30

## 1. 项目名称

儿歌播放

## 2. 项目位置

G:\codexwork\人工智能实验箱\子项目\儿歌播放

## 3. 项目目的

通过语音选择小星星或两只老虎并播放核心儿歌片段，带提示语音和前端歌词/状态显示。

## 4. 当前入口文件

代码/nursery_rhyme_player.py；启动脚本/nursery_rhyme_player.sh

## 5. 使用技术栈

Python, Tkinter, ASR, TTS/音频播放, ALSA

## 6. 当前完成状态

可用，音频资源在 RK3588 assets 中，当前备份保存资源清单。

## 7. 已知 bug / 待优化点

历史上出现过提示音太小、TTS 不统一、识别歌名不准；退出应回到重新询问状态。

## 8. 依赖关系

共享：voice_engine.py, audio_playback.py, audio_config.py。资源见 asset_manifest.txt。

## 9. 维护规则

- 修改本软件前先读本文件。
- 代码目录保存从 RK3588 最新运行环境拉取的业务文件副本。
- 启动脚本目录保存 /usr/local/bin 中对应脚本。
- 桌面入口目录保存 /home/ztl/Desktop 中对应 .desktop 文件。
- 公共模块优先查看 子项目/共享模块与资源。
- 涉及硬件的软件，测试前先确认对应麦克风、声卡、摄像头、串口或机械臂已连接。
