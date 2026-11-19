# COST-306 重试发送前重新准入

2026-11-17。旧 `ModelGateway.invoke` 在退避等待之前计算下次估算，等待结束后只重查图像报价完整性。期间撤销供应商授权、切换模型或删除路由，仍可能继续发送；报价上涨或请求限额收紧，也可能沿用旧估算和上限。

现在先等待，再以当前路由解析候选、核对原模型、读取当前报价和请求限额，最后经过共享暂停检查才发送。失效候选不发送、不增加 provider_calls；金额不足返回既有 BUDGET_EXCEEDED。此前已发送的失败/未知尝试保留估算，日请求计数不因重试重复增加。换讲单次计划与旧入口复用同一候选可用性检查，移除了重复遍历。

这不是逐 attempt 持久预算实现：旧入口的累计尝试估算仍在内存，未增加数据库预算记录，也不支持未知结果自动重发。配置每日金额限额时仍拒绝旧入口；正式换讲和文档 OCR 沿用已有持久单次发送路径。真实供应商默认禁用。

## 专项证据

- `var/retry-admission-red.log`：6 个场景全部失败（禁用、撤销审批、切模型、移除候选、涨价、收紧请求限额）。
- `var/retry-admission-green.log`：修复后的网关、启动接线、持久换讲、文档 OCR 共 277 项通过。
- `var/retry-admission-tooling.log`：变异执行器与 OCR 恢复 42 项通过；`var/retry-admission-ruff.log`：全仓 Ruff 通过。
- `var/retry-admission-mutations/mutation-evidence-r4d_52go/summary.json`：2/2；受共享检查影响的 `var/retry-image-quote-mutations/mutation-evidence-usi3qlto/summary.json`：3/3，无基线失败或无效目标。
- `var/retry-admission-source-verification.json`：独立变异快照 357 文件全部恢复，三个变更源码与主区一致。

专项测试用假适配器，不联系真实模型。模型环境变量变更使用自动还原的 monkeypatch，避免测试污染其他用例。当前后端全量结果单独记录，不将旧233项快照称为覆盖本增量的完整变异门禁。
