# PROD-301 受控 dev/staging 运行生命周期

这是基础设施和事务接入验证，不是生产发布。Q-03真实登录/监护核验、Q-07正式留存/对象存储等仍未冻结；prod无论传入何种依赖都拒绝启动。测试身份provider不代表真实账号服务，不选择任何身份商或对象存储供应商。

## 环境矩阵

| 环境/数据库 | 行为 |
|---|---|
| local + SQLite | 保持已有原型：按ORM建表、可显式启用本地身份Mock/自编样题/导入worker/本机附件；默认原型回执和RAM限流 |
| local + MySQL | 明确拒绝，不能仅替换URL后自动创建proto表 |
| dev/staging + MySQL | 仅在显式注入完整受控依赖、迁移完成且健康检查通过后运行；不自动修复或回退 |
| prod | 持续拒绝；本工作不提供发布许可或开关 |

managed模式需要：mysql+pymysql、固定pseudonym_secret、显式身份provider（拒绝LocalMock/Disabled）、SqlReceiptStore、现有私有FilesystemBlobStore或显式本机S3BlobStore、RedisInviteRedeemLimiter。必须关闭local_identity_mock、seed_sample_content、import_worker_enabled和外部模型调用。RedisReceiptCoordinator可选，因为业务正确性本就由DB回执保证；如果注入也检查健康。

PROD-303进一步要求注入网关的外调配置意图也关闭，不以“当前候选不可用”代替配置检查；
生命周期绑定不可放宽的禁止外调策略，包含已有单次计划与之后的候选/开关变化。
本地 SQLite 显式持久调用仍按 COST-308 接线，受控环境没有因此开放外调。

`create_app` 保留identity_provider/media_store/parent_invite_limiter参数，新增receipt_store/receipt_coordinator。缺依赖时在开数据库之前拒绝，不能默认改用原型回执、RAM限流或内存媒体。显式文件存储仅供受控环境验证，不因此确认生产媒体地域或留存政策。

## 启动与退出

managed生命周期只读检查：

- 仓库迁移文件集合与ledger完全对应，所有state为applied且SHA256匹配。
- 业务表及ORM需要的列存在；数据库内不能有任何proto_表。
- 显式媒体root已经存在、是规范路径的真实目录；生命周期不mkdir、不清理媒体。
- 或显式本机S3的命名空间LIST成功（MaxKeys=1），返回键必须在配置前缀内；不读取内容、不写删对象、不重复条件写探针。SDK只接受显式端口的回环IP、有限且最多15秒的连接/读取等待、单次尝试和禁用代理；同源重定向校验同时检查协议与主机端口。配置接线先于打开数据库，探针每次重验配置，失败不回退文件系统。
- Redis PING成功；不调用限流check、不创建桶、不重置TTL、不消耗额度。

不调用create_all、seed_if_empty、scrub_legacy_responses、cleanup_media，不创建或启动原型导入worker。失败统一拒绝启动，不自动baseline、补迁移或静默fallback；启动校验失败同样dispose数据库引擎。DDL由独立migration_runner显式执行，API启动不承担部署迁移。

此检查不替代备份恢复验证、权限部署审计或完整数据库结构审查。文件存储的跨进程实现也不是生产对象存储SLA。

### 本机S3联合验证（2026-11-17）

复用现有S3BlobStore，没有新增只读存储类、环境开关或供应商配置。其构造函数仍会在调用方显式准备适配器时写入并清除随机私有CAS探针；只读承诺针对随后API受控启动的校验阶段，不代表适配器构造无写入。调用方负责关闭注入的SDK客户端，API只dispose自己创建的数据库引擎。

隔离MySQL/Redis/S3联合回归29项通过，最终新增五项复验通过；重复启动只发两次前缀LIST，对象键/ETag及已有Redis配额不变，SQL无DDL/DML，存储故障、越界响应、接线后变成外部端点均拒绝启动并释放引擎。相关单元/媒体故障回归165项通过，Ruff及七个改动Python文件格式检查通过。新旧12项S3变异均捕获，原始JUnit重新分类核验；916份快照恢复且验证时与主目录相同。证据：`var/prod301-s3-real.log`、`var/prod301-s3-real-final.log`、`var/prod301-s3-unit.log`、`var/prod301-s3-mutation-coverage.json`、`var/prod301-s3-source-verification.json`。本轮未跑全库pytest、Flutter或后台全量，未改公开契约/客户端。

