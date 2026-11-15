-- 004_parent_invites.sql
-- V1.5：家长周报的授权绑定（PRD P0 第 8 条、docs/04 parent_student_links）。追加迁移，不回写 001–003。
-- 家长只能看"已明确授权、可撤销"的学生的汇总周报（US-06）。授权是学生自己做的：学生生成一次性邀请码，
-- 家长输入后才在 parent_student_links 里建立（或重新打开）一条绑定；学生随时可以撤销，撤销立即生效。
-- 这是原型阶段的授权方式：监护授权方案（Q-03）没有冻结，这里不做年龄判断，也不代表法定的监护人核验。

CREATE TABLE parent_invites (
  id           CHAR(36)     NOT NULL,
  student_id   CHAR(36)     NOT NULL,
  code_hash    CHAR(64)     NOT NULL COMMENT '邀请码的 SHA-256；明文只在创建时返回一次，不落库',
  expires_at   DATETIME(3)  NOT NULL,
  redeemed_at  DATETIME(3)  NULL COMMENT '家长输入后填上；一个码只能用一次',
  redeemed_by  CHAR(36)     NULL COMMENT '用它建立绑定的家长',
  revoked_at   DATETIME(3)  NULL COMMENT '学生又生成了新的邀请码，这个作废',
  created_at   DATETIME(3)  NOT NULL COMMENT '学生明确授权的时间，也是绑定记录的 consent_at',
  PRIMARY KEY (id),
  UNIQUE KEY uq_parent_invite_code (code_hash),
  KEY ix_parent_invites_student (student_id, created_at),
  CONSTRAINT fk_invite_student FOREIGN KEY (student_id) REFERENCES users (id),
  CONSTRAINT fk_invite_parent FOREIGN KEY (redeemed_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
