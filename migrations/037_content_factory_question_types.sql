CREATE TABLE cf_question_types (
  id CHAR(36) NOT NULL PRIMARY KEY,
  code VARCHAR(90) NOT NULL UNIQUE,
  subject VARCHAR(16) NOT NULL,
  title VARCHAR(200) NOT NULL,
  province_code CHAR(5) NULL,
  exam_year SMALLINT NULL,
  curriculum_version VARCHAR(80) NULL,
  specification_json JSON NOT NULL,
  status VARCHAR(16) NOT NULL,
  created_by CHAR(36) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  FOREIGN KEY (created_by) REFERENCES users(id),
  CONSTRAINT ck_cf_question_type_status CHECK (status IN ('draft', 'approved', 'deprecated'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE cf_question_type_knowledge (
  question_type_id CHAR(36) NOT NULL,
  knowledge_id CHAR(36) NOT NULL,
  relation VARCHAR(16) NOT NULL,
  PRIMARY KEY (question_type_id, knowledge_id, relation),
  FOREIGN KEY (question_type_id) REFERENCES cf_question_types(id),
  FOREIGN KEY (knowledge_id) REFERENCES knowledge_nodes(id),
  CONSTRAINT ck_cf_question_type_relation CHECK (relation IN ('primary', 'prerequisite', 'supporting'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
