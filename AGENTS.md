# AGENTS.md

给在本仓库工作的开发 Agent（以及人）的约定。与其他文档冲突时，以 `docs/DECISIONS_PENDING.md` 的"已明确"条目和 `contracts/` 下的契约为准。

## 先读什么

1. 本文件与 `README.md`。
2. `docs/DECISIONS_PENDING.md`：哪些已冻结，哪些不能由 Agent 决定。
3. `docs/09_首发区域与教材题库适配.md`、`docs/10_AI模型网关与成本治理.md`。
4. `docs/ADR-006_本地纵向切片.md`、`docs/ADR-007_切片技术锁定.md`：当前阶段做了什么、没做什么。
5. 你要改的模块对应的 docs/01 ~ 08。

## 硬规则

**契约先行。** 新增或修改公开 API：先改 `contracts/openapi.yaml`，再写测试，再写实现，最后重新生成 Dart 契约包并导出新的响应样例、重新生成审核后台的 TypeScript 类型（见下方"命令"）。契约里不能有重复的键——YAML 默认让后写的悄悄覆盖先写的，契约测试会拦住。客户端请求对象只用生成的类型，不手写；`*.g.dart` 不要手改。删除或重命名 JSON 字段是破坏性变更。

**学生的输入先落本机。** 客户端的草稿（答案、笔迹）先写本机存储、再同步云端；断网、重启、切后台都不能丢；同步冲突时不覆盖任何一方，由学生选。每个会改变服务端状态的动作带幂等键，失败后重试复用同一个键。

**教学事件必须过 Schema。** 任何发往客户端的教学事件都要通过 `contracts/tutor_event.schema.json`；`visual` 事件只能使用 `packages/visual_templates/registry.json` 里注册的模板和参数范围。渲染器不解释模型返回的脚本、HTML 或代码。

**不确定就弃判。** 判不出来的作答标 `uncertain`，不算对也不算错，不进正确率分母。练习反馈不是官方阅卷分数，界面和接口都不能这样表述。

**解答题不自动评分。** `written` 的作答状态是 `pending`，永远不判对错（哪怕和参考答案一字不差）；提交之后学生对照 `rubric.points` 自查，自查要点只能在提交之后给，不带分值，不进任何正确率，也不据此排复测。要接 AI 评分，先等 Q-06 冻结，并经模型网关。

**独立作答阶段不泄题。** 提交前只给不含答案的分层提示；完整解析需要学生明确选择，并记录 `used_solution`。

**权限来自 token。** 请求里的 `student_id` 只是资源关联，不作为授权依据。跨账号访问一律 404。

**不要写死这些东西：** 模型 ID、供应商端点、价格、密钥、地区考试规则、教材与省份的对应关系。它们全部走配置，示例配置里外部调用保持禁用。

**不要替负责人做决定。** `docs/DECISIONS_PENDING.md` 里 Q-02 ~ Q-09 没冻结之前，只能用文档允许的原型处理方式（Mock、占位、draft）。

**样题就是样题。** `services/api/seed/` 里是自编工程样题，没有经过学科审校，不得标称真题或某地区高考风格。地区标签只用于测试筛选逻辑。

**迁移只追加。** 已有的 `migrations/NNN_*.sql` 不回写。`proto_` 开头的表只存在于本地 SQLite 原型，不进生产迁移。

**客户端不碰模型密钥，** 也不直连任何模型供应商。所有模型调用走 `services/ai_gateway`。

## 目录

| 路径 | 内容 |
|---|---|
| `contracts/` | OpenAPI 与教学事件 Schema，唯一权威 |
| `packages/visual_templates/` | 图解模板白名单与参数边界 |
| `packages/contracts/dart/` | 由契约生成的 Dart 包；`lib/src/runtime.dart` 是手写的传输层，`*.g.dart` 不要手改 |
| `services/api/` | FastAPI 服务与样题种子 |
| `services/ai_gateway/` | 模型网关：路由、适配器、校验、熔断、预算、审计 |
| `apps/flutter_student/` | Flutter 学生端 |
| `apps/admin_web/` | 内容审核后台（Vue 3 + Vite + TypeScript），最小审核流已实现，见 ADR-008 |
| `migrations/` | MySQL 迁移 SQL |
| `config/` | 模型路由示例配置 |
| `tools/` | 本地启动脚本、迁移校验、变异检查 |
| `tests/` | pytest：契约、网关、单元、API、迁移、样题内容 |
| `docs/*高考真题/` | 用户提供的原始试卷文件（约 8.4 GB），未导入、不进仓库，见 ADR-007 |

## 命令

```
uv sync                                         # 安装 Python 依赖到 .venv
uv run pytest -q                                # 后端、网关、契约、迁移静态校验
uv run ruff check . ; uv run ruff format .      # lint 与格式化
uv run python tools/verify_migrations.py        # 迁移静态校验；加 --mysql-url 对真实库做 clean install
uv run python tools/mutation_check.py           # 把关键规则逐条改坏，确认测试会变红（约 5 分钟）
uv run python tools/run_dev_api.py              # 本地 API（127.0.0.1:8000，显式开启身份 Mock 与样题）
```

```
uv run python tools/gen_dart_contracts.py          # 由契约生成 Dart 包；--check 只检查是否过期
uv run python tools/export_dart_fixtures.py        # 导出真实响应样例与公式片段（改了契约或后端响应后运行）
uv run --with fonttools python tools/build_cjk_font.py   # 重新生成打包的中文字体子集（出现新的汉字、测试提示缺字时运行）
```

```
cd apps/admin_web
npm test                 # vitest：API 客户端、决策规则、公式渲染、队列页、审核页
npm run typecheck        # vue-tsc；测试数据按契约类型写
npm run check:api        # src/api/schema.d.ts 是否由当前契约生成；契约改了先 npm run gen:api
```

Flutter 已安装但没有加入系统 PATH，命令用绝对路径。在 `apps/flutter_student`（或 `packages/contracts/dart`）下执行：

```
C:\src\flutter\bin\flutter.bat test                # widget / 单元测试
C:\src\flutter\bin\dart.bat analyze                # 静态检查。不要用 flutter analyze：项目路径含中文时它会崩溃
C:\src\flutter\bin\dart.bat format lib test        # 格式化；之后 dart fix --apply 补花括号等 lint
C:\src\flutter\bin\flutter.bat build web --release # 构建 Web 版（联调用）
```

## 测试门禁

- 先写会失败的测试，看它因为功能缺失而失败，再写实现。
- `tests/support/api.py` 里的客户端会把每个响应按 `contracts/openapi.yaml` 校验一遍；响应不符合契约，测试直接失败。
- 改了归属校验、泄题门控、判题、幂等、复测这类规则之后，跑一遍 `tools/mutation_check.py`；如果改动了被变异的代码行，要同步更新脚本里的片段。
- 合并前全绿：`uv run pytest -q`、`uv run ruff check .`；`apps/flutter_student` 下的 `flutter test` 与 `dart analyze`；`packages/contracts/dart` 下的 `dart test`；`apps/admin_web` 下的 `npm test`、`npm run typecheck`、`npm run check:api`。
- 分支命名 `feat/TASK-ID-*`，提交说明列出任务 ID 和测试证明。
