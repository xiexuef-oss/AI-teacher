CREATE TABLE learning_pack_return_details (
  job_id CHAR(36) NOT NULL,
  code CHAR(3) NOT NULL,
  completed_on DATE NULL,
  independence VARCHAR(16) NOT NULL,
  PRIMARY KEY (job_id, code),
  FOREIGN KEY (job_id, code) REFERENCES learning_pack_returns(job_id, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
