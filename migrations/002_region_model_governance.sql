-- 002_region_model_governance.sql
-- V1.3：首发地区建模（docs/09）与模型网关治理（docs/10）。
-- 省份、考试年份、考试制度版本、教材版本分开建模；任何一项都不能由另一项推断。

-- ---------------------------------------------------------------- 学生资料

ALTER TABLE student_profiles
  ADD COLUMN region_code       VARCHAR(8)   NULL COMMENT 'CN-51 四川 / CN-50 重庆；用户手动选择，不按定位推断',
  ADD COLUMN exam_year         SMALLINT     NULL COMMENT '预期高考年份',
  ADD COLUMN exam_year_source  VARCHAR(16)  NULL COMMENT 'estimated（按年级推算）/ user（手动设置）',
  ADD COLUMN exam_scheme_code  VARCHAR(32)  NULL COMMENT '考试制度版本；对应规则审核生效前保持 NULL',
  ADD COLUMN subjects_json     JSON         NULL COMMENT '主要学习科目';

CREATE INDEX ix_student_profiles_region ON student_profiles (region_code, exam_year);

-- 会话保存学习时的地区与考试年份快照；切换地区后历史记录不迁移、不覆盖。
ALTER TABLE study_sessions
  ADD COLUMN region_code_snapshot         VARCHAR(8)   NULL,
  ADD COLUMN exam_year_snapshot           SMALLINT     NULL,
  ADD COLUMN exam_scheme_code_snapshot    VARCHAR(32)  NULL,
  ADD COLUMN curriculum_version_snapshot  VARCHAR(32)  NULL;

-- ---------------------------------------------------------------- 地区考试规则

