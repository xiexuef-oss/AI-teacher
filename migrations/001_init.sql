-- 001_init.sql
-- 基线结构（docs/04）。MySQL 8.0 / InnoDB / utf8mb4。
-- 约定：ID 为 UUID v4，存 CHAR(36)；时间为 UTC，存 DATETIME(3)；JSON 的形状由应用层校验。
-- 迁移只追加：本文件部署后不得回写，后续变更写新的迁移文件。

CREATE TABLE users (
  id            CHAR(36)     NOT NULL,
  role          VARCHAR(16)  NOT NULL COMMENT 'student / parent / reviewer / admin',
  email_hash    CHAR(64)     NULL COMMENT '邮箱的 SHA-256；身份映射由后续 auth provider 增补',
  display_name  VARCHAR(80)  NULL,
  status        VARCHAR(16)  NOT NULL DEFAULT 'active',
  created_at    DATETIME(3)  NOT NULL,
  updated_at    DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email_hash (email_hash),
  CONSTRAINT ck_users_role CHECK (role IN ('student', 'parent', 'reviewer', 'admin'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE student_profiles (
  user_id             CHAR(36)     NOT NULL,
  grade               VARCHAR(8)   NULL COMMENT 'G10 / G11 / G12，可暂缺',
  region              VARCHAR(64)  NULL COMMENT 'V1.2 遗留字段，仅保留兼容；新逻辑见 002 的 region_code',
  curriculum_version  VARCHAR(32)  NULL COMMENT '教材版本，未知为 NULL',
  created_at          DATETIME(3)  NOT NULL,
  updated_at          DATETIME(3)  NOT NULL,
  PRIMARY KEY (user_id),
  CONSTRAINT fk_student_profiles_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE parent_student_links (
  id          CHAR(36)     NOT NULL,
  parent_id   CHAR(36)     NOT NULL,
  student_id  CHAR(36)     NOT NULL,
  consent_at  DATETIME(3)  NOT NULL COMMENT '明确授权时间',
  revoked_at  DATETIME(3)  NULL COMMENT '撤销后立即失去访问权限',
  created_at  DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_parent_student (parent_id, student_id),
  CONSTRAINT fk_psl_parent FOREIGN KEY (parent_id) REFERENCES users (id),
  CONSTRAINT fk_psl_student FOREIGN KEY (student_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE knowledge_nodes (
  id          CHAR(36)      NOT NULL,
  subject     VARCHAR(16)   NOT NULL,
  code        VARCHAR(64)   NOT NULL,
  title       VARCHAR(120)  NOT NULL,
  summary     VARCHAR(500)  NULL,
  created_at  DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_knowledge_subject_code (subject, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE knowledge_edges (
  id         CHAR(36)  NOT NULL,
  prereq_id  CHAR(36)  NOT NULL,
  target_id  CHAR(36)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_knowledge_edge (prereq_id, target_id),
  CONSTRAINT fk_ke_prereq FOREIGN KEY (prereq_id) REFERENCES knowledge_nodes (id),
  CONSTRAINT fk_ke_target FOREIGN KEY (target_id) REFERENCES knowledge_nodes (id),
  CONSTRAINT ck_knowledge_edge_no_self_loop CHECK (prereq_id <> target_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE questions (
  id               CHAR(36)      NOT NULL,
  subject          VARCHAR(16)   NOT NULL,
  type             VARCHAR(24)   NOT NULL COMMENT '题型',
  answer_mode      VARCHAR(24)   NOT NULL COMMENT '作答区渲染方式',
  status           VARCHAR(16)   NOT NULL DEFAULT 'draft' COMMENT 'draft / reviewed / published / withdrawn',
  version          INT           NOT NULL DEFAULT 1 COMMENT '当前版本号',
  difficulty       TINYINT       NOT NULL DEFAULT 3,
  grade            VARCHAR(8)    NULL,
  source_type      VARCHAR(24)   NOT NULL,
  source_category  VARCHAR(16)   NOT NULL COMMENT 'gaokao_real / mock_exam / foundation / ai_variant',
  source_name      VARCHAR(200)  NULL,
  source_year      SMALLINT      NULL,
  source_license   VARCHAR(120)  NOT NULL,
  source_url       VARCHAR(500)  NULL,
  variant_of_id    CHAR(36)      NULL COMMENT '变式题指向母题',
  created_by       CHAR(36)      NULL,
  reviewed_by      CHAR(36)      NULL COMMENT '不得与 created_by 相同',
  published_at     DATETIME(3)   NULL,
  created_at       DATETIME(3)   NOT NULL,
  updated_at       DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  KEY ix_questions_delivery (status, subject, answer_mode),
  KEY ix_questions_variant_of (variant_of_id),
  CONSTRAINT fk_questions_variant_of FOREIGN KEY (variant_of_id) REFERENCES questions (id),
  CONSTRAINT ck_questions_status CHECK (status IN ('draft', 'reviewed', 'published', 'withdrawn')),
  CONSTRAINT ck_questions_difficulty CHECK (difficulty BETWEEN 1 AND 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE question_versions (
  id             CHAR(36)     NOT NULL,
  question_id    CHAR(36)     NOT NULL,
  version        INT          NOT NULL,
  content_json   JSON         NOT NULL COMMENT 'title, stem, options[], blanks[], subquestions[], attachments[]',
  answer_json    JSON         NOT NULL COMMENT 'value, equivalence_rules, units',
  teaching_json  JSON         NULL COMMENT '分层提示、换种讲法、选项分析、图解参数',
  created_by     CHAR(36)     NULL,
  created_at     DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_question_version (question_id, version),
  CONSTRAINT fk_qv_question FOREIGN KEY (question_id) REFERENCES questions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE question_knowledge (
  question_id   CHAR(36)  NOT NULL,
  knowledge_id  CHAR(36)  NOT NULL,
  PRIMARY KEY (question_id, knowledge_id),
  CONSTRAINT fk_qk_question FOREIGN KEY (question_id) REFERENCES questions (id),
  CONSTRAINT fk_qk_knowledge FOREIGN KEY (knowledge_id) REFERENCES knowledge_nodes (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE solutions (
  id               CHAR(36)     NOT NULL,
  question_id      CHAR(36)     NOT NULL,
  version          INT          NOT NULL COMMENT '对应的题目版本',
  kind             VARCHAR(16)  NOT NULL COMMENT 'standard / fast',
  content_json     JSON         NOT NULL,
  conditions_json  JSON         NULL COMMENT '快速解法的适用条件与反例',
  reviewed         TINYINT(1)   NOT NULL DEFAULT 0,
  reviewed_by      CHAR(36)     NULL,
  created_at       DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_solution (question_id, version, kind),
  CONSTRAINT fk_solutions_question FOREIGN KEY (question_id) REFERENCES questions (id),
  CONSTRAINT ck_solutions_kind CHECK (kind IN ('standard', 'fast')),
  CONSTRAINT ck_solutions_fast_needs_conditions CHECK (kind <> 'fast' OR conditions_json IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE rubrics (
  id           CHAR(36)     NOT NULL,
  question_id  CHAR(36)     NOT NULL,
  version      INT          NOT NULL COMMENT '对应的题目版本',
  rubric_json  JSON         NOT NULL,
  created_at   DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_rubric (question_id, version),
  CONSTRAINT fk_rubrics_question FOREIGN KEY (question_id) REFERENCES questions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE study_sessions (
  id                   CHAR(36)     NOT NULL,
  student_id           CHAR(36)     NOT NULL,
  question_id          CHAR(36)     NOT NULL,
  question_version     INT          NOT NULL COMMENT '开启会话时的题目版本快照',
  state                VARCHAR(24)  NOT NULL COMMENT 'docs/06 教学状态机',
  origin               VARCHAR(16)  NOT NULL COMMENT 'task / practice / review / variant',
  review_item_id       CHAR(36)     NULL,
  parent_session_id    CHAR(36)     NULL,
  assisted             TINYINT(1)   NOT NULL DEFAULT 0,
  used_solution        TINYINT(1)   NOT NULL DEFAULT 0,
  independent_ended    TINYINT(1)   NOT NULL DEFAULT 0,
  hint_level_revealed  INT          NOT NULL DEFAULT 0,
  confused_streak      INT          NOT NULL DEFAULT 0,
  needs_human_help     TINYINT(1)   NOT NULL DEFAULT 0,
  created_at           DATETIME(3)  NOT NULL,
  updated_at           DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  KEY ix_sessions_student_created (student_id, created_at),
  KEY ix_sessions_student_question (student_id, question_id),
  CONSTRAINT fk_sessions_student FOREIGN KEY (student_id) REFERENCES users (id),
  CONSTRAINT fk_sessions_question FOREIGN KEY (question_id) REFERENCES questions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE attempts (
  id                CHAR(36)      NOT NULL,
  session_id        CHAR(36)      NOT NULL,
  attempt_no        INT           NOT NULL,
  status            VARCHAR(16)   NOT NULL DEFAULT 'draft' COMMENT 'draft / submitted',
  answer_json       JSON          NULL COMMENT '各小问与步骤，以及模型读到的 OCR 校正记录',
  assisted          TINYINT(1)    NOT NULL DEFAULT 0,
  used_solution     TINYINT(1)    NOT NULL DEFAULT 0,
  independent       TINYINT(1)    NULL COMMENT '提交时确定',
  evaluation_state  VARCHAR(16)   NULL COMMENT 'pending / verified / uncertain / error',
  outcome           VARCHAR(24)   NULL,
  is_correct        TINYINT(1)    NULL COMMENT '仅 verified 时非空',
  evaluation_json   JSON          NULL,
  request_id        VARCHAR(128)  NULL COMMENT '提交使用的幂等键',
  elapsed_ms        INT           NULL,
  submitted_at      DATETIME(3)   NULL,
  created_at        DATETIME(3)   NOT NULL,
  updated_at        DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_attempt_no (session_id, attempt_no),
  UNIQUE KEY uq_attempt_request (request_id),
  CONSTRAINT fk_attempts_session FOREIGN KEY (session_id) REFERENCES study_sessions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE handwriting_drafts (
  id            CHAR(36)      NOT NULL,
  attempt_id    CHAR(36)      NOT NULL,
  revision      INT           NOT NULL DEFAULT 0 COMMENT '单调递增；同步须带 base_revision，冲突不静默覆盖',
  strokes_json  JSON          NULL,
  media_key     VARCHAR(255)  NULL COMMENT '缩略图或备份的对象键',
  updated_at    DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_draft_attempt (attempt_id),
  CONSTRAINT fk_drafts_attempt FOREIGN KEY (attempt_id) REFERENCES attempts (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE tutor_events (
  id          CHAR(36)     NOT NULL,
  session_id  CHAR(36)     NOT NULL,
  seq_no      INT          NOT NULL,
  event_type  VARCHAR(24)  NOT NULL,
  event_json  JSON         NOT NULL COMMENT '已通过 tutor_event.schema.json 的完整事件',
  created_at  DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_event_seq (session_id, seq_no),
  CONSTRAINT fk_events_session FOREIGN KEY (session_id) REFERENCES study_sessions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE review_items (
  id                 CHAR(36)     NOT NULL,
  student_id         CHAR(36)     NOT NULL,
  question_id        CHAR(36)     NOT NULL,
  status             VARCHAR(16)  NOT NULL DEFAULT 'scheduled' COMMENT 'scheduled / mastered / paused',
  stage              INT          NOT NULL DEFAULT 0 COMMENT '已通过的复测档数',
  due_at             DATETIME(3)  NOT NULL,
  last_result        VARCHAR(16)  NULL COMMENT 'passed / failed，只来自实测',
  last_attempt_id    CHAR(36)     NULL,
  origin_session_id  CHAR(36)     NULL,
  created_at         DATETIME(3)  NOT NULL,
  updated_at         DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_review_student_question (student_id, question_id),
  KEY ix_review_due (student_id, status, due_at),
  CONSTRAINT fk_review_student FOREIGN KEY (student_id) REFERENCES users (id),
  CONSTRAINT fk_review_question FOREIGN KEY (question_id) REFERENCES questions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE media_assets (
  id          CHAR(36)      NOT NULL,
  owner_id    CHAR(36)      NOT NULL,
  object_key  VARCHAR(255)  NOT NULL COMMENT '私有对象，访问须鉴权并使用短期签名 URL',
  mime        VARCHAR(64)   NOT NULL,
  sha256      CHAR(64)      NOT NULL,
  size_bytes  BIGINT        NOT NULL,
  purpose     VARCHAR(24)   NOT NULL,
  created_at  DATETIME(3)   NOT NULL,
  deleted_at  DATETIME(3)   NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_media_object_key (object_key),
  KEY ix_media_owner (owner_id, created_at),
  CONSTRAINT fk_media_owner FOREIGN KEY (owner_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE audit_logs (
  id           CHAR(36)      NOT NULL,
  actor_id     CHAR(36)      NULL,
  action       VARCHAR(64)   NOT NULL,
  target_type  VARCHAR(48)   NOT NULL,
  target_id    CHAR(36)      NULL,
  detail_json  JSON          NULL COMMENT '不得包含学生原文、草稿或图片',
  request_id   VARCHAR(128)  NULL,
  created_at   DATETIME(3)   NOT NULL,
  PRIMARY KEY (id),
  KEY ix_audit_target (target_type, target_id),
  KEY ix_audit_actor (actor_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
