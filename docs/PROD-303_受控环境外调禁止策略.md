# PROD-303 受控环境外调禁止策略

2026-11-17。维持受控 dev/staging 禁止外调的既有范围，补齐瞬时可用性检查漏洞；
不启用生产环境，不改变本地显式持久外调的授权边界，不增加 API、迁移或依赖。

## 问题与修复

原 managed 配置门控检查 `external_calls_possible`。它会受到候选 enabled、环境变量、
报价和熔断器的当前状态影响；注入的网关即使允许外调，也可能因为暂时无可用候选而
通过检查。稍后条件改变，单次持久 seam 就可能发送，违背受控环境禁止外调的约定。

现在启动同时检查注入网关的外调配置意图，不能用禁用候选、缺失配置或熔断暂时掩盖它。
受控生命周期另外绑定单向的禁止外调策略；修改普通开关、候选配置或再次要求持久调用
均不能放宽该策略。检查放在候选解析处，覆盖准备单次计划、消费已有计划及旧 invoke。

另补供应商类型一致性检查：当前 OpenAI 兼容供应商必须标为 external，Mock 不得标为
external。加载时拒绝不一致配置；候选解析时也复核缓存对象，避免运行中直接修改
external 标记绕过发送/费用保护。已有三份路由配置均通过新的加载校验。

网关只维护一个发送模式：独立 SDK 默认 legacy；本地应用绑定 durable；受控应用绑定
disabled。模式只能收紧，避免独立布尔值组合出互相矛盾的权限。模式不是客户端配置，
请求不能修改它。单次 seam 依旧须由持久编排器先提交 dispatch/预算；本修复不替代它。

本地默认外调开关仍关闭。显式启用本地持久换讲/OCR时，既有配置、SQL 回执、稳定密钥、
预算和发送/恢复规则保留；prod 继续无条件拒绝启动。

## 验证

- `var/prod303-intent-red.log`：dev/staging × 禁用候选/缺环境变量/熔断，六项因没有拒绝配置而失败。
- `var/prod303-dispatch-red.log`：持久开关开启/关闭两项，复现绑定后切换开关及重绑策略仍发送。
- `var/prod303-gateway.log`：网关、配置/生命周期及既有成本保护 300 项通过，含本地真实 HTTP 持久调用回归。
- `var/prod303-provider-kind-red.log` 和 `var/prod303-provider-cache-red.log`：供应商误标两项和缓存对象改标一项先失败；最终相关303项通过，见 `var/prod303-gateway-final.log`。
- `var/prod303-managed-real.log`：显式隔离 MySQL/Redis 与完整迁移上，dev/staging 两项实际启动、健康及三类调用入口保护通过，无跳过；脚本适配器调用数为零。
- `var/prod303-managed-regression.log`：完整受控启动及辅导事务相关真实 MySQL/Redis 27 项通过，无跳过，进程退出 0。
- `var/prod303-mutations/mutation-evidence-6xbnj53u/summary.json`：配置意图、生命周期绑定、发送前解析、禁止策略不可放宽和供应商类型加载/缓存一致性六项变异均捕获；`var/prod303-source-verification.json` 的380份隔离源恢复并与主区一致。
- `var/prod303-existing-final-mutations/mutation-evidence-h26ylv8q/summary.json`：最终源上既有持久入口三项变异复验通过；`var/prod303-precharge-final-mutations/mutation-evidence-b1zt3a9w/summary.json`：发送前保守记账六项变异复验通过。共15项相关变异捕获，不冒称全仓290项都已执行；之后再次核对380份隔离源与主区一致。

`var/prod303-full-backend.log`：全量后端2840项通过、134项可选基础设施未配置而跳过，进程退出0。
该次收集早于供应商类型一致性三项补强，不能把它冒称为补强后的全仓重跑；补强后完整网关/接线303项独立补验。
`var/prod303-managed-final.log`：供应商类型补强后，最终源再跑实际dev/staging接线两项通过。
全仓Ruff、九个相关文件格式、契约生成新鲜度及290项变异源片段存在性检查通过。
全部本轮进程已终态，状态见`var/prod303-status.json`。测试没有真实供应商请求。

## 保留范围

不是 MySQL 模型业务接入完成，也不是生产许可。受控环境的外部换讲仍不开放，
Q-03/Q-04/Q-07、正式队列/存储、授权评测和账单对账待办均保持总计划。
