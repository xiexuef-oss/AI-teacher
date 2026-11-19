# DATA-303B 服务端学习记录导出

后续现状：LEARN-301D已补本人摸底计划及SQLite/MySQL读取快照；DATA-303C已补本人现存授权/邀请记录，并明确历史不完整。DATA-303D又补本人现存拍题文字（不含原图/已清理历史，受控范围null）。以下保留本切片初始范围与验收记录，最新行为以对应专篇为准。

2026-11-17。“我的 → 隐私与数据 → 导出服务端学习记录”，需联网，主动保存 JSON。复用本机草稿导出的保存/取消/错误处理与身份切换保护，统一为 StudentDataExportSection；本机草稿按钮继续离线可用。

## 范围与边界

新增契约 `GET /profile/learning-export`，身份只来自 token，不接受 student_id 或筛选参数；家长和审核角色403。响应和已知错误禁止缓存。只读查询，不新建导出任务、回执或持久文件，不改学生作答、提交状态或 used_solution。

文件包括本人资料、全部已保存会话、作答与副本、同步笔迹、已保存自查选项、此前教学事件、复测列表与完成历史。复用现有响应序列化器的字段白名单；事件重新过教学 Schema。学生答案保留原文，主观题仍 pending，自查不折算分数；不通过导出解锁尚未请求的提示、解析或参考证明。教学事件本身已有的公开 trace/request 元数据保留，不是导出内部幂等命令或凭据。

明确排除登录凭据、运维日志、题库答案全集、本机未同步内容、媒体文件和家长授权记录。因此这是**服务端学习记录导出**，还不是完整个人数据请求、迁移备份或恢复功能；界面与文件 scope/excluded 均标明范围。DATA-303 完整个人数据导出、DATA-304 删除没有因此完成。

当前同步内存实现总计上限10000条源记录、序列化数据32 MiB，超限整次413，不返回静默截断文件。未来实际数据规模需要时改为流式导出；没有新增队列或存储依赖。并发修改可能导致读到不同时间的记录，不承诺跨表原子快照；读取失败不交付部分文件。原生保存对话框与最新平板/iPad包仍待设备验收。

## 验证

- 契约先行，接口缺失时4项红：`var/student-learning-export-red.log`；客户端缺少服务端入口参数的红：`var/student-learning-export-ui-red.log`。
- 8项 API 覆盖归属、只读、空记录、角色拒绝、参数拒绝、完整失败、written/experiment/proof 的 pending 与自查、真实复测完成历史。API/契约/变异执行器330项通过：`var/student-learning-export-contract.log`；API/浏览器工具111项通过：`var/student-learning-export-api-tooling-final.log`。
- 真实响应样例137份已重新导出，包含 student_learning_export；Dart生成包与后台TS类型重新生成，未手改g.dart。Dart273项通过：`var/student-learning-export-dart.log`。
- Flutter全量632项通过：`var/student-learning-export-full-flutter.log`；后补的服务端响应途中切换身份（含切回）与原有导出等8项通过：`var/student-learning-export-ui-final.log`。新一轮包含这两项的全量634项通过，见 `var/student-learning-export-full-flutter-final.log`。静态检查无问题：`var/student-learning-export-analyze-final.log`。
- 后台首次全量428通过/1多标签恢复断言失败，保留 `var/student-learning-export-admin-test.log`；单独复查该用例通过后，完整重跑429/429：`var/student-learning-export-admin-final.log`。未更改该既有用例或产品实现，不把一次复查作为失败根因证明。typecheck与check:api通过，见同前缀日志。
- 新Web发布构建通过：`var/student-learning-export-web.log`；Chromium实际下载服务端/本机文件、校验实际同步作答、凭据排除及API离线后重试行为14/14：`var/student-learning-export-browser.log`。产物与已查看截图在 `var/e2e-student-learning-export-20261117/local_draft_export/`。
- StudentExport归属/行数/字节3/3变异捕获：`var/student-learning-export-mutations/mutation-evidence-87wtxabq/summary.json`；361个快照文件全部恢复且主区6个变更源码一致：`var/student-learning-export-source-verification.json`。Ruff通过：`var/student-learning-export-ruff-final.log`。

本增量后端全量已终态：2658通过、120可选环境跳过，见 `var/student-learning-export-full-backend.log`。前一轮2642通过/120可选环境跳过，不覆盖本导出增量；本增量后收集的全量也不把可选环境skip当作验证成功。当前无真实模型调用或发布部署。
