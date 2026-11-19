# MySQL备份恢复演练（OPS-301）

`mysql_backup.py` 提供 `create_backup`、`verify_backup`、`restore_backup` 和 `require_empty_database`，
供受控运维入口调用；不会自动备份或连接任何数据库。

`tools/mysql_backup_cli.py` 提供显式命令行入口。凭据JSON包含host、port、user、password，放在受保护目录，不提交仓库。
以下路径均为占位符；backup/restore必须显式指定库名和对应的官方客户端可执行文件。

```
uv run --group mysql python tools/mysql_backup_cli.py backup --credentials PRIVATE_CONFIG --database SOURCE_DB --client MYSQLDUMP_PATH --backup NEW_BACKUP.sql --metadata NEW_METADATA.json
uv run python tools/mysql_backup_cli.py verify --backup NEW_BACKUP.sql --metadata NEW_METADATA.json
uv run --group mysql python tools/mysql_backup_cli.py restore --credentials PRIVATE_CONFIG --database EMPTY_TARGET_DB --client MYSQL_PATH --backup NEW_BACKUP.sql --metadata NEW_METADATA.json
```

verify只校验文件，不连接数据库。backup拒绝覆盖已有备份或元数据；restore不创建目标库、不清库，目标须预先准备并停止其他写入。

## 使用边界

- 数据库连接由调用方提供SQLAlchemy engine，客户端凭据从私密配置读入，不写命令参数或日志。
- helper在任何操作前核对engine与客户端host/port/user/password一致；显式defaults-file并禁用login paths，剔除MYSQL_*环境，避免用户配置改变客户端目标。
- 仅接受受信任的常规engine（URL query最多允许charset=utf8mb4）；不得用creator、connect_args或连接事件重写目标。CLI从同一私密配置创建engine，未开放这些覆盖参数。
- 恢复只接收受信任的、本工具生成的单库dump；SHA256不校验SQL作用域，空库检查不是SQL沙箱。运维须使用仅有目标库权限的账号或隔离实例，不能把任意外来SQL交给高权限恢复账号。
- mysqldump使用单事务、禁止表锁，包含表、数据、视图、触发器、过程/函数和事件。
- 单事务快照适用于InnoDB；本工具尚未与迁移锁集成，演练期间应停止DDL，不承诺并行DDL一致性。
- 输出必须是新文件，拒绝覆盖；失败删除本次创建的未完成文件，不删除其他调用创建的文件。
- Ctrl+C同样清理本次未完成dump；元数据写入失败清理本次CLI创建的dump。进程被强制结束或机器断电可能留下文件，应人工核验后处理，不自动覆盖。
- 元数据记录格式、来源库名、大小及SHA256；恢复前验证普通文件和校验和。
- 备份与元数据都应放在受保护目录。校验和可检测意外损坏，不是数字签名，不能抵御两者同时被篡改。
- 恢复只允许没有表、视图、例程和事件的独立目标库；不要让应用同时向恢复目标写入。
- 恢复失败可能留下部分DDL，必须人工检查；不自动清库或重跑，不提供覆盖生产库的入口。
- 当前有超时限制，尚无硬磁盘配额；生产使用前应配置独立卷及容量监控。
- 工具只演练数据库，不包含对象存储、设备草稿或整个应用的灾难恢复；未决定生产备份周期和留存期限。

## 可重复验证

先配置仅本机独立测试库的凭据文件路径 `TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS`，
其中包含host、port、user、password；当前测试夹具仅允许127.0.0.1:13316，自动新建随机测试库，不删除已有库。
再设置 `TUTOR_MYSQL_CLIENT_BIN` 为本机mysql/mysqldump客户端所在目录。
配置文件不可提交仓库，密钥不放聊天或命令行参数。

运行：

```
uv run --group mysql pytest tests/integration/test_mysql_backup_restore.py -q
uv run pytest tests/unit/test_mysql_backup.py -q
```

真实MySQL8.4.13演练验证：执行全部迁移、自编中文/emoji记录和函数、导出、新空库恢复、
校对数据/函数及迁移ledger，再次向非空目标恢复被拒绝。未配置时测试明确skip，不能算作演练成功。

