# 离线评测结果格式（EVAL-301）

本工具只汇总已获授权的本地评测结果元数据，不调用模型，不读取题面、答案、图片或学生资料。它不验证授权凭据，不验证人工标注是否正确，也不代表已完成300题评测。当前题库登记仍以 `golden_dataset_manifest.csv` 和其校验工具为准；输入 `item_id` 应由操作者关联已授权、审校的登记项。

运行：

```powershell
uv run python tools/summarize_evaluation.py C:\private-evaluation\results.jsonl
```

标准输出为单个JSON报告。退出码0表示输入完整合法并已汇总，1表示内容、重复ID、资源限制或文件读取错误；命令行参数错误退出2。无效文件不输出部分聚合，`overall` 为 null，`groups` 为空。错误只含行号和错误类别，不回显输入值。空文件、空行、重复JSON键、超长行均拒绝；每行最多1MiB，最多100000行。

每行一个JSON对象。以下仅为自编工具样例，不是实测结果：

```json
{"request_id":"fixture-call-1","item_id":"self-authored-1","task_type":"ocr_extract","answer_mode":"single_choice","provider":"fixture-provider","model":"fixture-model","status":"ok","verdict":"correct","review_required":false,"latency_ms":100,"input_tokens":20,"output_tokens":10,"image_units":null,"estimated_cost_micros":null}
```

字段约定：

| 字段 | 规则 |
|---|---|
| `request_id` | 每次调用唯一；整文件不允许重复，重试使用新调用ID |
| `item_id` | 授权登记项的匿名ID；不同模型或重试可重复 |
| `task_type` | 使用网关 `TaskType` 已注册任务，不硬编码模型或供应商清单 |
| `answer_mode` | `single_choice`、`multiple_choice`、`fill`、`written`、`experiment`、`proof` |
| `provider`、`model` | 配置里的匿名供应商/模型标识；未调用或未知时显式 null |
| `status` | `ok`、`degraded`、`error`，只有 `ok` 算成功 |
| `verdict` | `correct`、`incorrect`、`uncertain`、`pending`；非ok状态不能有确定对错 |
| `review_required` | 必填JSON布尔值，不接受字符串 |
| `latency_ms` | 必填非负整数，包括失败调用的耗时 |
| `input_tokens`、`output_tokens`、`image_units`、`estimated_cost_micros` | 非负整数或null；缺省也表示未知，不当成0 |

所有计数/耗时最大为有符号64位整数；拒绝负数、浮点、布尔冒充整数。ID和模型/供应商标识只允许1~128位ASCII字母、数字以及 `_ . / : -`。这些字段只能放匿名标识，不得编码题面、原图、姓名、学生身份、密钥或供应商原始响应。额外字段一律拒绝。

主观题边界直接复用 `grading.SUBJECTIVE_MODES`：written/experiment/proof只接受 `pending`，即使离线人工认为答案正确，也不能在本文件中写成自动correct/incorrect。将来需要人工评价时，应设计独立格式与维度，不能混入当前自动可判定正确率。

报告包含全体 `overall` 和按 `(task_type, provider, model)` 分组的 `groups`：

- 成功率：ok请求数 / 所有请求数；降级与失败均在分母内。
- `accuracy`：correct / (correct + incorrect)，uncertain和pending均不入分母；无可判定项时为null。它是调用结果的可判定正确率，不是官方阅卷分数。
- 人工复核率：review_required为true的请求数 / 所有请求数。
- 延迟：平均值和最近秩p95，即排序后第ceil(0.95×N)项。
- 每个usage字段分别输出 `total`、`known_total`、`unknown_count`。只要有一条未知，total为null；known_total仅为已知部分的小计。全部未知时known_total可以是0，但total仍为null。

费用来自输入的网关估算，工具不内置价格、不计算真实账单。请求数不是去重题目数，同一道题多次调用会分别计数；这些汇总不检查地区、学科、模态分布或正式上线所需的300道授权题覆盖度。