-- 按 (地区, 考试年份, 学科, 制度版本) 版本化；只有 active 才生效，且必须有官方依据和审核人。
CREATE TABLE exam_region_rules (
  id                   CHAR(36)      NOT NULL,
  region_code          VARCHAR(8)    NOT NULL,
  exam_year            SMALLINT      NOT NULL,
  subject              VARCHAR(16)   NOT NULL,
  scheme_code          VARCHAR(32)   NOT NULL,
  version              INT           NOT NULL DEFAULT 1,
  status               VARCHAR(16)   NOT NULL DEFAULT 'draft' COMMENT 'draft / reviewed / active / retired',
  rule_json            JSON          NOT NULL COMMENT '考试形式、题型映射等',
  effective_from       DATE          NULL,
  official_source      VARCHAR(500)  NULL COMMENT '官方依据名称',
  official_source_url  VARCHAR(500)  NULL,
  reviewed_by          CHAR(36)      NULL,
  reviewed_at          DATETIME(3)   NULL,
  created_at           DATETIME(3)   NOT NULL,
  updated_at           DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_exam_region_rule (region_code, exam_year, subject, scheme_code, version),
  CONSTRAINT ck_exam_region_rules_status CHECK (status IN ('draft', 'reviewed', 'active', 'retired')),
  CONSTRAINT ck_exam_region_rules_active_needs_basis
    CHECK (status <> 'active' OR (official_source IS NOT NULL AND reviewed_by IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 区分试题原始来源地区与推荐适用地区。没有任何记录的自编基础题按"全国通用"处理。
CREATE TABLE question_region_applicability (
  id                       CHAR(36)      NOT NULL,
  question_id              CHAR(36)      NOT NULL,
  origin_region_code       VARCHAR(8)    NULL COMMENT '试题原始来源地区；自编题为 NULL',
  recommended_region_code  VARCHAR(8)    NOT NULL COMMENT '推荐适用地区',
  exam_year_from           SMALLINT      NULL,
  exam_year_to             SMALLINT      NULL,
  review_status            VARCHAR(16)   NOT NULL DEFAULT 'draft' COMMENT 'draft / approved / rejected；仅 approved 参与推荐',
  note                     VARCHAR(500)  NULL,
  reviewed_by              CHAR(36)      NULL,
  created_at               DATETIME(3)   NOT NULL,
  updated_at               DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_question_region (question_id, recommended_region_code),
  KEY ix_qra_region (recommended_region_code, review_status),
  CONSTRAINT fk_qra_question FOREIGN KEY (question_id) REFERENCES questions (id),
  CONSTRAINT ck_qra_years CHECK (exam_year_from IS NULL OR exam_year_to IS NULL OR exam_year_from <= exam_year_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 题目与教材章节的映射按审校版本管理，更换教材不破坏历史记录。
CREATE TABLE question_curriculum_mappings (
  id                  CHAR(36)      NOT NULL,
  question_id         CHAR(36)      NOT NULL,
  curriculum_version  VARCHAR(32)   NOT NULL,
  chapter_code        VARCHAR(64)   NOT NULL,
  chapter_title       VARCHAR(200)  NULL,
  mapping_version     INT           NOT NULL DEFAULT 1,
  review_status       VARCHAR(16)   NOT NULL DEFAULT 'draft',
  reviewed_by         CHAR(36)      NULL,
  created_at          DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_question_curriculum (question_id, curriculum_version, chapter_code, mapping_version),
  CONSTRAINT fk_qcm_question FOREIGN KEY (question_id) REFERENCES questions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------- 模型网关治理

-- 路由可由运营或技术后台更新；每次变更另写 audit_logs。model_ref 是配置引用，不是写死的模型 ID。
CREATE TABLE model_routes (
  id                   CHAR(36)      NOT NULL,
  task_type            VARCHAR(32)   NOT NULL,
  provider             VARCHAR(32)   NOT NULL,
  model_ref            VARCHAR(128)  NOT NULL,
  priority             INT           NOT NULL DEFAULT 0,
  enabled              TINYINT(1)    NOT NULL DEFAULT 0,
  compliance_approved  TINYINT(1)    NOT NULL DEFAULT 0 COMMENT '数据处理协议与未成年人相关要求已核验',
  config_json          JSON          NULL COMMENT '超时、重试、熔断等',
  updated_by           CHAR(36)      NULL,
  updated_at           DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_model_route (task_type, provider)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 每次网关调用一条（含降级）。只记元数据：不保存学生原文、题目图片或模型输出正文。
CREATE TABLE model_call_audits (
  id                     CHAR(36)      NOT NULL,
  request_id             VARCHAR(128)  NOT NULL,
  trace_id               VARCHAR(64)   NOT NULL,
  student_pseudonym      VARCHAR(64)   NOT NULL COMMENT '去标识化 ID',
  task_type              VARCHAR(32)   NOT NULL,
  provider               VARCHAR(32)   NULL,
  model_id               VARCHAR(128)  NULL,
  status                 VARCHAR(16)   NOT NULL COMMENT 'ok / degraded / error',
  error_code             VARCHAR(48)   NULL,
  provider_calls         INT           NOT NULL DEFAULT 0 COMMENT '含重试与换供应商的总调用次数',
  latency_ms             INT           NOT NULL DEFAULT 0,
  input_tokens           INT           NULL,
  output_tokens          INT           NULL,
  image_units            INT           NULL,
  estimated_cost_micros  BIGINT        NULL COMMENT '估算值，仅用于预算，不是账单',
  schema_valid           TINYINT(1)    NULL,
  review_required        TINYINT(1)    NOT NULL DEFAULT 0,
  created_at             DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  KEY ix_model_audit_created (created_at),
  KEY ix_model_audit_request (request_id),
  KEY ix_model_audit_student (student_pseudonym, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 每学生每日与平台每日的额度占用。
CREATE TABLE model_budget_usage (
  id                     CHAR(36)     NOT NULL,
  scope                  VARCHAR(16)  NOT NULL COMMENT 'student / platform',
  scope_key              VARCHAR(64)  NOT NULL COMMENT '学生去标识化 ID，或 platform',
  usage_date             DATE         NOT NULL,
  request_count          INT          NOT NULL DEFAULT 0,
  estimated_cost_micros  BIGINT       NOT NULL DEFAULT 0,
  updated_at             DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_model_budget (scope, scope_key, usage_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
