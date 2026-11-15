# 评测集登记（EDU-EVAL-001，尚未开始）

`golden_dataset_manifest.csv` 目前只有表头。docs/10 要求在学生正式使用前，用不少于 300 道**有授权、经审校、已标注**的题目建立模型质量基线；这些题目还没有收集，表里不要填入没有授权依据的题。

每行登记一道评测题：

| 列 | 说明 |
|---|---|
| `item_id` | 评测题 ID |
| `subject` / `question_type` / `answer_mode` | 学科、题型、作答方式 |
| `modality` | text / image / handwriting / chart |
| `region_code` / `exam_year` | 适用地区与考试年份，通用题留空 |
| `knowledge_codes` | 知识点编码，分号分隔 |
| `difficulty` | 1–5 |
| `source_type` / `source_name` / `source_year` | 来源 |
| `source_license` / `license_evidence` | 许可类型与凭据位置 |
| `reviewer` / `reviewed_at` | 审校人与时间 |
| `answer_key_ref` / `rubric_ref` | 标准答案与评分细则的存放位置 |
| `notes` | OCR 噪声、等价答案、多解、单位遗漏等评测关注点 |

建议权重（docs/10，初始值，可调，不代表实测）：答案推导 35%、错误诊断与分步评价 20%、教学效果 20%、图文与手写识别 15%、延迟与成本 10%。
