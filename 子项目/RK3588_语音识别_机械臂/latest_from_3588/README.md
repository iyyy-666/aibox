# latest_from_3588

这是 2026-09-24 从 RK3588 拉下来的当前业务快照。

## 内容

- `ai_box_latest_business_code.tar.gz`：业务代码压缩包
- `extracted/`：展开后的文件
- `model_manifest.txt`：模型清单
- `asset_manifest.txt`：资源清单

## 说明

- 这里只保留业务代码和必要入口。
- 大模型、音频资源、历史备份、`__pycache__`、`.pyc` 没有当作默认上下文。
- 包含统一“功能演示”软件、必要启动脚本和服务配置。
- 运行时关节位置、日志和缓存不纳入快照。
- 需要具体文件时，再进入 `extracted/` 对应路径。
