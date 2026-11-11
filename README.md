# 高中理科 AI 私教

面向高中数学、物理、化学的 AI 私教。首发地区四川、重庆；学生端计划用 Flutter（平板横屏优先）。需求与决策在 `docs/`，接口契约在 `contracts/`。

## 现在做到哪了

按 `docs/ADR-006_本地纵向切片.md` 的范围推进：**后端和 Flutter 学生端都已完成，能在本机端到端跑通；还没有在真机或模拟器上运行过。**

| 部分 | 状态 |
|---|---|
| 接口契约（OpenAPI、教学事件 Schema、图解模板白名单） | 完成 |
| MySQL 迁移 SQL、模型路由示例配置 | 完成；迁移只做过静态校验，没有在真实 MySQL 上执行 |
| 模型网关（路由、Mock、输出校验、重试熔断、预算、审计） | 完成；外部供应商全部禁用，真实接入未做 |
| 后端 API：地区资料、题目、会话、作答、草稿、提交判定、分层提示与解析、图解、复测、今日任务、学情 | 完成，只能在本机以原型方式运行（SQLite + 本地身份 Mock） |
| 17 道自编工程样题 + 3 道待审样题（`seed/drafts/`，学生看不到） | 完成；没有经过学科审校 |
| Dart 契约包（由契约生成） | 完成 |
| Flutter 学生端：引导、首页、练习、作答（题目/草稿分栏、手写画布、本地草稿、断网与冲突处理）、辅导时间线、六个图解模板、复测、学情、我的 | 完成；只在 Flutter 测试框架和 Chrome 里验证过，Android/iOS 没有构建 |
| 内容审核最小流（后端 + Vue 3 审核后台）：题目 draft → reviewed → published，可撤回，提交者不能审自己的题，程序校验把关，审计日志 | 完成（`docs/ADR-008_内容审核最小流.md`）；只能审、不能改；在浏览器里用真实后端走过二审、上线、下线 |
| 拍题 OCR、媒体上传、主观题评分、家长周报 | 不在本切片内；接口只进了契约，服务端返回 501，客户端的拍题页只是说明 |
| `docs/` 下的高考真题文件（约 8.4 GB） | 没有导入，原因见 `docs/ADR-007_切片技术锁定.md` 末尾 |

技术取舍、与文档的偏差、没有验证过的东西，都记在 `docs/ADR-007_切片技术锁定.md`。

## 运行

