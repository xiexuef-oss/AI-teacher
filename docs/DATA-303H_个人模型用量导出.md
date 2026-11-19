# DATA-303H 个人模型用量导出

2026-11-17，工程增量。复用GET /profile/learning-export及现有学生端服务端学习记录下载，不新增入口、依赖、数据表或外部调用。全项目目标继续开放。

## 范围

契约先追加可选model_usage字段；新服务始终返回，旧文件缺失表示未提供该范围。format_version保持1。服务端只从当前token身份与当前服务端密钥派生伪名，不接受客户端指定学生或伪名；沿用student_ctx角色门控、禁止查询参数及同一数据库读取快照。

- calls：当前伪名对应的现存调用时间、任务类别、状态、供应商尝试次数、输入/输出Token、图像计量和估算成本。未知计量保留null，不伪造零。
- budget_days：仅scope=student且scope_key为本人当前伪名的日期、请求计数、预算估算和更新时间。即使platform桶的key碰巧等于本人伪名，也不能导出。
- 不包含伪名、数据库ID、request/trace ID、供应商及模型内部标记、错误细节、提示词、图像、内部恢复metadata、平台预算或其他学生记录。
- history_complete=false，identity_scope=current_server_pseudonym，costs_are_billing=false。密钥轮换前的记录不能凭猜测关联，空集合不证明从未调用。
- 调用估算与预算保守预占分别保留，不能相加当作实际账单；不释放未知调用预算、不写库、不续期、不清理记录。
- 两类记录均计入原共享10000条及32MiB上限；超限拒绝整个导出，不悄悄截断。

Q-07留存、去关联和密钥轮换历史仍待冻结。本增量没有补造旧密钥映射，不开启真实模型调用、生产运行或删除接口。

## 验证

先加契约与3项失败测试，因缺少model_usage及预算未计入总数而失败，日志var/data303h-red.log。实现后扩充到5项API测试，覆盖本人/他人/旧密钥/平台桶、未知计量、只读、家长403、密钥轮换与估算分离。

- 契约及相关API：317项通过，var/data303h-contract-api.log。
- 实际隔离MySQL/Redis：3项通过，包含预算桶筛选及受控dev/staging无proto扫描，var/data303h-managed.log。
- Dart契约286项、后台432项、typecheck/check:api、Flutter751项及dart analyze通过。Dart/TypeScript由契约重新生成，148份响应样例重新导出。
- 浏览器工具与变异运行器144项通过，var/data303h-tooling.log。
- 新增5项ModelUsageExport变异全部捕获，逐项检查JUnit实际failure且无error；927份隔离快照文件恢复，受影响实现/契约/测试/运行器与当前源码一致。证据var/data303h-raw-verification.json。后补的真实MySQL回归另有独立通过记录，不混作原快照内容。

首轮新Web实际下载49项通过，证据var/e2e-data303h-final/local_draft_export，下载JSON中model_usage可由生成的Dart类型完整传递，截图已查看。随后补充学生可见说明（估算非账单及历史不完整），30项相关widget测试、单文件格式和字体覆盖通过，最终新Web复验49项全部通过，最终档案var/e2e-data303h-final-r2/local_draft_export；最终analyze与生成一致性、Ruff通过。后端全量仍须以本轮运行终态日志为准，不能用以上专项数量替代。最新已构建Android包仍不包含DATA-303F/G/H；没有真机安装、手写笔或iPad验收。

后端全库已终态：2982通过、148项可选环境跳过，退出0（var/data303h-full-backend.log及-exit.json）。本次收集早于后补真实MySQL回归，该回归另有3项通过记录；本轮未跑完整旧变异矩阵，五项新增变异已专项验证。
