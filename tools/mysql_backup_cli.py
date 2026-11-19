"""显式运维入口；不自动调度、不创建或清空数据库、不输出连接信息。"""

import argparse
import json
import re
import sys
from pathlib import Path

from mysql_backup import create_backup, restore_backup, verify_backup
from sqlalchemy import URL, create_engine


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "backup", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--backup", type=Path, required=True)
        command.add_argument("--metadata", type=Path, required=True)
        if name != "verify":
            command.add_argument("--credentials", type=Path, required=True)
            command.add_argument("--database", required=True)
            command.add_argument("--client", type=Path, required=True)
    args = parser.parse_args(argv)
    engine = None
    reserved_metadata = False
    created_backup = False
    try:
        if args.command == "verify":
            verify_backup(args.backup, json.loads(args.metadata.read_text(encoding="utf-8")))
            print("备份校验通过；未连接数据库")
            return 0
        if args.command == "backup":
            # 先独占元数据路径，避免完成dump后才发现不能保存校验信息。
            with args.metadata.open("x", encoding="utf-8"):
                reserved_metadata = True
            args.metadata.chmod(0o600)
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", args.database):
            raise ValueError("invalid database")
        credentials = json.loads(args.credentials.read_text(encoding="utf-8"))
        if not isinstance(credentials, dict) or not all(
            key in credentials for key in ("host", "port", "user", "password")
        ):
            raise ValueError("invalid credentials")
        port = int(credentials["port"])
        if not 1 <= port <= 65535:
            raise ValueError("invalid port")
        engine = create_engine(
            URL.create(
                "mysql+pymysql",
                username=credentials["user"],
                password=credentials["password"],
                host=credentials["host"],
                port=port,
                database=args.database,
                query={"charset": "utf8mb4"},
            ),
            hide_parameters=True,
            connect_args={"connect_timeout": 10},
        )
        if args.command == "backup":
            metadata = create_backup(
                engine, executable=args.client, credentials=credentials, output_path=args.backup
            )
            created_backup = True
            args.metadata.write_text(
                json.dumps(metadata, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            reserved_metadata = False
            print("数据库备份及校验元数据已生成")
        else:
            restore_backup(
                engine,
                executable=args.client,
                credentials=credentials,
                backup_path=args.backup,
                metadata=json.loads(args.metadata.read_text(encoding="utf-8")),
            )
            print("数据库已恢复到空目标库；请继续执行应用验收")
        return 0
    except (Exception, KeyboardInterrupt):
        # 驱动异常可能包含连接字符串；仅返回固定提示。
        print(
            "操作失败；检查私密配置、文件和空库条件。恢复失败需人工检查目标，不自动重跑。",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        if reserved_metadata:
            args.metadata.unlink(missing_ok=True)
            if created_backup:
                args.backup.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
