# 本地纵向切片（ADR-006）实施计划

> **对于 Claude：** 必需的子技能：使用 superpowers:executing-plans 按任务逐步实施此计划。

**目标：** 按 ADR-006 交付一个可在本机端到端跑通的纵向切片：单仓骨架、OpenAPI 与教学事件契约、地区资料（REG-001）、模型网关 Mock 与降级（GW-001）、客观题主流程（今日任务 → 作答 → 提交 → 分层提示 / 解析 / 图解 → 复测），后端与 Flutter 学生端各带自动化测试。

**架构：** 契约先行。`contracts/openapi.yaml` 与 `contracts/tutor_event.schema.json` 是唯一权威；后端每个测试响应都自动按契约校验，Dart 客户端由脚本从同一份契约生成。FastAPI 负责鉴权、教学状态机与确定性判题；教学内容"审核内容优先 → 模型网关 → 规则降级"，网关默认只启用 Mock。开发态用 SQLite 文件保存演示状态，MySQL 迁移 SQL 单独维护并做静态校验。

**技术栈：** Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 · SQLite（开发）/ MySQL 8（迁移目标）· SymPy · jsonschema · pytest · Flutter 3.47.9（Dart 3.13.7）· Riverpod · go_router。

**确认过的前提（2026-11-10，用户选择）：**

1. Flutter SDK 安装到 `C:\src\flutter`，不改系统 PATH，命令一律用绝对路径 `C:\src\flutter\bin\flutter.bat`。
2. 文件夹里缺失的权威文件（OpenAPI、事件 Schema、两份迁移、模型路由配置、AGENTS.md）按 docs/04、05、06、09、10 重新编写。
3. 范围按 ADR-006 切片；拍题 OCR、媒体上传、主观题评分、家长周报、审核后台只进契约（标记 `planned`），服务端返回 501。

**约束：**

- 原始任务卡（ARC-001 / CON-001 / REG-001 / GW-001 的 DoD）不在文件夹内，下面各任务的验收标准由 docs/ 推导，不等同于原 DoD。
- 目录不是 git 仓库，未获授权不执行 `git init` 与提交；计划里不含提交步骤。
- 本机没有 Docker / MySQL / Redis：MySQL 迁移只做静态解析与 ORM 对照，真实库上的 clean install 留给 `tools/verify_migrations.py --mysql-url`。
- 不得由 Agent 决定的事项（DECISIONS_PENDING Q-02 ~ Q-09）一律走配置占位，不写死。

---

## 目录结构

```
contracts/openapi.yaml                 权威 API 契约（OpenAPI 3.1）
contracts/tutor_event.schema.json      教学事件 Schema（JSON Schema 2020-12）
config/model_routes.example.yaml       模型路由示例（外部调用全部禁用）
evaluation/golden_dataset_manifest.csv 评测集登记模板（仅表头）
migrations/001_init.sql                MySQL 基线
migrations/002_region_model_governance.sql
infra/compose.yaml                     MySQL / Redis / 对象存储（开发）
packages/visual_templates/registry.json 图解白名单与参数边界
packages/contracts/dart/               由契约生成的 Dart 包 tutor_contracts
services/ai_gateway/ai_gateway/        模型网关
services/api/tutor_api/                FastAPI 服务
services/api/seed/                     自编工程样题与知识点
apps/flutter_student/                  学生端
apps/admin_web/README.md               占位，本阶段不实现
tools/                                 代码生成、迁移校验、启动脚本
tests/                                 pytest：contract / gateway / unit / api / migrations
```

Python 依赖集中在根 `pyproject.toml`，`uv sync` 生成 `.venv`；包路径通过 pytest 的 `pythonpath` 与启动脚本的 `PYTHONPATH` 提供，不做 editable 安装（项目路径含中文，Python 3.12 读取 `.pth` 用本地编码，容易失败）。

统一测试命令：`uv run pytest -q`。

---

## 任务 1：单仓骨架（ARC-001）

**文件：**
- 创建：`AGENTS.md`、`README.md`、`.gitignore`、`.tool-versions`、`.env.example`、`pyproject.toml`、`infra/compose.yaml`、`apps/admin_web/README.md`

**步骤：**
1. 写根 `pyproject.toml`（依赖、dev 组、pytest 与 ruff 配置）。
2. 运行 `uv sync`，预期创建 `.venv` 且 `uv run python -c "import fastapi, sqlalchemy, sympy"` 无报错。
3. 写 AGENTS.md（阅读顺序、契约先行、禁止写死的事项、测试门禁、命令）与 README.md（如何跑后端、测试、Flutter）。

