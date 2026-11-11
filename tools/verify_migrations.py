"""迁移验证入口（ADR-006）。

静态模式（默认，不需要数据库）：
    uv run python tools/verify_migrations.py
  按 MySQL 方言解析 migrations/*.sql，推导出表结构，并核对 ORM 的每一列都被迁移覆盖。
  解析器比较宽松，只能抓到明显的语法问题，不能代替在真实 MySQL 上执行。

真实库模式（需要一个空的 MySQL 8 数据库和 mysql 依赖组）：
    uv sync --group mysql
    uv run python tools/verify_migrations.py --mysql-url mysql+pymysql://user:pass@127.0.0.1:3306/tutor_verify
  在空库上按顺序执行全部迁移（clean install），再把反射出的表和列与静态推导结果对照。
  编写时的开发机没有 MySQL，这个模式尚未实际运行过。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
PROTOTYPE_PREFIX = "proto_"

Schema = dict[str, dict[str, str]]


class MigrationParseError(Exception):
    """迁移 SQL 无法按 MySQL 方言解析。"""


def parse_sql(sql: str, *, source: str) -> list[exp.Expression]:
    try:
        statements = [s for s in sqlglot.parse(sql, read="mysql") if s is not None]
    except ParseError as error:
        raise MigrationParseError(f"{source}: {error}") from error
    for statement in statements:
        # sqlglot 解析不了的语句会退化成 Command，这里一律当作错误，避免静默放过。
        if isinstance(statement, exp.Command):
            raise MigrationParseError(f"{source}: 无法解析的语句：{statement.sql()[:120]}")
    return statements


def _table_name(node: exp.Expression) -> str:
    table = node.find(exp.Table)
    if table is None:
        raise MigrationParseError(f"找不到表名：{node.sql()[:120]}")
    return table.name


def _column_type(column: exp.ColumnDef) -> str:
    kind = column.args.get("kind")
    return kind.sql(dialect="mysql").upper() if kind is not None else ""


def _apply(schema: Schema, statement: exp.Expression, source: str) -> None:
    if isinstance(statement, exp.Create) and (statement.args.get("kind") or "").upper() == "TABLE":
        name = _table_name(statement.this)
        if name in schema:
            raise MigrationParseError(f"{source}: 表 {name} 重复创建")
        definition = statement.this
        columns = [e for e in definition.expressions if isinstance(e, exp.ColumnDef)]
        schema[name] = {c.name: _column_type(c) for c in columns}
    elif isinstance(statement, exp.Alter):
        name = _table_name(statement)
        if name not in schema:
            raise MigrationParseError(f"{source}: ALTER 了不存在的表 {name}")
        for action in statement.args.get("actions") or []:
            if isinstance(action, exp.ColumnDef):
                if action.name in schema[name]:
                    raise MigrationParseError(f"{source}: {name}.{action.name} 重复添加")
                schema[name][action.name] = _column_type(action)
            elif isinstance(action, exp.Drop):
                column = action.find(exp.Column)
                if column is not None:
                    schema[name].pop(column.name, None)


def load_migration_schema(
    directory: Path = MIGRATIONS_DIR, only: Iterable[str] | None = None
) -> Schema:
    """按文件名顺序应用迁移，返回 {表: {列: 类型}}。"""
    wanted = set(only) if only is not None else None
    schema: Schema = {}
    for path in sorted(directory.glob("*.sql")):
        if wanted is not None and path.name not in wanted:
            continue
        for statement in parse_sql(path.read_text(encoding="utf-8"), source=path.name):
            _apply(schema, statement, path.name)
    return schema


# ---------------------------------------------------------------- ORM 对照


def _acceptable_sql_types(column: Any) -> set[str]:
    """ORM 列类型对应的迁移类型写法。认不出的类型返回空集，由调用方报告。"""
    import sqlalchemy as sa

    column_type = column.type
    if type(column_type).__name__ == "UTCDateTime":
        return {"DATETIME(3)"}
    if isinstance(column_type, sa.CHAR):
        return {f"CHAR({column_type.length})"}
    if isinstance(column_type, sa.String):
        return {f"VARCHAR({column_type.length})"}
    if isinstance(column_type, sa.Boolean):
        return {"TINYINT(1)"}
    if isinstance(column_type, sa.BigInteger):
        return {"BIGINT"}
    if isinstance(column_type, sa.SmallInteger):
        return {"SMALLINT", "TINYINT"}
    if isinstance(column_type, sa.Integer):
        return {"INT"}
    if isinstance(column_type, sa.JSON):
        return {"JSON"}
    if isinstance(column_type, sa.Date):
        return {"DATE"}
    return set()


def orm_drift(schema: Schema, metadata: Any, *, ignore_prefix: str = PROTOTYPE_PREFIX) -> list[str]:
    """列出 ORM 里有、但迁移里没有或类型对不上的表和列。原型表（proto_）不参与对照。"""
    problems: list[str] = []
    for table in metadata.sorted_tables:
        if table.name.startswith(ignore_prefix):
            continue
        if table.name not in schema:
            problems.append(f"表 {table.name} 不在迁移中")
            continue
        migrated = schema[table.name]
        for column in table.columns:
            if column.name not in migrated:
                problems.append(f"{table.name}.{column.name} 不在迁移中")
            elif migrated[column.name] not in _acceptable_sql_types(column):
                problems.append(
                    f"{table.name}.{column.name} 类型不一致：ORM 为 {column.type!r}，"
                    f"迁移为 {migrated[column.name]}"
                )
    return problems


def _load_orm_metadata() -> Any:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
    sys.path.insert(0, str(REPO_ROOT / "services" / "ai_gateway"))
    import tutor_api.models  # noqa: F401
    import tutor_api.proto_models  # noqa: F401
    from tutor_api.db import Base

    return Base.metadata


# ---------------------------------------------------------------- 真实库模式


def split_statements(sql: str) -> Iterator[str]:
    """把一份迁移拆成单条语句：去掉 -- 行注释，按引号外的分号切分。"""
    buffer: list[str] = []
    in_string = False
    i = 0
    while i < len(sql):
        char = sql[i]
        if in_string:
            buffer.append(char)
            if char == "'":
                if sql[i + 1 : i + 2] == "'":  # 转义的单引号
                    buffer.append("'")
                    i += 1
                else:
                    in_string = False
        elif char == "'":
            in_string = True
            buffer.append(char)
        elif char == "-" and sql[i : i + 2] == "--":
            while i < len(sql) and sql[i] != "\n":
                i += 1
            continue
        elif char == ";":
            statement = "".join(buffer).strip()
            if statement:
                yield statement
            buffer = []
        else:
            buffer.append(char)
        i += 1
    tail = "".join(buffer).strip()
    if tail:
        yield tail


def verify_on_mysql(mysql_url: str, expected: Schema) -> list[str]:
    """在空库上 clean install，并把反射结果与静态推导的表、列对照。"""
    import sqlalchemy as sa

    engine = sa.create_engine(mysql_url)
    problems: list[str] = []
    with engine.connect() as connection:
        existing = sa.inspect(connection).get_table_names()
        if existing:
            return [f"目标库不是空库（已有 {len(existing)} 张表），拒绝执行。请换一个空库。"]
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            for statement in split_statements(path.read_text(encoding="utf-8")):
                connection.execute(sa.text(statement))
            connection.commit()
            print(f"已执行 {path.name}")

        inspector = sa.inspect(connection)
        actual = {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in inspector.get_table_names()
        }
    engine.dispose()

    for table, columns in expected.items():
        if table not in actual:
            problems.append(f"真实库缺少表 {table}")
        elif set(columns) != actual[table]:
            problems.append(f"{table} 的列与静态推导不一致：{sorted(set(columns) ^ actual[table])}")
    problems.extend(f"真实库多出表 {table}" for table in set(actual) - set(expected))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 MySQL 迁移")
    parser.add_argument(
        "--mysql-url", help="空 MySQL 库的 SQLAlchemy URL；提供后执行 clean install"
    )
    args = parser.parse_args(argv)

    schema = load_migration_schema()
    print(f"静态解析通过：{len(schema)} 张表，{sum(len(c) for c in schema.values())} 列")

    problems = orm_drift(schema, _load_orm_metadata())
    if not problems:
        print("ORM 对照通过：ORM 的每一列都在迁移中，类型一致")

    if args.mysql_url:
        problems.extend(verify_on_mysql(args.mysql_url, schema))
    else:
        print("未提供 --mysql-url：没有在真实 MySQL 上执行迁移")

    for problem in problems:
        print(f"问题：{problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
