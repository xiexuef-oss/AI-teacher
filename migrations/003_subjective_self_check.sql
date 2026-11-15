-- 003_subjective_self_check.sql
-- V1.4：解答题（主观题）提交后的对照自查（PRD P0 第 3、4 条）。追加迁移，不回写 001、002。
-- 解答题不自动评分（Q-06：低置信度弃判，不冒充官方阅卷）：学生提交后对照题目的要点清单，
-- 给每个要点标"做到了 / 做到一部分 / 没做到"。这是学生自己的记录，不折算成分数，也不进任何正确率。

CREATE TABLE attempt_self_checks (
  id          CHAR(36)     NOT NULL,
  attempt_id  CHAR(36)     NOT NULL,
  marks_json  JSON         NOT NULL COMMENT '[{point_key, level}]；level 取 done / partial / missed；不含分数',
  created_at  DATETIME(3)  NOT NULL,
  updated_at  DATETIME(3)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_self_check_attempt (attempt_id),
  CONSTRAINT fk_self_check_attempt FOREIGN KEY (attempt_id) REFERENCES attempts (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