## 任务 2：契约（CON-001）

**文件：**
- 创建：`contracts/openapi.yaml`、`contracts/tutor_event.schema.json`、`packages/visual_templates/registry.json`
- 测试：`tests/contract/test_contract_files.py`

**先写失败的测试：**
- `test_openapi_is_valid_31`：`openapi-spec-validator` 通过。
- `test_every_operation_declares_id_status_and_errors`：每个操作有唯一 `operationId`、`x-implementation-status ∈ {implemented, planned}`、至少一个 2xx 与通用错误响应。
- `test_non_idempotent_operations_require_idempotency_key`：提交、草稿同步、教学下一步、建会话、建作答、完成复测都把 `Idempotency-Key` 声明为必填头。
- `test_success_bodies_use_data_envelope`：所有 2xx JSON 体是 `{data: ...}`。
- `test_tutor_event_schema_is_valid_2020_12` 与逐类型正反例（`hint` 合法；`visual` 缺 `template_id` 非法；未知 `type` 非法；payload 多余字段非法）。
- `test_visual_registry_matches_doc06`：注册表恰为 `quadratic_graph, rectangle_area, number_line, force_diagram, motion_chart, chemical_flow`，每个参数有有限的 `min/max/default`。

**运行：** `uv run pytest tests/contract -q`，先红后绿。

**契约要点：**
- Base `/api/v1`；成功 `{data}`；错误 `{error:{code,message,details,request_id}}`；`X-Request-Id` 回显。
- 切片内实现的操作：`createLocalIdentity`、`getHealth`、`getLaunchConfig`、`getProfile`、`updateProfile`、`getTodayTasks`、`listQuestions`、`getQuestion`、`createSession`、`getSession`、`listSessionEvents`、`createAttempt`、`getAttempt`、`getDraft`、`syncDraft`、`submitAttempt`、`tutorNext`、`listDueReviews`、`completeReview`、`getProgressSummary`。
- 仅入契约（`planned`，返回 501）：`createMediaUpload`、`createScan`、`getScan`、`confirmScan`、`getParentWeekly`、`reviewQuestion`。
- 教学事件类型：`diagnosis, hint, standard, fast, visual, ask, notice, uncertainty, fallback`；`meta` 记录来源、供应商、模型、提示版本、题目版本、trace。

## 任务 3：迁移与配置

**文件：**
- 创建：`migrations/001_init.sql`、`migrations/002_region_model_governance.sql`、`config/model_routes.example.yaml`、`evaluation/golden_dataset_manifest.csv`、`tools/verify_migrations.py`
- 测试：`tests/migrations/test_migrations_static.py`

**先写失败的测试：**
- `test_migrations_parse_as_mysql`：sqlglot 以 MySQL 方言解析两份 SQL 无错误。
- `test_doc04_tables_exist`：docs/04 的 17 张表全部出现。
- `test_v13_additions_exist`：`student_profiles.region_code/exam_year/exam_scheme_code`、`exam_region_rules`、`question_region_applicability`、`question_curriculum_mappings`、会话地区快照列、模型治理三表。
- `test_orm_columns_are_covered_by_migrations`（任务 5 之后启用）：非原型 ORM 表的每一列都能在迁移里找到。
- `test_example_routes_disable_external_calls`：示例路由中非 mock 供应商 `enabled: false`，且不出现写死的模型 ID、价格、密钥。

## 任务 4：模型网关（GW-001）

**文件：**
- 创建：`services/ai_gateway/ai_gateway/{__init__,dto,config,breaker,budget,audit,validation,visual_templates,gateway}.py`、`providers/{__init__,base,mock,openai_compat}.py`
- 测试：`tests/gateway/test_{routing,validation,resilience,budget,audit,visual_templates,openai_compat}.py`

**先写失败的测试：**
- 路由：按配置顺序取候选；`enabled:false`、未配置环境变量、`compliance_approved:false` 的供应商被跳过；全部不可用时 `status=degraded`、`error_code=MODEL_UNAVAILABLE`。
- 校验：模型输出不符合事件 Schema → 不下发，换下一个候选或降级；`visual` 输出含未注册模板或越界参数 → 拒绝。
- 韧性：超时按配置重试限次；连续失败触发熔断，冷却后半开；熔断期间不再调用该供应商。
- 预算：单请求预算、学生日额度、平台日额度超限 → `BUDGET_EXCEEDED` 降级。
- 审计：每次调用（含降级）写一条不含原文的审计记录，带 `request_id / trace_id / student_pseudonym`。
- 外部适配器：`OpenAICompatAdapter` 仅在显式开启并提供环境变量时可构造，用 `httpx.MockTransport` 测请求形状与错误映射，不发真实网络请求。

