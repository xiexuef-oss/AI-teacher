# MySQL迁移执行器（DATA-301）

`migration_runner.py` 是独立的迁移运维工具，不切换API运行数据库，不改变现有SQLite原型，也不导入 `proto_` 表。历史 `migrations/NNN_*.sql` 不回写。

安装mysql依赖组，将连接信息放在私密环境变量 `TUTOR_MIGRATION_DATABASE_URL`。不要把URL写在命令参数、提交、文档或日志里。工具不打印URL、密码或驱动异常；失败输出通用JSON错误。

```powershell
uv sync --group mysql
uv run python tools/migration_runner.py
uv run python tools/migration_runner.py --apply
```

默认是只读审计：列出目标库表、ledger历史、待执行文件和 `ready`/`blocked_reason`，不会创建ledger或修改数据库。不指定 `--directory` 时读取仓库 `migrations/`。`--apply` 才执行。成功退出0；审计发现脏历史、校验和冲突或无人管理的既有库，以及执行失败，均退出1；参数错误退出2。

## Ledger管理边界

`schema_migration_ledger` 是执行器独立引导管理的基础设施表，不是API业务ORM表，不进入业务SQL迁移、也不由业务ORM创建。这样首个业务迁移执行前就能持久化运行状态。它没有 `proto_` 前缀，包含：

- `name`：迁移文件名主键。
- `sha256`：实际执行的完整文件字节摘要。
- `state`：`running`、`applied`、`failed`。
- `started_at`、`finished_at`：UTC时间。
- `error_code`：脱敏类别；不存SQL原文或驱动错误。

只有原本空库可引导ledger；已有业务表但没有ledger历史的库明确拒绝自动认领，哪怕有人预建了空ledger也拒绝。已有版本只接受原文件和摘要，历史文件缺失、修改、重复版本、乱序空洞和未完成状态均拒绝升级。以后新增业务结构仍只追加编号SQL。

## 执行及失败语义

同一个SQLAlchemy连接使用MySQL `GET_LOCK`，锁名由目标数据库名摘要派生；持锁连接按文件执行、维护ledger，最后显式 `RELEASE_LOCK`。DDL隐式提交不会释放这个连接锁。锁不能获得时不执行DDL；默认等待0秒，Python函数允许配置等待上限。锁不是跨服务器锁，数据库故障转移、多节点运维还需相应协调。

每文件先以autocommit持久化 `running`，再逐语句执行，全部成功才标 `applied`。MySQL DDL通常不能事务回滚：中途失败会留下部分结构及 `failed`；连接中断、进程崩溃可能留下 `running`。两种状态都视为dirty，后续明确拒绝自动重跑，避免重复或覆盖结构。已完成的前面文件保持applied。无新文件时重复执行为空操作。

文件在执行前读取为快照，ledger记录该快照摘要；计划期间发生文件变化则拒绝。只支持仓库现有SQL语法与拆分器，不支持DELIMITER、存储过程等复杂脚本；SQL不是不可信输入。预检拒绝proto表、ledger访问、跨库表、切换数据库、创建/删除数据库、会话或事务控制。不要用此工具执行用户上传的SQL。

## 旧库或脏库处理

先只读审计并保存结构、ledger和备份证据。由负责人核对实际部分DDL、数据及历史摘要，批准修复或备份恢复方案。工具不提供自动baseline、自动认领、清库、强制标applied或重置dirty开关；不得为了继续部署直接修改历史摘要或盲改ledger状态。历史无ledger库的受控基线方案仍需后续设计。

## 真实回归

`tests/integration/test_mysql_migrations.py` 默认跳过，需显式设置私密文件路径 `TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS`，文件只含host/port/user/password；测试限定已授权的127.0.0.1:13316隔离实例。

```powershell
uv run --group mysql pytest tests/unit/test_migration_runner.py tests/integration/test_mysql_migrations.py -q
```

每个真实测试新建随机 `tutor_migration_runner_*` 空库，不删除任何已有库。新建库名记录在凭据文件同目录的 `migration-runner-test-databases.jsonl`，记录不含秘密。测试库保留供检查，由操作者后续按记录确认清理。覆盖仓库全部迁移clean install、增量升级、重复无操作、历史篡改拒绝、部分DDL失败及failed/running拒绝重跑、旧库只读审计与拒绝认领、不同连接争锁。尚未验证生产数据迁移、生产备份恢复、多节点故障转移或API运行时MySQL兼容。