`/health`仍是环境信息接口，不会重新探测依赖，不是实时就绪探针。此轮只补存储接线与启动检查；非local媒体业务仍501/404，生产S3、生产凭据/权限/地域/留存及正式部署仍待。

## API功能及验证矩阵

| 路径/功能 | managed行为 | 本轮真实MySQL/Redis验证 |
|---|---|---|
| health/meta | 开放 | health的dev/staging标记；启动PING不消费额度 |
| 学生profile | 开放 | 正常读取、父角色403、未知token401 |
| 家长邀请/绑定/周报 | 开放，正式回执和共享Redis限流 | 同键邀请重放、绑定后读取、未授权家长404、无效兑换回滚 |
| 文本结构化单题导入/审核 | 开放 | 自编JSON导入、同键重放、作者不能自审、独立审核及发布 |
| 批量审核 | 开放，单外层事务内SAVEPOINT | 成功/失败项、同键重放；SAVEPOINT释放允许但不得提交外层 |
| 学生题目/会话/客观作答 | 开放 | 题目读取、建会话、建作答、同步草稿、提交确定反馈，跨owner404 |
| events读取、tasks、progress、reviews、自查、版本编辑等 | 保持正式表路径，未发现proto依赖 | 不宣称每个功能已完成真实MySQL覆盖；仍需扩展专项回归 |
| `/admin/import-jobs`全部操作 | reviewer/admin角色检查后统一501；学生403，未知token401 | 明确拒绝且不访问proto表 |
| `/dev/local-identities` | 非LocalMock provider下404 | 已验证，不发放原型token |
| `/tutor/sessions/{id}/next` | A恢复受审内容与规则路径，学生token/归属/独立作答门控保留；无受审换讲文案则safe fallback | 真实MySQL同key/不同key、旧RR快照等待锁及next-vs-submit回归；无网关调用 |
| 媒体上传/确认/读取 | 保留现有nonlocal gate；按契约501/404 | 仅验证持久store依赖注入与健康，不声称nonlocal媒体API已开放 |
| scans | 保持既有501 | 不声称接入真实OCR |

后续实现已由PROD-302/COST-302在显式本地SQLite切片补齐换讲/OCR持久意图、未知发送恢复和审计/预算协调，COST-308要求本地业务外调统一进入持久流程。managed next仍仅开放受审/规则及安全fallback，PROD-303禁止任何外部发送；不能把本地实现或受控fallback称为MySQL外部模型业务接入完成。

## SAVEPOINT与外层提交

SQLAlchemy在SAVEPOINT释放和外层commit都会触发before_commit。正式回执守卫允许nested事务的正常release，仍要求外层事务等回执完成后才提交。真实MySQL回归专门验证：action在nested里手动Session.commit时，先释放SAVEPOINT后仍会经过外层before_commit并被拒绝，业务及新回执均回滚；不能靠nested状态提前提交。

## 真实测试边界

`tests/integration/test_managed_runtime.py` 使用显式授权的隔离MySQL/Redis配置、新建随机测试数据库、完整迁移及预先创建的私有临时目录。测试数据是自编User和工程JSON样题，由测试明确写入，不是API启动seed，也不读取真实学生或原始试卷。fake身份provider只在测试中映射token，并从users读取真实role/active状态。

覆盖空库无ledger、缺迁移记录、running状态、校验和不符、意外proto表、业务列缺失、媒体root丢失及Redis不可用时拒绝；SQL观察器及禁用bootstrap函数确认启动无DDL/DML，失败引擎被dispose。测试库不drop已有库，Redis只清理本次tutor-test:随机前缀。

真实账户、真实监护授权、生产对象存储、外部模型调用、全API的MySQL并发语义、生产SLA和正式部署仍未完成。