## 任务 5：后端基础

**文件：**
- 创建：`services/api/tutor_api/{__init__,main,settings,db,models,proto_models,errors,middleware,idempotency,auth,schemas,clock}.py`、`routers/{dev,meta,planned}.py`
- 测试：`tests/conftest.py`（契约自动校验客户端）、`tests/api/test_foundation.py`

**先写失败的测试：**
- `X-Request-Id` 回显与自动生成；错误体符合信封且不含栈信息。
- 本地身份 Mock 未开启时 `POST /dev/local-identities` 返回 404，其余接口 401；开启后返回随机 bearer，库里只存哈希。
- Mock 开启时非回环来源请求被拒绝（403）。
- 缺 `Idempotency-Key` → 400；同键同请求重放同一响应；同键不同请求 → 409。
- `planned` 操作统一返回 501 `not_implemented`。

## 任务 6：地区资料（REG-001）

**文件：**
- 创建：`routers/profile.py`、`services/profile_service.py`
- 测试：`tests/api/test_profile.py`、`tests/unit/test_exam_year.py`

**先写失败的测试：**
- 考试年份估算以 9 月为学年起点：2026-11 的高三 → 2027，高一 → 2029；2027-03 的高三 → 2027；2027-09 的高三 → 2028。
- `region_code` 只接受 `CN-51 / CN-50`，其他 → 422；不根据任何定位信息推断。
- 教材版本可为空，资料仍算完成，并带"建议补充教材"提示。
- 用户改过的考试年份标记 `exam_year_source=user`，再改年级不被覆盖。
- 启动配置返回两地、三个年级、三门学科和各年级估算年份。

## 任务 7：题库与样题

**文件：**
- 创建：`services/api/seed/knowledge.yaml`、`services/api/seed/questions/*.yaml`、`services/content_seed.py`、`services/question_service.py`、`routers/questions.py`
- 测试：`tests/content/test_seed_content.py`、`tests/api/test_questions.py`

**先写失败的测试：**
- 样题校验：答案键存在于选项；提示逐层且不含最终答案；`fast` 解法必须带适用条件；图解参数通过白名单校验；来源一律 `self_authored`，不出现"真题"字样。
- `GET /questions/{id}` 不含答案、解法、选项分析。
- 地区筛选：四川学生优先拿到带 CN-51 标签且考试年份在区间内的题，不足用通用题补，并标明"全国通用基础题"；重庆学生结果不同；跨年份的地区题不出现。
- 未发布题对学生 404。

## 任务 8：客观题判定

**文件：**
- 创建：`services/grading.py`、`services/mathparse.py`
- 测试：`tests/unit/test_grading.py`、`tests/unit/test_mathparse.py`

**先写失败的测试：**
- 单选对错；多选 `all_or_nothing` 与 `partial_no_wrong` 两种可配规则。
- 填空：字面量归一化（全角、空格）；数值容差；缺单位 / 单位错给出明确原因；表达式等价（`2*x+2` 与 `2(x+1)`）；区间端点开闭可配；无法解析 → `uncertain`，不判错。
- 表达式解析器不使用 `eval`，拒绝 `__import__`、属性访问等输入。

## 任务 9：会话、作答、草稿、提交

**文件：**
- 创建：`routers/{sessions,attempts}.py`、`services/session_service.py`
- 测试：`tests/api/test_attempt_flow.py`

**先写失败的测试：**
- 建会话保存题目版本、地区、考试年份快照；之后切换地区，旧会话快照不变。
- 草稿同步：`base_revision` 匹配则 `revision+1`；不匹配 → 409 并带回服务端版本，不覆盖；超限 → 413。
- 提交：答案形状不符 → 422；同一幂等键重复提交只生成一次评估；已提交再用新键提交 → 409。
- 首次无提示提交 `independent=true`；看过提示或解析后 `assisted=true`；同一会话的重试一律 `assisted`。
- 无法确认的填空 → `state=uncertain`、`is_correct=null`，不计入正确率。
- 答错或辅助答对 → 自动生成复测项。

## 任务 10：教学编排

**文件：**
- 创建：`routers/tutor.py`、`services/{orchestrator,events}.py`
- 测试：`tests/api/test_tutor_flow.py`

