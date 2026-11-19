CREATE TABLE weekly_report_snapshots (
  student_id CHAR(36) NOT NULL,
  week_start DATE NOT NULL,
  revision INT NOT NULL,
  summary_json JSON NOT NULL,
  generated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (student_id, week_start, revision),
  FOREIGN KEY (student_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
