# COST-303 超预占事件与共享暂停

状态：2026-11-17，本地／受控预发工程切片已合入；暂停读取已覆盖服务器旧invoke、单次计划及重试／回退。公开 API 不变，生产发布仍拒绝。真实报价、账单核对、外部告警投递和旧invoke逐attempt持久预算／告警结算尚未完成，不能据此关闭 COST-301。

## 策略与边界

`TUTOR_MODEL_COST_OVERRUN_POLICY=record_only` 为默认值；持久调用结算后的用量估算超过发送时的预占，记录一条内部事件，但不自动暂停。
显式设为 `pause_platform` 时，同时暂停共享数据库里后续的持久 dispatch 准入；该策略必须配合 `TUTOR_DURABLE_MODEL_INVOCATIONS_ENABLED=true`、稳定去标识密钥和正式 SQL 回执，缺一则拒绝启动。两种策略都不启用供应商或改变价格。

暂停保存在数据库，其他实例、重启、UTC跨日以及把配置改回 record_only 都不会绕过它。已经取得 dispatch 许可或已经在途的请求无法据此保证撤回；发生在暂停前的调用仍须结算，未知用量不退款。

金额是供应商用量乘配置价格得出的估算，**不是实际账单**；输入估算与图像定价的准确性仍须独立核验。模型正文超预占时拒绝应用的既有规则不变。

## 数据与原子性

追加迁移015，不修改014。`model_budget_incidents` 用稳定 attempt ID 去重，只存 `contracts/model_budget_incident.schema.json` 允许的摘要、日期、预占／观察估算金额、策略和复核元数据；禁止原始提示、响应、图像、供应商地址和密钥。`model_dispatch_gate` 保存共享暂停及当前事件ID。

结算时，共享门控→意图→平台／账户预算→事件按固定顺序加锁，审计、差额、事件和暂停一起提交；失败全部回滚。dispatch先取得应用上下文锁，再共享门控、意图和预算锁，暂停拒绝会回滚同事务的页面标记与预算。managed启动只检查迁移和结构，不创建表或自动升级；本地显式持久调用初始化可创建这三张内部表。

完全相同的审计重放不重复插事件，不加费用，也不会在复核解除后再次触发暂停。暂停期间迟到的另一笔超预占会更新当前事件；使用旧事件ID不能解除新的暂停。

## 共享发送检查与结构精简

服务器统一在初始化入口检查成本表并绑定网关，只枚举一次表清单；发现部分成本表则拒绝启动。已有015表时，即使关闭持久调用开关也继续读取暂停；旧原型尚无成本表时保留原行为，不自动建表。只有服务端启动代码可绑定检查，客户端请求不能指定或绕过。

首次旧调用在消费请求额度前检查，并在每次实际发送前重查；单次计划、退避后的重试及跨候选回退都受约束。新事务只读暂停状态，不为查询创建／锁定门控行，不跨网络持锁。明确暂停返回既有BUDGET_EXCEEDED，数据库故障返回BUDGET_UNAVAILABLE且不输出异常连接信息；此前已获许可／在途调用的边界不变。

本轮还移除OCR的动态hasattr判断，让本地和持久检查点使用同一invoke接口；Mock、失败、空输出与正常输出共享一个完成写入位置。CLI恢复参数改为“要么全部提供，要么全部不提供”，操作行为不变。相关回归353项及真实MySQL/Redis集成8项通过（`var/simplify-pause-final-regression.log`、`var/simplify-pause-real-infra.log`）；SharedPause 4/4、OCR恢复6/6和CostPause 3/3专项变异均捕获，无跳过或无效基线；833个隔离快照文件恢复哈希通过，Ruff通过（`var/simplify-source-verification.json`、`var/simplify-final-ruff.log`）。这些是相关行为保护，不宣称全仓库233项变异已通过。

## 本地操作工具

在目标开发／预发配置下只读检查：

```powershell
uv run python tools/model_cost_report.py
```

输出最多50条经Schema验证的内部事件（`--limit`可设1至200），不创建表、不调用模型、不向外发送消息。数据库不存在或缺迁移时报告固定错误，不打印连接串或异常细节；prod环境拒绝执行。

核对当前事件、配置价格和供应商用量后，才执行明确的解除操作，事件ID取自报告中的 `incident_id`：

```powershell
uv run python tools/model_cost_report.py --resume-attempt <当前32位事件ID> --reason pricing_corrected --apply
```

固定复核原因还可选 `provider_usage_verified`、`configuration_changed`；不保存自由文本。ID、原因和 `--apply` 必须同时提供，默认只读。解除和复核记录同事务，当前事件发生变化则拒绝；这不是公开管理员权限接口，不把本地操作员当作真实认证方案。

## 证据与后续

- 首轮新增7项因缺少功能失败，日志 `var/cost-overrun-red.log`；修复后初轮42项通过。
- 隔离相关回归428项通过（`var/cost-overrun-stage-regression.log`），随后新增启动策略／缺015不自动升级边界与成本单测17项通过（`var/cost-overrun-startup.log`）。
- 隔离真实MySQL／Redis集成8项通过，无跳过，覆盖015迁移、v1/v2并发、8线程重复结算、共享暂停拒绝、复核后准入，以及managed辅导与回执恢复（`var/cost-overrun-managed-real.log`）。
- 3/3 CostPause变异被捕获，无跳过／无效基线（`var/cost-pause-mutations/mutation-evidence-7xpn6nn3/summary.json`）；830个隔离快照文件恢复哈希一致，合入16个文件与该候选一致，当前229个变异锚点均唯一（`var/cost-overrun-source-verification.json`）。锚点有效不等于所有229项已运行。
- 主区合入回归466项通过（`var/cost-overrun-integrated-regression.log`），Ruff通过（`var/cost-overrun-main-ruff.log`）。此前完整后端2576通过/117可选环境跳过不包含最后OCR竞争修复和本成本增量；旧220项变异已结束：219项捕获，1项因Redis真实窗口休眠基线失败未执行；该结果不算完整通过，后续已改为隔离键可控过期／成员时间分数推进，真实Redis相关17项及REDIS-LIMIT 5/5变异通过（var/redis-window-controlled-expiry.log、var/redis-gate-repair-mutations.log），无基线失败；该补验不冒称一次全量通过。当前整合全量及完整变异另在执行。

后续继续处理旧入口逐attempt持久预算／告警结算、每日金额硬额度、真实供应商用量／报价核验和外部运维告警；真实身份、地域留存与生产策略仍由负责人冻结。测试仅用自编元数据和fake适配器，未对真实用户数据库执行迁移或解除暂停。
