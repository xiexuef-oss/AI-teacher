# 评测集登记（EDU-EVAL-001，工具准备中）

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

登记后运行 `uv run python tools/validate_evaluation_manifest.py`。
默认要求至少300条有效登记，输出JSON并以退出码1表示不完整；当前空模板应当返回1。
`--minimum 1` 仅用于小样/工具验证，不能代替正式题量要求。
工具检查列名、必填授权/审校/答案引用、重复ID、枚举、难度、年份和含时区的审校时间；主观题还需rubric引用。
`ready` 只表示登记字段完整，不验证凭据内容或引用文件存在，不是版权核验、学科审校或上线许可。
工具不读取试卷、答案及凭据，不联网；不要把真实学生信息或未授权材料放入公开仓库。

## 结果覆盖检查（EVAL-301A）

结果元数据可先用 `tools/summarize_evaluation.py` 汇总准确率、弃判、延迟和已知/未知费用。
另用下列命令将结果与登记表关联：

```
uv run python tools/check_evaluation_coverage.py evaluation/golden_dataset_manifest.csv private/results.jsonl
```

默认要求至少300道字段完整的登记。每条结果的 item_id 与 answer_mode 必须匹配登记，
provider/model 必须明确；重复请求不能充当新题目，不同 task/provider/model 分别统计。
每个已出现的组合都覆盖这份登记表的全部题目，才返回 ready=true 和退出码0。
因此同一份登记应只包含该评测范围实际要求覆盖的题目。缺结果、文件不可读或格式错误返回1，
只输出固定错误代码和计数，不输出题目、答案、授权凭据或审校人。

这里的 ready 表示组合的登记元数据覆盖完整。用可重复的 `--require-group TASK PROVIDER MODEL`
指定本次评测要求的任务、供应商和模型；缺失的指定组合会报告全部登记题目缺结果。
工具也不验证模型标识的真实性、许可证内容、学科质量或上线资格。
失败/弃判也是已尝试题目，不能用覆盖率代替准确率或有效调用成功率。
`--minimum 1` 仅用于工程小样，不替代正式300题要求；当前空登记表必须失败。

2026-11-17工具证据：`var/evaluation-coverage-green.log`，与登记校验和结果汇总共37项通过；
实际空模板检查见 `var/evaluation-coverage-current-dataset.log`，退出1。
未知模型仍能错误通过的中间失败用例见 `var/evaluation-coverage-red.log`，修复后通过。