**先写失败的测试：**
- `request_hint` 每次只给下一层；提示用尽后给 `notice`。
- 未提交且未确认结束独立作答时 `request_standard / request_fast` → 409；带 `confirm_end_independent=true` 允许，并记 `used_solution`。
- 无审核过的快速解法 → `notice: fast_not_applicable`，不编造。
- `request_visual` 事件的模板与参数经白名单校验；题目无图解 → `notice`。
- 连续 `mark_confused`：第 1 次换讲法，第 2 次给前置知识并推荐图解，第 3 次建议暂停并记 `needs_human_help`，之后不再重复生成。
- 复测会话提交前请求提示 → 409。
- 网关返回非法结构或不可用 → 下发 `fallback` 事件，状态 `FALLBACK`，不伪造评分。
- `GET /sessions/{id}/events?after_seq=` 按序恢复；所有事件通过事件 Schema。

## 任务 11：复测、今日任务、学情

**文件：**
- 创建：`routers/{reviews,tasks,progress}.py`、`services/{review_scheduler,task_planner,progress_service}.py`
- 测试：`tests/api/test_{reviews,tasks,progress}.py`

**先写失败的测试：**
- 间隔默认 T+1 / T+3 / T+7（可配）；复测通过进下一档，全部通过 → `mastered`；失败回到第一档。
- `complete` 只认服务端已判定的作答，不接受客户端自报结果；未判定 → 409。
- 今日任务：新用户给入门题；有到期项给"复习旧错题 / 复测"；有薄弱点与变式时分别出现；无数据返回空数组。
- 学情：独立与辅助正确率分开；样本不足 `rate=null, insufficient_data=true`；`uncertain` 不进分母。

## 任务 12：权限隔离

**文件：**
- 测试：`tests/api/test_security.py`

**先写失败的测试：**
- 学生 B 访问学生 A 的会话、作答、草稿、事件、复测 → 404（防枚举）。
- 请求体里塞别人的 `student_id` 不改变归属。
- 无 token → 401；错误 token → 401。

## 任务 13：Dart 契约包

**文件：**
- 创建：`tools/gen_dart_contracts.py`、`packages/contracts/dart/{pubspec.yaml,lib/tutor_contracts.dart,lib/src/*.dart,test/*.dart}`
- 测试：`tests/contract/test_dart_codegen.py`

**步骤：**
1. 先写 `test_generated_dart_is_up_to_date`（`--check` 模式比较生成结果与落盘文件），运行应失败。
2. 实现生成器：`components.schemas` → 模型类与枚举（未知枚举值落到 `$unknown`）；每个操作 → `TutorApiClient` 方法；需要幂等键的操作参数必填。
3. `C:\src\flutter\bin\dart.bat analyze` 与 `dart test` 通过。

## 任务 14 ~ 18：Flutter 学生端

**文件：** `apps/flutter_student/lib/**`、`apps/flutter_student/test/**`

- 14 基础设施：`flutter create`、主题（深浅色）、路由、API Provider、本地身份引导、令牌与缓存存储、统一的 loading / empty / error / offline 视图。
- 15 引导与首页：三步引导（地区 → 年级与科目 → 教材，可选"暂不清楚"）；首页只有"开始今日学习、拍题、练习、我的"四个入口；任务卡可跳过；拍题入口进入"本阶段未开放"说明页。
- 16 作答页：≥900dp 双栏 42 / 58，可拖到 35–60%；600–899dp 自适应；<600dp 单栏加"题目 / 草稿"切换。单选、多选、填空输入；草稿画布（笔、黑 / 蓝、粗细、橡皮、撤销、重做、清空二次确认、多页）；每 2 秒与切后台本地保存，重开恢复；带 `base_revision` 同步，409 时提示保留本地稿 / 用云端稿 / 建副本。
- 17 辅导与图解：事件时间线；提交前"常规解法 / 快速解法"需要确认结束独立作答；六个白名单模板的 CustomPainter 与滑块、重置；未知模板显示静态说明。
- 18 练习、复测、学情、我的：筛选列表；到期复测；样本不足显示"信息不足"；资料可改，考试年份可见可改。

**测试（先写）：** 断点布局、分栏拖动上下限、三种答题输入的状态、草稿序列化往返与重启恢复、提示按钮在独立作答阶段不泄露解析、未知图解模板不白屏。

**运行：** `C:\src\flutter\bin\flutter.bat analyze` 无 error；`flutter test` 通过。

## 任务 19：端到端验证