需要 [uv](https://docs.astral.sh/uv/)；Python 3.12 会由 uv 自动准备。

```
uv sync
uv run pytest -q
uv run python tools/run_dev_api.py
```

第三条命令在 `http://127.0.0.1:8000` 启动 API。这个入口会显式开启本地身份 Mock 和样题种子，并且只监听回环地址；演示数据存在 `var/tutor_dev.sqlite3`，删掉它就回到初始状态。想在几分钟内看到复测到期，可以加 `--review-minutes 1,2,3`。

### 审核后台（Vue 3）

Node 22。先启动上面的 API，再：

```
cd apps/admin_web
npm install
npm run dev          # http://127.0.0.1:5174，登录页点"以审核员身份进入"
npm test             # 另有 npm run typecheck、npm run check:api
```

演示：用审核员身份进入，"待审"页签里有 3 道样题，打开一道，二审通过、上线；学生端的练习列表里随即有了这道题。
用法与限制见 `apps/admin_web/README.md`。

### 学生端（Flutter）

Flutter 3.47.9 已装在 `C:\src\flutter`（没有加进系统 PATH，下面用绝对路径）。先启动上面的 API，再：

```powershell
cd apps\flutter_student
C:\src\flutter\bin\flutter.bat run -d chrome --web-port 8080     # 在 Chrome 里运行
C:\src\flutter\bin\flutter.bat test                               # widget / 单元测试
C:\src\flutter\bin\dart.bat analyze                               # 静态检查（不要用 flutter analyze，见 ADR-007 决策 24）
```

后端地址默认是 `http://127.0.0.1:8000`，用 `--dart-define=TUTOR_API_BASE=...` 覆盖。本地身份 Mock 只接受回环地址的请求，所以目前只能和同一台电脑上的后端联调；跨域只对 `localhost` 与 `127.0.0.1` 的页面放行。

改了契约或后端响应之后，按这个顺序同步客户端：

```powershell
uv run python tools/gen_dart_contracts.py        # 重新生成 packages/contracts/dart
uv run python tools/export_dart_fixtures.py      # 重新导出真实响应样例（Dart 与 Flutter 的测试都用）
cd packages\contracts\dart; C:\src\flutter\bin\dart.bat test
```

用 PowerShell 走一遍主流程：

```powershell
$base = 'http://127.0.0.1:8000/api/v1'
$json = 'application/json'
function Key { @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() } }

# 1. 领一个本地学生身份，完成引导（四川、高三、三科）
$id = (Invoke-RestMethod -Method Post "$base/dev/local-identities").data
$auth = @{ Authorization = "Bearer $($id.access_token)" }
Invoke-RestMethod -Method Put "$base/profile" -Headers $auth -ContentType $json `
  -Body '{"region_code":"CN-51","grade":"G12","subjects":["math","physics","chemistry"]}' | Out-Null

# 2. 今日任务 → 取第一道题
$task = (Invoke-RestMethod "$base/tasks/today" -Headers $auth).data.items[0]
(Invoke-RestMethod "$base/questions/$($task.question_id)" -Headers $auth).data.content

# 3. 开会话、建作答、要一层提示、提交
$session = (Invoke-RestMethod -Method Post "$base/sessions" -Headers ($auth + (Key)) -ContentType $json `
  -Body (@{ question_id = $task.question_id; origin = 'task' } | ConvertTo-Json)).data
$attempt = (Invoke-RestMethod -Method Post "$base/attempts" -Headers ($auth + (Key)) -ContentType $json `
  -Body (@{ session_id = $session.id } | ConvertTo-Json)).data
(Invoke-RestMethod -Method Post "$base/tutor/sessions/$($session.id)/next" -Headers ($auth + (Key)) `
  -ContentType $json -Body '{"action":"request_hint"}').data.events[0].payload.text
(Invoke-RestMethod -Method Post "$base/attempts/$($attempt.id)/submit" -Headers ($auth + (Key)) `
  -ContentType $json -Body '{"answer":{"selected_options":["B"]}}').data.evaluation
```

## 几条贯穿全局的规则

这些规则都有测试守着，`tools/mutation_check.py` 会把它们逐条改坏来确认测试确实会变红。

- **契约先行。** 每个测试响应都按 `contracts/openapi.yaml` 校验；教学事件写库前先过 `tutor_event.schema.json`。
- **不确定就弃判。** 格式认不出、单位认不出、确认不了等价的作答标成 `uncertain`，不算对也不算错，不进正确率分母，也不据此安排复测。
- **独立作答阶段不泄题。** 提示每次只给下一层；提交前看解析必须显式确认，并记入会话；复测在提交前不给任何辅助。
- **权限只来自 token。** 别人的资源一律 404，与"不存在"的响应完全相同。
- **模型只经网关调用。** 外部供应商要同时满足总开关、启用、合规核验、定价核验、环境变量齐全才会被用到；示例配置下只有 Mock。模型输出不合 Schema、带标记或泄题时不下发，改发 `fallback` 事件。
- **样题就是样题。** 来源标为"自编工程样题 · 未经学科审校"，地区标签只用于测试筛选。

## 目录

```
contracts/                 OpenAPI 与教学事件 Schema（唯一权威）
packages/visual_templates/ 图解模板白名单与参数边界
services/ai_gateway/       模型网关
services/api/              FastAPI 服务；seed/ 下是样题与知识点
migrations/                MySQL 迁移 SQL
config/                    模型路由示例（外部调用全部禁用）
evaluation/                评测集登记模板（空）
apps/flutter_student/      Flutter 学生端
apps/admin_web/            内容审核后台（Vue 3 + Vite + TypeScript）
packages/contracts/dart/   由契约生成的 Dart 包（模型、客户端、事件 payload、图解模板表）
infra/compose.yaml         开发用 MySQL / Redis / 对象存储（未实际启动过）
tools/                     启动脚本、迁移校验、变异检查、Dart 契约生成与样例导出
tests/                     契约、网关、单元、API、迁移、样题内容
docs/                      需求、决策、ADR、实施计划
```

给开发 Agent 的约定见 `AGENTS.md`。

## 下一步

1. **真机验证**：在 iPad 和安卓平板上跑起来，实测手写延迟、手掌误触、10 分钟连续书写后的草稿恢复（docs/03 P03 验收）。这需要先装 Android cmdline-tools 并接上设备。
2. 决定 `docs/` 下高考真题的使用范围和识别方式（Q-05、Q-04A），再做导入与人工审校流程。
3. 接入 MySQL、真实登录与真实模型之前，先替换本地身份 Mock 和 SQLite 里的幂等记录。
4. 拍题 OCR、主观题评分、家长周报。
5. 审核后台里的编辑：修改题干或答案并产生新版本（docs/07），再接上导入流程。
