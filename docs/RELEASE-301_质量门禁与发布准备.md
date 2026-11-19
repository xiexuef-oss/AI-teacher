# RELEASE-301 质量门禁与发布准备

最新本地Android测试包见RELEASE-301B：353份客户端源码/构建入口摘要一致，当前功能标记与签名已核对，构建前后ADB均无设备，未安装或发布。远端CI与正式签名条件仍未完成。

状态：本地门禁入口与手动 CI 准备；远端工作流尚未运行。`workflow_dispatch` 不是已完成的 PR 自动门禁。正式应用标识、签名与部署仍等待负责人及基础设施条件，不修改原有应用标识、不接入证书或模型凭据。

## 本地入口

按 README 准备现有工具链，以 `uv sync --locked`、审核后台 `npm ci`、Dart/Flutter `pub get --enforce-lockfile` 安装已有锁文件依赖，不升级依赖。

```powershell
uv run --locked python tools/run_quality_gates.py --list
uv run --locked python tools/run_quality_gates.py
```

Windows 默认使用已约定的 `C:/src/flutter/bin/flutter.bat` 与 `dart.bat`，其他系统从 PATH 查找；可通过 `--flutter`、`--dart`、`--uv`、`--npm` 提供可执行文件路径（不接受拼接的 shell 命令）。入口不安装依赖、不启动 API、不自动修改代码或生成契约。

默认按顺序执行：根目录 pytest、ruff check、Dart 契约生成 `--check`；学生端 flutter test、dart analyze；契约包 dart test；后台 npm test、typecheck、check:api。每一项结束后持续写入 `var/quality-gates/<本次运行>/status.json` 与独立日志；终端只输出状态和日志路径，不回显命令输出。失败后继续收集其他项的结果，缺工具、超时均失败，进程最终非零退出。报告中的 passed 仅表示该命令退出码为零，不代表真实基础设施、设备、外部模型已通过。

`--timeout` 设置每项超时秒数。`--output` 指向新的独立报告目录；已存在的目录拒绝覆盖，避免混用旧结果。`--list` 只展示命令，不产生通过报告。日志可能包含测试诊断内容，应按本地工程数据保管，不自动上传。不要给运行进程注入真实模型、生产数据库、签名或其他业务凭据。

## CI 前置与边界

`.github/workflows/quality.yml` 仅手动触发，需要专用 `self-hosted, Windows, X64, tutor-quality-isolated` runner。它不是已配置完成的 GitHub 托管环境。只执行已审查、可信分支；严禁为公共 fork 开启 self-hosted `pull_request` 或 `pull_request_target` 执行。runner 应是一次性隔离环境，无业务密钥、无生产网络访问和既有业务数据，运行后销毁，不能直接复用日常开发机。

runner 管理者需预先安装并核验 Python 3.12、uv、Node 22，以及项目当前 Flutter 3.47.9 / Dart 3.13.7（Windows 路径 `C:/src/flutter`）。当前未交付 SDK 下载器，未声称这些安装包或 runner 镜像已完成供应链校验。依赖安装可能访问包仓库；这与调用真实业务模型不同，外部模型仍按仓库配置关闭。

checkout 使用固定提交 `11bd71901bbe5b1630ceea73d27597364c9af683`，来自 [actions/checkout v4.2.2 官方发布](https://github.com/actions/checkout/releases/tag/v4.2.2)。只给 contents:read，检出不持久保存 token；不声明 secrets、不签名、不部署、不推送、不发布制品、不发外部消息。日志与 JSON 保留于 runner 的本地工作目录，应在销毁前由有权限的维护者按数据策略处理。GitHub job 结果会显示命令是否成功；报告并未上传为 GitHub artifact。

启用 PR 自动门禁之前还须确定可信 runner 方案和依赖供应链核验、运行远端工作流并保存证据，再配置分支保护；此处不能将它们标为完成。

## 后续发布验收

关键规则修改后单独执行 `tools/mutation_check.py`；页面流程变更建议执行 `tools/e2e/run.py`。它们会改动代码或启动服务，不由默认 runner 同时触发。真实 MySQL/Redis、对象存储及设备验收必须分别记录实际环境与结果，不以本地单元测试或跳过项替代。

本地Flutter Web、后台Web和Android profile已于2026-11-17构建并记录命令、源码清单、工具链与摘要，见RELEASE-301A。远端工作流未构建或上传发布包；正式Android applicationId/keystore、Apple bundle ID/账号证书和发布目标等待负责人，不生成占位生产签名。安装/设备验收与正式发布子项仍未完成。

## 本次验证证据

2026-11-16：新增测试先因 `run_quality_gates` 尚未实现而收集失败，再实现入口；`uv run --locked pytest -q tests/unit/test_quality_gates.py` 最终 5 passed（存在既有 Starlette TestClient 弃用警告）。定向 `ruff check` 与 `ruff format` 完成；实际 `--list` 正常列出九项且不执行门禁。测试使用临时目录与短生命周期 Python 子进程，没有连接业务基础设施。

此证据仅验证门禁编排行为；尚未通过此入口执行完整九项门禁，GitHub 远端工作流也未运行。主线程的其他测试记录不自动归入本入口的通过报告。本工作包未调用子智能体，实际主线程模型标识未知。

后续整合已实际使用此入口执行wave2九项门禁，`var/quality-gates/project-wave2/status.json`为passed；日志含后端1937、Flutter388、Dart180、后台197及其余静态/生成检查。该批源码之后继续开发，不能拿这份历史报告替代最新源码复验。66专用环境用例在另一显式环境运行通过，不由默认pytest的skip计入；GitHub远端和正式签名部署仍未执行。
