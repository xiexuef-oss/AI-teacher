# DATA-302 持久回执与 Redis 协调

此阶段提供可注入的正式SQL回执及Redis协调器，未解除main里的生产启动护栏，未将原型导入任务、身份或批次表搬进MySQL，也不代表全应用可生产运行。

## 权威与事务

`SqlReceiptStore` 使用正式 `idempotency_receipts` 表：actor_id、按actor隔离的key_digest、请求fingerprint、状态、HTTP状态、脱敏响应和时间。原始幂等键不落正式表。`(actor_id,key_digest)` 唯一约束是最终并发边界。

执行顺序：先读已完成回执；没有时，在当前业务事务里INSERT reserved并flush取得唯一键锁；之后才执行业务动作、写complete响应，最后同事务commit。reserved不单独提交。业务失败、异常或进程崩溃应回滚业务及占位。已有complete回执同请求重放，不同指纹409；异常提交的残缺回执明确拒绝自动执行。

唯一键冲突后先完整rollback，再以新事务查询已提交赢家，避免MySQL REPEATABLE READ旧快照及SQLAlchemy失败session污染。没有赢家的业务IntegrityError继续抛出，不误称成功重放，也不吞死锁、连接失败等fatal异常。

业务action不能自行commit或另开事务；Session before_commit守卫在回执完成之前拒绝提前提交，也拒绝嵌套回执事务。正式store明确拒绝 `/admin/import-jobs` 原型路径，避免其内部逐项commit把reserved提前提交。不能把不可事务化的网络副作用当成数据库事务的一部分：外部调用、outbox及供应商请求幂等仍需后续方案。

## 005及006：保留真实失败证据

005追加正式回执表，最初包含actor到users的FK。真实MySQL并发回归观察到1213死锁：插入回执的actor FK共享锁与业务更新同actor行的排他锁，以及另一事务等待同key唯一锁形成循环。

遵守迁移只追加，005未回写。006仅删除该FK，保留actor字段、actor/key唯一约束及历史。actor有效性由请求认证和授权校验负责；回执不赋予权限，注销账号不能借历史回执恢复访问。测试同时覆盖全部迁移clean install和005→006升级，确认只移除FK、唯一键仍在。

## Redis只协调

`RedisReceiptCoordinator` 接收已配置的Redis客户端、显式namespace及毫秒租约。键只含namespace和SHA256摘要，值为随机owner token；不存业务响应、邀请码或学生材料。

- 获取使用SET NX PX。
- 续租及释放使用Lua原子比较owner token；旧owner不能延长或删除新owner的租约。
- Redis繁忙返回已有409 conflict，提示原幂等键重试。
- Redis故障可退回数据库唯一键及事务保障；已提交回执重放不依赖Redis。
- 租约过期也不能跳过数据库占位。协调器不把租约当成业务授权或提交凭据；长调用可超过协调TTL，正确性仍由DB保证。

无自动后台续租线程、无Redis响应缓存、无FLUSH操作。示例外部模型调用保持关闭。限流已提供独立RedisInviteRedeemLimiter适配及fixed/sliding原子窗口；默认仍为RAM，受控多实例须显式注入同namespace共享Redis，故障failclosed429。

## 兼容与敏感信息

`app.state.receipt_store` / `receipt_coordinator` 可供受控接入与测试注入。默认仍为 `LegacyProtoReceiptStore`，保留现有本地原型、多事务导入批次及键冲突行为；正式store不查询proto批次。不得直接在正在使用的本地库上切store并假定旧幂等键已迁移：旧proto历史需要另行核验、设计迁移，当前不自动认领。

SEC-301的邀请码语义不变：正式及原型回执都去掉明文code；重放仍核对授权归属、过期、使用、撤销与HMAC摘要。稳定配置secret支持有效邀请重启重放；随机secret变化会409，不能返回一个不可兑换的错误码。Redis不存邀请码，不能绕过上述检查。

不自动TTL删除正式回执。删除回执可能让同key重新执行业务，留存、脱敏及受控归档需在Q-07政策确认后另行设计；这不是擅自确定永久留存政策。

## 验证及真实环境边界

API回归使用SQLite验证兼容、正式store注入、actor隔离、角色拒绝、指纹冲突、敏感邀请码、业务失败回滚和Redis故障/繁忙分支。这些测试中的故障stub不冒充真实Redis。

真实回归 `tests/integration/test_durable_receipts.py` 显式依赖已授权隔离MySQL与Redis配置，默认跳过。MySQL数据库由迁移测试fixture随机新建并通过完整迁移初始化，不drop已有库；Redis仅使用配置要求的tutor-test:下随机专属namespace，结束只删除本测试prefix内key，禁止FLUSHDB/FLUSHALL。

```powershell
uv run --group mysql --group redis pytest tests/integration/test_durable_receipts.py -q
```

凭据分别通过 `TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS` 和 `TUTOR_REDIS_RECEIPT_TEST_CONFIG` 私密文件环境变量提供，不打印密码或URL。真实测试验证独立连接同key并发仅执行一次业务、提交后新store重放、错误rollback、拒绝内部commit、prototype路径隔离、fatal IntegrityError不吞、Redis NX/续租/过期/旧token、Redis租约过期后的双owner仍不能重复SQL业务，以及005→006升级链。

## 分布式限流后续更新

RedisInviteRedeemLimiter已单独实现并实际验证，替代前文尚未提供限流的历史状态。显式注入时使用共享namespace与Redis TIME原子窗口，失败关闭429；默认仍RAM，不自动连接Redis。fixed/sliding模式切换遇到未过期桶拒绝重置额度；详见parent_invite_rate_limit及集成测试。
