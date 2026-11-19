# COST-309 调用状态只读核查

2026-11-17。本地/受控非生产运维工具新增调用状态清单，复用既有 `model_cost_report.py`，
不新增 API、账本或迁移，不改变学生或家长的数据访问范围。

## 使用

```powershell
uv run python tools/model_cost_report.py --invocations --limit 50
uv run python tools/model_cost_report.py --invocations --limit 50 --after-invocation <上一页next_cursor>
```

使用原有环境数据库配置。生产环境仍拒绝运行；表不存在或记录损坏时失败，
不自动建表，不输出连接信息、损坏内容或半份 JSON。
清单模式不能与恢复事件的 `--resume-attempt`、`--reason`、`--apply` 组合，
在连接数据库之前拒绝混合操作。原有不带清单参数的成本报告/显式复核行为保留。

`invocations.items` 只含调用 ID、会话/文档上下文类别、状态、fence、UTC 额度日，以及
尝试的 ID、状态、保守预占和已有的 recover_after。原始 metadata 不直接输出，
不包含学生标识/预算账户、会话/文件资源摘要、请求指纹、提示、图片或响应正文。
读取前复用调用状态机的 Schema/状态/fence 校验，并核对 SQL 主键与元数据调用 ID。

按不可变调用 ID 升序分页，每页默认 50、最大 200，游标必须为 32 位小写十六进制。
ID 顺序不代表发生时间；各页是读取当时的状态，不是跨页冻结快照。
所有状态均可列出，包括 cancelled_unsent、closed_unknown 和 stale，
避免把“业务已关闭”误当成“供应商费用已确认”。清单不改变记录，不重发、不退款，
不会把保守预占当成实际账单或把未知发送当成零次发送。

## 验证

- `var/cost309-report-red.log`：最初 10 项因清单函数/CLI 参数缺失失败。
- `var/cost309-report-final.log`：扩大到包含文档未知尝试、非法游标类型和损坏 CLI 输出的相关 48 项通过。
- `var/cost309-final.log`：报告、成本事件、换讲/OCR 持久恢复和变异运行器最终 84 项通过。
- `var/cost309-mysql.log`：显式隔离 MySQL 上实际迁移、分页无重复/遗漏、前后记录相等，1 项通过、无跳过。
- `var/cost309-mutations/mutation-evidence-adtrpqpu/summary.json`：删除游标边界、绕过 Schema/状态验证、允许混合恢复的 3 项变异均捕获。
- `var/cost309-source-verification.json`：380 份隔离源恢复，并与主区逐字节一致。
- `var/cost309-cli-result.json`：真实命令行子进程两页均退出 0，返回 a/b 两个自编调用且数据库记录不变；使用临时 SQLite，无真实供应商请求。
- 全仓 Ruff 与五个相关文件格式检查通过。本轮未改页面、公开响应或契约；未重跑 Flutter/后台/浏览器或宣称它们为本轮新证据。

## 待办

这只是定位和核查入口，不是供应商账单对账、恢复授权或自动结算服务。
旧独立 SDK 的逐 attempt 持久记录、跨尝试恢复、供应商侧结果查询/账单关联仍待；
真实价格、授权评测与生产留存依赖保持原计划，COST-301 和全项目目标继续开放。
