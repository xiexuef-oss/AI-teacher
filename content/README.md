# 样板专题登记（CONTENT-304A）

`sample_content_manifest.csv` 当前只有表头，尚无正式样板题登记。
它用于 docs/07 的样板内容集验收，和 evaluation/ 的至少300道模型评测登记分开。
这里不保存题干、答案、原图、学生信息或授权文件；真实记录与凭据应保存在受控位置，
不要将不宜公开的授权依据和审校身份提交到仓库。

## 使用

```text
uv run python tools/check_sample_content_coverage.py
uv run python tools/check_sample_content_coverage.py private/sample_content_manifest.csv
```

输出JSON计数、专题缺口及固定错误代码/行号，不回显题目ID、作者、审校人或凭据引用。
退出0只表示**登记元数据完整**；退出1表示有缺口、错误或文件不可读。
没有降低正式专题最低题量的命令行选项。当前空模板应退出1。

`registration_complete=true` 不证明题目存在、学科正确、凭据有效、变式经过实际检验，
也不代表版权核验、独立二审或上线许可。工具不打开引用文件、不访问数据库、不联网，
不改变后台发布状态。Q-05 的实际授权范围与学科审校负责人仍待确定。

## 登记规则

每道独立样板题一行；列名和顺序必须与模板相同：

| 字段 | 内容 |
|---|---|
| question_id / question_version | 题库题目UUID及正整数版本，不能用标题代替；只做格式检查，不查询题库 |
| topic_codes | 下表专题编码，以分号分隔；可覆盖同科多个专题，不可重复或跨科混填 |
| source_type / source_name / source_license | 来源类别、来源名称和使用依据；类别复用现有单题导入类型，未自行另立许可类别 |
| license_evidence | 授权凭据引用，由负责人核验实际内容 |
| author_id / reviewer_id | 内容作者和独立审校人的稳定标识，均必填且不同；这里只比较标识，不核验真实身份 |
| reviewed_at / review_evidence | 含时区且不晚于当前时间的审校时间、当前版本审校依据引用 |
| standard_solution_ref | 当前版本的标准解引用，必填；不读取或自动判断其正确性 |
| variant_1_ref / variant_2_ref | 两道变式的`题目UUID@版本`，题目ID须各不相同且不同于样板题；同一道变式的两个版本不算两道 |
| variant_1_review_evidence / variant_2_review_evidence | 分别对应变式固定版本的检验依据引用，必填；不读取或自动认可其内容 |
| is_engineering_sample | 明确填写true或false；true的工程样题不计正式登记 |

已知工程样题许可`internal-engineering-sample`即使被填写为false也排除。
同一道题重复登记、或换版本重复登记，不会增加独立题数，相关行均不计入。
同一行若覆盖两个同科专题，会分别增加两个专题的覆盖数，但独立题总数仍只增加1。
专题归属须由学科审校人确认；工具不能判断实际题目是否适合所声明专题。

## 最低专题覆盖

每专题至少5道带上述完整登记的样板题，每题有一份标准解和两个变式及其检验依据引用。
因此空模板有45个专题覆盖缺口；这不是数据库题量统计，也不将跨专题的一道题变成多道题。

| 编码 | 专题 |
|---|---|
| math.function_monotonicity | 函数与单调性 |
| math.basic_inequality | 基本不等式 |
| math.proof | 证明 |
| physics.force_motion | 受力与运动 |
| physics.circuit | 电路 |
| physics.experiment | 物理实验 |
| chemistry.conservation | 守恒计算 |
| chemistry.inference | 物质推断 |
| chemistry.experiment | 化学实验 |

这些是 docs/07 的样板专题登记编码，不是地区考试细则或教材章节映射。
教材、省份、年份的实际适配仍按 Q-08/Q-09 单独确认；证明、实验等主观题仍不自动评分。

输入限制为4MiB、10000行；多列/缺列、未知专题、无效版本/来源/时间、重复ID与自审均不计入。
临时自编测试登记只用于工具回归，不会填入实际空模板，不冒充已经获得授权或人工审校。

## 本轮证据（2026-11-17）

- 相关回归111项通过：`var/content304-coverage-final-r2.log`；其中38项为本工具用例，其余复用既有评测工具和变异运行器回归。
- 多专题登记缺失的行为红测：`var/content304-multiple-topics-red.log`。初始工具文件缺失的收集错误保留作开发诊断，不冒充业务断言证据。
- 5/5定向变异捕获：`var/content304-mutations-r2/mutation-evidence-lthc53l2/summary.json`，无跳过、基线失败或执行错误。
- 隔离快照371文件恢复及关键源码一致：`var/content304-source-verification.json`。
- 实际空模板检查：`var/content304-current-registration.json`，退出1，登记0条、9个专题各缺5个覆盖记录；不作为数据库完整盘点。
- Ruff与格式检查通过；未改变公开API、客户端、样题、生产配置或后台发布状态。未重跑项目全量门禁，此轮证据只覆盖上述工具增量。
