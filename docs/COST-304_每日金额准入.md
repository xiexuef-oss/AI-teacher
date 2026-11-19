# COST-304 每日估算金额准入候选

状态：2026-11-17，已按基线哈希合入15个文件。主区371项相关回归、真实MySQL3项及4项专项变异通过；金额配置默认null，外部调用默认禁用。

复用 `model_budget_usage` 现有金额列及 dispatch 短事务，不增加表、迁移或预算框架。配置增加可空的 `student_daily_max_cost_micros`、`platform_daily_max_cost_micros`，默认均为null，不由Agent指定额度。值必须是非负整数，不能以布尔、字符串或小数冒充。OCR账户桶沿用原student命名，但主体是创建任务的审核员，不赋予其学生权限。

持久dispatch在原平台→账户锁序下同时检查请求数和“已记账／预占估算＋本次预占≤限额”；等于限额可准入。任一范围不足则意图、页面发送标记、两个预算桶全部回滚；结果未知不退预占。UTC日界在实际准入时固定，跨日使用新桶，旧日记录保留。换讲和文档OCR均传递当前服务端配置，客户端不能指定额度。

配置日金额限额必须启用持久调用；旧invoke没有持久金额预占时明确返回既有BUDGET_UNAVAILABLE，不冒充已执行限额校验。null维持旧行为。不会启用任何供应商，也不改变模型、端点、密钥或价格。计入的是配置价格下的估算，不能保证实际账单绝不超限；供应商用量超过预占继续记录差额并遵守COST-303暂停策略，不回溯撤回已发送请求。

证据：初始10项失败/4项通过（`var/daily-cost-red.log`）；候选相关回归371项通过（`var/daily-cost-stage-regression.log`）；真实隔离MySQL3项通过，含学生／平台两组8线程仅一笔准入（`var/daily-cost-mysql.log`）；DailyCost 4/4变异捕获、无skip或无效基线（`var/daily-cost-mutations/mutation-evidence-hi58irf6/summary.json`）。835个变异快照文件恢复哈希一致（`var/daily-cost-source-verification.json`），候选Ruff通过。未在真实用户数据库或供应商执行操作。

合入只应用13个原文件增量及2个新增测试，未整目录覆盖；15个文件与已测候选哈希一致（`var/daily-cost-integration-verification.json`）。主区回归见`var/daily-cost-integrated-regression.log`，真实MySQL见`var/daily-cost-integrated-mysql.log`，Ruff通过。此前后端2606项全量和仍运行的233项快照变异不包含本增量，不能冒称当前237项完整门禁。

原主区冻结已解除：后端全量已终态，变异运行在独立固定快照，不会被主区改动污染。后续工程继续分别记录源码切片和相关验证，不因快照检查长时间阻断已授权的可执行开发。
