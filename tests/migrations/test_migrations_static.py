"""MySQL 迁移的静态校验：能按 MySQL 方言解析，且覆盖 docs/04 与 docs/09、docs/10 要求的结构。

本机没有 MySQL，这里不执行 SQL；真实库上的 clean install 由
`tools/verify_migrations.py --mysql-url` 完成。
"""

from __future__ import annotations

import csv

import pytest
import yaml

from support import MIGRATIONS_DIR, REPO_ROOT
from verify_migrations import MigrationParseError, load_migration_schema, parse_sql

DOC04_TABLES = {
    "users",
    "student_profiles",
    "parent_student_links",
    "knowledge_nodes",
    "knowledge_edges",
    "questions",
    "question_versions",
    "question_knowledge",
    "solutions",
    "rubrics",
    "study_sessions",
    "attempts",
    "handwriting_drafts",
    "tutor_events",
    "review_items",
    "media_assets",
    "audit_logs",
}
V13_TABLES = {
    "exam_region_rules",
    "question_region_applicability",
    "question_curriculum_mappings",
    "model_routes",
    "model_call_audits",
    "model_budget_usage",
}
TASK_TYPES = {
    "ocr_extract",
    "handwriting_understand",
    "knowledge_classify",
    "tutor_hint",
    "tutor_explain",
    "complex_reasoning",
    "solution_verify",
    "visual_spec",
    "review_plan",
}


@pytest.fixture(scope="module")
def schema() -> dict[str, dict[str, str]]:
    return load_migration_schema(MIGRATIONS_DIR)


def test_migration_files_are_numbered_and_ordered():
    names = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    assert names == ["001_init.sql", "002_region_model_governance.sql"]


def test_migrations_parse_as_mysql():
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        statements = parse_sql(path.read_text(encoding="utf-8"), source=path.name)
        assert statements, path.name


@pytest.mark.parametrize(
    "broken_sql",
    [
        "CREATE TABLE broken (id CHAR(36) NOT NULL;",  # 括号不闭合
        "CREATE TABLE broken (id CHAR(36) NOT NULLL);",  # 关键字拼错
        "CREATE TABEL broken (id CHAR(36));",  # 解析器退化为 Command 的语句
        "ALTER TABLE broken ADD COLUMN;",
    ],
)
def test_unparseable_sql_is_reported(broken_sql):
    with pytest.raises(MigrationParseError):
        parse_sql(broken_sql, source="broken.sql")


def test_doc04_tables_exist(schema):
    assert set(schema) >= DOC04_TABLES


def test_ids_are_char36_and_times_are_datetime3(schema):
    for table in DOC04_TABLES | V13_TABLES:
        columns = schema[table]
        if "id" in columns:
            assert columns["id"] == "CHAR(36)", table
        for name, sql_type in columns.items():
            if name.endswith("_at"):
                assert sql_type == "DATETIME(3)", f"{table}.{name}"
            if name.endswith("_id") and name not in {"model_id", "request_id", "trace_id"}:
                assert sql_type == "CHAR(36)", f"{table}.{name}"


def test_baseline_only_contains_doc04_tables():
    baseline = load_migration_schema(MIGRATIONS_DIR, only=["001_init.sql"])
    assert set(baseline) == DOC04_TABLES
    assert "region_code" not in baseline["student_profiles"]


def test_v13_additions_exist(schema):
    assert set(schema) >= V13_TABLES
    profile = schema["student_profiles"]
    # docs/09：region 保留兼容，新逻辑使用 region_code / exam_year / exam_scheme_code / curriculum_version
    assert {"region", "region_code", "exam_year", "exam_scheme_code", "curriculum_version"} <= set(
        profile
    )
    session = schema["study_sessions"]
    assert {"region_code_snapshot", "exam_year_snapshot"} <= set(session)
    rules = schema["exam_region_rules"]
    assert {
        "region_code",
        "exam_year",
        "subject",
        "scheme_code",
        "status",
        "official_source",
    } <= set(rules)
    applicability = schema["question_region_applicability"]
    assert {
        "origin_region_code",
        "recommended_region_code",
        "exam_year_from",
        "exam_year_to",
        "review_status",
    } <= set(applicability)


def test_questions_track_source_and_license_separately(schema):
    """docs/04：source_license 与 source_year 是独立字段；docs/07：来源五要素。"""
    assert {"source_type", "source_name", "source_year", "source_license", "source_url"} <= set(
        schema["questions"]
    )


def test_learning_records_keep_version_snapshots(schema):
    assert "question_version" in schema["study_sessions"]
    assert {"assisted", "used_solution", "submitted_at", "answer_json"} <= set(schema["attempts"])
    assert {"revision", "strokes_json", "media_key"} <= set(schema["handwriting_drafts"])
    assert {"seq_no", "event_json"} <= set(schema["tutor_events"])


