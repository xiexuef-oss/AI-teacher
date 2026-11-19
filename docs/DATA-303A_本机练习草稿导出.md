# DATA-303A 本机练习草稿导出

“我的 → 隐私与数据 → 导出本机练习草稿”由学生主动下载 JSON。资料或选项加载失败时也保留入口；读取本机内容和下载不请求导出 API。

范围是当前学生在本设备保存的练习作答、笔迹、冲突与恢复副本。只从当前归属键读取并通过 LocalDraft 解析，再以 toJson 白名单输出，不导出登录信息、幂等命令或原始日志。账号切换会取消尚未交付的导出，即使切回相同学生，也不继续旧操作。

共享 owner 队列防止本 isolate 的写入与读取交错；不宣称跨标签页或进程原子快照。损坏或未知格式导致整次失败，不修改源数据、不提供静默缺项的文件。当前内存文件上限 32 MiB，超限明确失败；不支持将 JSON 导回应用。导出不是迁移或灾备恢复。

## 验证（2026-11-17）

- 缺少导出读取函数的初始红测试：`var/local-draft-export-red.log`。
- 资料失败时入口消失的红测试：`var/local-draft-export-offline-red.log`；修复后导出专项 16 项通过：`var/local-draft-export-offline-green.log`。
- 全量 Flutter 631 项通过：`var/local-draft-export-full-flutter-final.log`；静态检查无问题：`var/local-draft-export-full-analyze-final.log`。
- 联调工具 103 项与 Ruff 通过：`var/local-draft-export-tooling.log`。
- 新构建 Web 发布版：`var/local-draft-export-web-build.log`。
- 真实 Chromium/本地 API：`var/local-draft-export-browser.log`，8/8。通过页面产生并保存作答，再拦截 API 请求并冷加载“我的”，实际接收下载，校验范围、归属、作答、无凭据、源存储不变及交付提示。API 被拦截不等于整机断网。
- 下载文件和截图：`var/e2e-local-draft-export-20261117/local_draft_export/`。截图已查看，导出入口与状态可读，无布局溢出。

## 仍待完成

DATA-303 的云端完整个人数据导出与 DATA-304 删除没有因此完成；原生系统保存窗口、最新 Android/iOS 包仍需设备验收。新入口没有新增公开 API 或改变服务端数据，未重复生成契约包。