1. 起后端：本地身份 Mock 与样题种子显式开启，仅监听 127.0.0.1。
2. `flutter build web`，在浏览器里走完整流程：引导 → 首页 → 做题 → 提示 → 提交 → 解析 → 图解 → 我懂了 → 复测出现。
3. 逐条对照 docs/09 验收与 US-01 / 03 / 04 / 05，记录哪些已验证、哪些因环境限制未验证（真机手写、MySQL、真实模型）。

## 任务 20：文档

- 新增 `docs/ADR-007_切片技术锁定.md`：实际锁定的版本、SQLite 原型表与生产迁移的边界、客户端本地存储选择、同步网关的取舍、未做事项。
- 更新 README 的运行说明。

---

## 不在本计划内

GW-002（真实供应商接入与评测）、EDU-EVAL-001（300 题评测集）、拍题 OCR 与媒体上传、主观题与实验题评分、家长周报、Vue 审核后台、CI 流水线、真机验收。

---

## 进度（2026-11-11）

| 任务 | 状态 | 备注 |
|---|---|---|
| 1 单仓骨架 | 完成 | |
| 2 契约 | 完成 | |
| 3 迁移与配置 | 完成 | 迁移只做了静态校验 |
| 4 模型网关 | 完成 | |
| 5 后端基础 | 完成 | |
| 6 地区资料 | 完成 | |
| 7 题库与样题 | 完成 | 17 道自编样题；`docs/` 下的真题文件没有导入 |
| 8 客观题判定 | 完成 | 没有用 SymPy，见 ADR-007 |
| 9 会话、作答、草稿、提交 | 完成 | |
| 10 教学编排 | 完成 | |
| 11 复测、今日任务、学情 | 完成 | |
| 12 权限隔离 | 完成 | |
| 13 Dart 契约包 | 完成 | 生成器 + 42 个真实响应样例 + 93 项 Dart 测试 |
| 14 Flutter 基础设施 | 完成 | Riverpod、go_router、本地存储、主题、响应式分栏 |
| 15 引导与首页 | 完成 | 三步引导；首页四个入口；今日任务可跳过；断网显示缓存 |
| 16 作答页 | 完成 | 42/58 分栏可拖、手写画布、本地草稿、断网与冲突处理 |
| 17 辅导与图解 | 完成 | 时间线、六个图解模板、"不认识的模板"兜底 |
| 18 练习、复测、学情、我的 | 完成 | |
| 19 端到端验证 | 完成（仅 Web） | 后端用真实 HTTP 走通了主流程；Web 发布版在 Chrome 里与真实后端联调：引导 → 作答 → 提示 → 图解 → 提交 → 解析 → 复测排期 → 次日任务变化；真机与模拟器没有跑过（结果与发现的问题见 ADR-007"浏览器联调"） |
| 20 文档 | 完成 | README、ADR-007、AGENTS.md |

与计划不同的地方：
- 计划里写"每个任务先写失败的测试"。多数任务是这样做的；会话提交、教学编排、复测、权限这几块的测试是和实现同一批写的，第一次运行就是绿的。为了补上"亲眼看它失败"这一步，加了 `tools/mutation_check.py`：把 21 条关键规则逐条改坏，对应的测试全部变红。
- 启动脚本从计划里的 PowerShell 脚本改成了 `tools/run_dev_api.py`，不受执行策略影响。
- 计划里没有的：`.gitignore` 排除了 `docs/` 下的原始题库目录。
- Flutter 一侧同样是先写测试：墨迹控制器、作答控制器、草稿存储、图解计算先看到失败再实现；整页的 widget 测试是在页面写完之后补的，其中暴露了三个真实问题（提交后又新建作答、窄屏公式溢出、首页宽屏布局不可滚动），都已修复。
- 计划里的"Dart 契约包"原定为手写，实际改成了生成器产出，并且把"真实响应样例"作为 Python 后端与 Dart/Flutter 之间的共享测试数据。
- 浏览器联调又暴露了七个原有测试没发现的问题：中文显示成方块（Web 版要联网下载回退字体）、作答页有两个返回箭头、方法要点标签显示公式源码、开口向下的二次函数图解里两种标签叠在一起、手机宽度下首页入口卡没铺满、点开任务又退出后任务从今日任务里消失（后端规则）、系统字体放大时公式与旁边的文字比例不一致（读代码发现）。都已修复并有回归测试（字体问题由 `tests/app/test_cjk_font.py` 看守），细节见 ADR-007"浏览器联调"。共同的原因是测试直接构造页面或只检查文字内容，没有走真实的导航、也没有看渲染结果，还有一条后端测试把不合理的行为固定了下来——这类问题还会有，真机验收时应该再走一遍。