def test_model_audit_table_has_no_raw_content_columns(schema):
    """docs/10：审计只记元数据，不保存学生原文或图片。"""
    columns = set(schema["model_call_audits"])
    assert {
        "request_id",
        "trace_id",
        "student_pseudonym",
        "task_type",
        "provider",
        "status",
    } <= columns
    # image_units 是计费单位数量（docs/10 的 usage），不是图片内容
    raw_markers = (
        "prompt",
        "content",
        "_text",
        "raw_",
        "image_url",
        "image_key",
        "image_data",
        "output_json",
    )
    assert not {c for c in columns if any(marker in c for marker in raw_markers)}


# ---------------------------------------------------------------- 语句拆分（真实库模式用）


def test_split_statements_matches_the_parser_on_real_migrations():
    from verify_migrations import split_statements

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        pieces = list(split_statements(sql))
        assert len(pieces) == len(parse_sql(sql, source=path.name)), path.name
        assert all(not piece.lstrip().startswith("--") for piece in pieces)
        for piece in pieces:
            parse_sql(piece, source=path.name)


def test_split_statements_ignores_semicolons_in_strings_and_comments():
    from verify_migrations import split_statements

    sql = (
        "-- 注释里的分号; 不算\n"
        "CREATE TABLE a (x VARCHAR(8) COMMENT 'p; q -- r', y INT); -- 行尾注释; 也不算\n"
        "ALTER TABLE a ADD COLUMN z VARCHAR(8) COMMENT 'it''s; fine';\n"
        "\n"
    )

    assert list(split_statements(sql)) == [
        "CREATE TABLE a (x VARCHAR(8) COMMENT 'p; q -- r', y INT)",
        "ALTER TABLE a ADD COLUMN z VARCHAR(8) COMMENT 'it''s; fine'",
    ]


# ---------------------------------------------------------------- ORM 与迁移对照


def _orm_metadata():
    import tutor_api.models  # noqa: F401
    import tutor_api.proto_models  # noqa: F401
    from tutor_api.db import Base

    return Base.metadata


def test_orm_tables_and_columns_are_covered_by_migrations(schema):
    """原型库按 ORM 建表；ORM 里的每一列都必须能在生产迁移里找到同名、同类型的列。"""
    from verify_migrations import orm_drift

    assert orm_drift(schema, _orm_metadata()) == []


def test_orm_drift_reports_missing_and_mismatched_columns(schema):
    from sqlalchemy import CHAR, Column, Integer, MetaData, String, Table

    from verify_migrations import orm_drift

    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", CHAR(36), primary_key=True),
        Column("role", String(99)),  # 迁移里是 VARCHAR(16)
        Column("nickname", String(40)),  # 迁移里没有
        Column("status", Integer),  # 迁移里是 VARCHAR(16)
    )
    Table("ghosts", metadata, Column("id", CHAR(36), primary_key=True))

    problems = orm_drift(schema, metadata)

    assert len(problems) == 4
    joined = "\n".join(problems)
    assert "users.role" in joined and "users.nickname" in joined and "users.status" in joined
    assert "ghosts" in joined


def test_prototype_tables_stay_out_of_production_migrations(schema):
    proto = {name for name in _orm_metadata().tables if name.startswith("proto_")}
    assert proto == {"proto_local_identities", "proto_idempotency_records"}
    assert not proto & set(schema)
    assert not [name for name in schema if name.startswith("proto_")]


# ---------------------------------------------------------------- 配置与模板


@pytest.fixture(scope="module")
def routes() -> dict:
    path = REPO_ROOT / "config" / "model_routes.example.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_example_routes_cover_all_task_types(routes):
    assert set(routes["routes"]) == TASK_TYPES


def test_example_routes_follow_frozen_provider_strategy(routes):
    """D-02：百炼主平台，DeepSeek 负责复杂推理，火山方舟备选。"""

    def order(task):
        return [c["provider"] for c in routes["routes"][task]["candidates"]]

    assert order("ocr_extract")[0] == "bailian"
    assert order("tutor_hint")[0] == "bailian"
    assert order("complex_reasoning")[0] == "deepseek"
    assert "volcengine_ark" in order("tutor_explain")
    assert {"bailian", "deepseek", "volcengine_ark", "mock"} == set(routes["providers"])


def test_example_routes_disable_external_calls(routes):
    for name, provider in routes["providers"].items():
        if provider["external"]:
            assert provider["enabled"] is False, name
            assert provider["compliance_approved"] is False, name
            assert provider["base_url_env"].isupper() and provider["api_key_env"].isupper(), name
            assert "api_key" not in provider and "base_url" not in provider, name
            assert all(v is None for v in provider["pricing"].values()), f"{name} 的价格不应写死"


def test_example_routes_do_not_hardcode_external_model_ids(routes):
    providers = routes["providers"]
    for task, route in routes["routes"].items():
        for candidate in route["candidates"]:
            if providers[candidate["provider"]]["external"]:
                assert "model" not in candidate, f"{task} 写死了外部模型 ID"
                assert candidate["model_env"].isupper(), task


def test_golden_dataset_manifest_is_an_empty_template():
    path = REPO_ROOT / "evaluation" / "golden_dataset_manifest.csv"
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 1, "评测集登记表目前只应有表头，题目尚未收集"
    assert {"item_id", "subject", "region_code", "source_license", "reviewer"} <= set(rows[0])
