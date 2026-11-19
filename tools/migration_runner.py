"""迁移计划校验；MySQL DDL不是事务回滚保证，脏版本必须人工修复。"""

import hashlib
import re
from pathlib import Path


class MigrationPlanError(ValueError):
    pass


def plan_migrations(paths, applied):
    files = sorted((Path(path) for path in paths), key=lambda path: path.name)
    if any(not re.fullmatch(r"\d{3}_[A-Za-z0-9_]+\.sql", path.name) for path in files):
        raise MigrationPlanError("迁移文件名无效")
    numbers = [path.name[:3] for path in files]
    if len(set(numbers)) != len(numbers):
        raise MigrationPlanError("迁移版本号重复")
    records = {record["name"]: record for record in applied}
    if len(records) != len(applied):
        raise MigrationPlanError("迁移历史重复")
    if set(records) - {path.name for path in files}:
        raise MigrationPlanError("已执行迁移文件缺失，拒绝继续")
    pending, encountered_pending = [], False
    for path in files:
        record = records.get(path.name)
        if record is None:
            encountered_pending = True
            pending.append(path)
            continue
        if record["state"] != "applied":
            raise MigrationPlanError("迁移未完成，必须先检查并人工修复，不能自动重跑DDL")
        if record["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise MigrationPlanError("已执行迁移校验和变化，历史文件不可回写")
        if encountered_pending:
            raise MigrationPlanError("迁移历史顺序存在空洞，拒绝乱序升级")
    return pending


LEDGER = "schema_migration_ledger"


def _history(connection, tables):
    if LEDGER not in tables:
        return []
    return list(
        connection.exec_driver_sql(
            f"SELECT name, sha256, state FROM {LEDGER} ORDER BY name"
        ).mappings()
    )


def _tables(connection):
    return [row[0] for row in connection.exec_driver_sql("SHOW TABLES")]


def audit_schema(engine, paths):
    """只读审计，不创建ledger、不执行迁移、不自动认领旧库。"""
    if engine.dialect.name != "mysql":
        raise MigrationPlanError("仅支持 MySQL 迁移执行和审计")
    with engine.connect() as connection:
        tables = _tables(connection)
        history = _history(connection, tables)
        unmanaged = bool(set(tables) - {LEDGER}) and not history
        blocked = None
        try:
            pending = [path.name for path in plan_migrations(paths, history)]
        except MigrationPlanError as error:
            pending, blocked = None, str(error)
        return {
            "tables": sorted(tables),
            "unmanaged_schema": unmanaged,
            "history": [dict(row) for row in history],
            "pending": pending,
            "ready": not unmanaged and blocked is None,
            "blocked_reason": blocked,
        }


def apply_migrations(engine, paths, *, lock_timeout=0):
    """同一连接持有GET_LOCK；DDL失败保留dirty，不提供自动回滚/重试/认领。"""
    from sqlalchemy import text
    from sqlglot import exp

    from verify_migrations import parse_sql, split_statements

    if engine.dialect.name != "mysql":
        raise MigrationPlanError("仅支持 MySQL 迁移执行和审计")
    if type(lock_timeout) is not int or not 0 <= lock_timeout <= 3600:
        raise MigrationPlanError("锁等待必须为0~3600秒整数")
    files = list(paths)
    plan_migrations(files, [])
    snapshots = {}
    for file in files:
        path = Path(file)
        raw = path.read_bytes()
        sql = raw.decode("utf-8-sig")
        for statement in parse_sql(sql, source=path.name):
            if isinstance(statement, (exp.Use, exp.Set, exp.Transaction, exp.Commit, exp.Rollback)):
                raise MigrationPlanError("迁移不能切换数据库或控制会话/事务")
            if isinstance(statement, (exp.Create, exp.Drop)) and statement.args.get("kind") in {
                "DATABASE",
                "SCHEMA",
            }:
                raise MigrationPlanError("迁移不能创建或删除数据库")
            if any(
                table.name.lower().startswith("proto_")
                or table.name.lower() == LEDGER
                or table.db
                or table.catalog
                for table in statement.find_all(exp.Table)
            ):
                raise MigrationPlanError("迁移不能访问原型表或执行器ledger")
        snapshots[path.name] = (raw, list(split_statements(sql)))
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        database = connection.exec_driver_sql("SELECT DATABASE()").scalar()
        if not database:
            raise MigrationPlanError("必须显式指定目标数据库")
        lock = "tutor-migrations:" + hashlib.sha256(database.encode()).hexdigest()[:32]
        acquired = connection.execute(
            text("SELECT GET_LOCK(:name, :timeout)"), {"name": lock, "timeout": lock_timeout}
        ).scalar()
        if acquired != 1:
            raise MigrationPlanError("迁移锁正在使用或不可获取，未执行迁移")
        try:
            connection.exec_driver_sql("SET time_zone = '+00:00'")
            tables = _tables(connection)
            history = _history(connection, tables)
            if (set(tables) - {LEDGER}) and not history:
                raise MigrationPlanError("已有结构但没有迁移历史，拒绝自动认领；请先只读审计")
            pending = plan_migrations(files, history)
            for path in pending:
                if path.read_bytes() != snapshots[path.name][0]:
                    raise MigrationPlanError("迁移文件在计划期间发生变化")
            if LEDGER not in tables:
                connection.exec_driver_sql(f"""CREATE TABLE {LEDGER} (
                    name VARCHAR(255) NOT NULL PRIMARY KEY,
                    sha256 CHAR(64) NOT NULL,
                    state VARCHAR(16) NOT NULL,
                    started_at DATETIME(6) NOT NULL,
                    finished_at DATETIME(6) NULL,
                    error_code VARCHAR(64) NULL,
                    CONSTRAINT ck_migration_state CHECK (state IN ('running','applied','failed'))
                ) ENGINE=InnoDB""")
            applied = []
            for path in pending:
                raw, statements = snapshots[path.name]
                connection.execute(
                    text(f"""INSERT INTO {LEDGER}
                    (name, sha256, state, started_at) VALUES (:name, :sha, 'running', UTC_TIMESTAMP(6))"""),
                    {"name": path.name, "sha": hashlib.sha256(raw).hexdigest()},
                )
                try:
                    for statement in statements:
                        connection.exec_driver_sql(statement)
                except Exception:
                    # Persist only a category: SQL and driver errors may contain private data.
                    connection.execute(
                        text(f"""UPDATE {LEDGER} SET state='failed',
                        finished_at=UTC_TIMESTAMP(6), error_code='ddl_failed' WHERE name=:name"""),
                        {"name": path.name},
                    )
                    raise MigrationPlanError(
                        "DDL执行失败，数据库可能已部分变更；脏版本必须人工修复"
                    ) from None
                connection.execute(
                    text(f"""UPDATE {LEDGER} SET state='applied',
                    finished_at=UTC_TIMESTAMP(6) WHERE name=:name"""),
                    {"name": path.name},
                )
                applied.append(path.name)
            return applied
        finally:
            connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock})


def main():
    import argparse
    import json
    import os

    from sqlalchemy import create_engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory", type=Path, default=Path(__file__).resolve().parents[1] / "migrations"
    )
    parser.add_argument("--apply", action="store_true", help="显式执行；默认只读审计")
    args = parser.parse_args()
    url = os.environ.get("TUTOR_MIGRATION_DATABASE_URL")
    if not url:
        print(json.dumps({"error": "migration database environment configuration required"}))
        return 1
    engine = None
    try:
        engine = create_engine(url, hide_parameters=True)
        paths = list(args.directory.glob("*.sql"))
        report = (
            {"applied": apply_migrations(engine, paths)}
            if args.apply
            else audit_schema(engine, paths)
        )
        print(json.dumps(report, ensure_ascii=True))
        return 0 if args.apply or report["ready"] else 1
    except Exception:
        print(
            json.dumps(
                {"error": "migration refused or failed; inspect protected ledger and schema"}
            )
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
