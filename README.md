# 高中理科 AI 私教

面向高中数学、物理、化学的 AI 私教。首发地区四川、重庆；学生端计划用 Flutter（平板横屏优先）。需求与决策在 `docs/`，接口契约在 `contracts/`。

## 现在做到哪了

按 `docs/ADR-006_本地纵向切片.md` 的范围推进：**后端和 Flutter 学生端都已完成，能在本机端到端跑通；Android debug 已在荣耀 KRJ-W09 上安装运行，引导、API 联通、短草稿离线新增与重启恢复及同步、横竖屏与大字体已验证；长时间书写与手写笔体验验收仍未完成。**

| 部分 | 状态 |
|---|---|
| 接口契约（OpenAPI、教学事件 Schema、图解模板白名单） | 完成 |
| MySQL 迁移 SQL、模型路由示例配置 | 迁移执行器及引擎已在隔离MySQL 8.4验证；包含升级、并发锁、时区、持久回执与备份恢复，外部模型仍关闭 |
| 模型网关（路由、Mock、输出校验、重试熔断、预算、审计） | 原型可用；换讲和本地文档OCR已支持显式启用的持久恢复、逐尝试预占与幂等审计，见PROD-302/COST-302；显式SDK已补逐尝试持久重试/回退及确认失败后的跨进程续跑，见[COST-312](docs/COST-312_SDK确认失败后的跨进程续跑.md)；成功正文恢复、旧入口迁移、生产存储、真实计费和授权评测仍待完成，外部供应商默认禁用 |
| 后端 API：地区资料、题目、会话、作答、草稿、提交判定、分层提示与解析、图解、复测、今日任务、学情 | 本地SQLite原型可运行；受控dev/staging已验证部分MySQL/Redis业务链及本机S3只读启动校验，辅导next/文档导入任务/媒体仍有边界，prod拒绝启动，见[受控运行矩阵](docs/PROD-301_受控运行生命周期.md) |
| 18 道客观题 + 3 道解答题 + 3 道实验题 + 5 道证明题（数学 4、物理 1）自编工程样题，另有 3 道待审样题（`seed/drafts/`，学生看不到） | 工程验证可用；没有经过学科审校，不作为正式题库覆盖承诺 |
| Dart 契约包（由契约生成） | 完成 |
| 本人记录与当前媒体导出 | 本机练习、拍题、资料/辅导复测/授权恢复记录，以及服务端学习记录可分别导出JSON；练习命令、分支、现存回执及本人题面缓存已合并进恢复导出，Flutter766与实际浏览器50项通过，见[DATA-303I](docs/DATA-303I_独立题面缓存导出.md)。媒体ZIP保存本人当前可读媒体及状态清单，当前主要为拍题原图，不转换笔迹坐标，不含过期/审核用途或完整历史，见[ZIP范围与验收](docs/MEDIA-301D_本人媒体ZIP下载.md)。当前服务端伪名可关联的个人模型用量与预算估算已追加，专项通过、全量终态见[DATA-303H](docs/DATA-303H_个人模型用量导出.md)；完整个人备份/删除与最新真机仍待 |
| 三题摸底、本人历史与导出 | 本地工程原型已实现：固定版本、原会话、首份计数、本机先存命令与恢复、本人历史分页及计划/本机恢复记录分别导出；最新真实浏览器两流程40项、Flutter682项通过，见LEARN-301B/C/D。工程样题不足三道会明确提示；不推算掌握度或分数，尚未验证正式教学效果或最新真机 |
| Flutter 学生端：引导、首页、练习、作答（题目/草稿分栏、手写画布、本地草稿、冲突双方留档与恢复）、辅导时间线、八个图解模板、复测、学情、我的 | 本地原型可用；既有版本已在Chrome与KRJ-W09首轮验证，新草稿恢复浏览器25项通过，新增图示浏览器14项通过；最新功能未重新真机安装验收，iOS未构建 |
| 内容审核最小流（后端 + Vue 3 审核后台）：题目 draft → reviewed → published，可撤回，提交者不能审自己的题，程序校验把关，审计日志 | 完成（`docs/ADR-008_内容审核最小流.md`、`docs/ADR-009_题目编辑与新版本.md`、`docs/ADR-010_回看与对比旧版本.md`）；审核员可以修改题目、产生新版本，并回看、并排对比任意两个版本；在浏览器里用真实后端走过修改、对比、二审、上线、下线 |
| 解答题（主观题）：分小问作答、**不自动评分**、提交后对照要点自查，学情里只有计数 | 完成（`docs/ADR-011_解答题与对照自查.md`）；后端、Flutter 学生端、审核后台都支持；在浏览器里用真实后端走过作答、自查、学情、审核后台的修改与对比；没有做手写识别和任何自动评分 |
| 实验题：数据表（留空格子填数）+ 安全提示、**不自动评分**、提交后把自己填的数和参考数据并排对照再按要点自查，学情里只有计数 | 完成（`docs/ADR-013_实验题与数据表.md`）；后端、Flutter 学生端、审核后台都支持；在浏览器里用真实后端走过学生端的完整流程（填表、本机草稿恢复、提交、对照参考数据、自查、学情）；审核后台也走过（看、下线、改安全提示、版本对比、高风险拦截）；已支持经独立审校声明、发布后按当前题目版本授权的静态题面附件（本地媒体原型）；不收录高风险实验 |
| 证明题：有"已知 / 求证"，学生把证明写成一步一步（每步带依据）、**不自动评分**、提交后把自己的证明和参考证明并排对照再按阶段（前提、构造、推理、结论）分组的要点自查，学情里只有计数 | 完成（`docs/ADR-015_证明题与分步证明.md`）；后端、Flutter 学生端、审核后台都支持；在浏览器里用真实后端走过学生端的完整流程（写步骤、挪动、本机草稿恢复、提交、对照参考证明、自查、学情）；化学没有证明题；没有做手写识别和任何自动评分 |
| 家长周报（基础版）：学生生成一次性邀请码授权、可随时撤销；家长只看按周汇总的趋势 | 完成（`docs/ADR-012_家长周报与学生授权.md`）；后端、Flutter 学生端和家长页都支持；家长是本地身份 Mock 里的角色，**不是真实账号，没有监护人核验**（Q-03 没有冻结）；在浏览器里用真实后端走过授权、看周报、翻周、撤销 |
| 浏览器联调（真实后端 + Flutter Web + 审核后台，无头Chromium） | 二十条已注册流程；303C资料固定构建13流程480/480通过，家长与扫描合并构建15流程538项已分两次取得通过证据（旧文案断言修正后家长54/54专项复验，非单次全绿）；扫描恢复27/27、家长写恢复31/31、媒体确认与独立审校声明恢复13/13、文档六动作写恢复22/22已通过，每条隔离数据库，只在Windows上跑过，见[联调说明](tools/e2e/README.md) |
| 本地题面媒体上传、私有预览、独立审校及学生受控读取 | 已实现本地原型，默认关闭；仅静态PNG/JPEG/WebP，拒绝动画，临时TTL与发布引用门控仍生效；媒体删除/过期显示替代文本与重试，不缓存学生图片；MEDIA-301C/D已补内部枚举和本人当前学生媒体ZIP下载，S3全局快照、手写Blob上传及生产条件仍待；生产留存未冻结 |
| 学生拍题与确认 | 本地手工确认原型已实现，默认关闭；学生专用临时图片、文字本机恢复、明确确认后匹配唯一已发布工程样题，尚未实际OCR；真实识别/授权评测及原生相机验收仍待完成 |
| 主观题自动评分、高风险实验 | 仍未启用，保持主观题pending与高风险实验禁入；待负责人冻结相应流程 |
| `docs/` 下的高考真题文件（约 8.4 GB） | 没有导入，原因见 `docs/ADR-007_切片技术锁定.md` 末尾 |

最近已构建的Android profile测试包见[RELEASE-301C](docs/RELEASE-301C_恢复导出Android测试包.md)，已打入DATA-303F/G/H/I导出增量，358份源码、签名、包完整性、新字段标记与字体核对通过。最新学生端Flutter766、实际浏览器50项通过；构建前后ADB列表均为空，尚未安装或完成本包真机验收。

技术取舍、与文档的偏差、没有验证过的东西，都记在 `docs/ADR-007_切片技术锁定.md`。

全部剩余任务、依赖和最新执行证据见[持续执行工作计划](docs/plans/2026-11-15-project-backlog.md)。后台审核代际与并发修复已整合，012及双CAS、关联当前读已有后端和真实MySQL验证；单题导入恢复已整合，真实跨标签页浏览器及其余写入口仍在推进，不能将当前后台视作生产就绪。

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

试一下家长周报：先在 Chrome 里做几道题；"我的"页填好称呼，点"生成邀请码"（弹窗里的十位码只显示这一次）；再点"切换到家长身份（本机演示）"进入家长页，输入邀请码、点学生就是周报；切回学生身份，在"我的"页的"家长查看"里可以撤销授权，撤销后家长马上就看不到了。两个身份存在这台设备的同一份本机存储里，切回去还是原来那个。家长是本地身份 Mock，不是真实账号（`docs/ADR-012_家长周报与学生授权.md`）。

跑一遍浏览器联调（真实后端 + Web 版 + 审核后台，无头 Chromium，全部流程约 6~8 分钟）：先 `uv sync --group e2e` 装 playwright，之后 `uv run --group e2e python tools/e2e/run.py`；用法、固定端口和 Web 版过期会自动重新构建等细节见 `tools/e2e/README.md`。

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
$profile = (Invoke-RestMethod "$base/profile" -Headers $auth).data
$profileBody = @{ region_code = 'CN-51'; grade = 'G12'; subjects = @('math','physics','chemistry'); expected_revision = $profile.revision } | ConvertTo-Json
$profileKey = Key
Invoke-RestMethod -Method Put "$base/profile" -Headers ($auth + $profileKey) -ContentType $json `
  -Body $profileBody | Out-Null

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
- **不确定就弃判。** 格式认不出、单位认不出、确认不了等价的作答标成 `uncertain`，不算对也不算错，不进正确率分母，也不据此安排复测。解答题（`written`）、实验题（`experiment`）和证明题（`proof`）不自动评分，状态是 `pending`：学生提交后对照要点（实验题还有参考数据，证明题还有参考证明）自查，自查不是评分，不折算成分数，也不进任何正确率。
- **独立作答阶段不泄题。** 提示每次只给下一层；提交前看解析必须显式确认，并记入会话；复测在提交前不给任何辅助。
- **权限只来自 token。** 别人的资源一律 404，与"不存在"的响应完全相同。
- **家长只看汇总，且要学生明确授权。** 家长（现在只是本地身份 Mock）只能看到已授权学生的按周汇总——计数和比例，没有题目、作答、草稿，没有每次练习的时间，没有排名；授权由学生发起、可随时撤销、撤销立即生效；没绑定、已撤销、学生不存在，对家长都是同一个 404。
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

所有剩余开发、验证和负责人决策统一排在[持续执行计划](docs/plans/2026-11-15-project-backlog.md)，各项保留依赖及实际验收证据。
文档切题/批量导入、可视化答案编辑、批量独立审核已完成本地原型；MySQL/Redis正式回执及受控dev/staging运行已专项验证。
接下来整合全量门禁，继续辅导事务、严格预算预占、学科图示和部署准备。
真实登录、真实OCR、授权题库、地区教材及留存政策等待对应决策；KRJ-W09手写笔长时体验和iPad实测仍待设备条件，见[真机记录](docs/plans/2026-11-15-krj-device-validation.md)。

### 文档与批量导入（本地原型）

启动本地 API 与审核后台后，从“导入题目”进入“文档与批量导入”（`/#/document-import`）。
填写来源和使用依据，上传 PDF、DOCX、PNG/JPEG 或结构化 JSON；任务处理后回看原文，人工拆合、校对并确认候选题，批量保存为待审草稿。
同题成功后保留稳定草稿映射；部分失败可修正失败项后重试。草稿仍须独立二审，不会自动发布。

文字 PDF/DOCX 可本地提取；扫描 PDF 与图片默认只提供原图和人工录入，OCR 外部调用未启用。
Mock 只测试网关链路。DOC 需要显式配置本机转换器，未配置时请另存为 DOCX。
任务原文默认临时保留 120 分钟，具体限额、恢复、清理和隔离边界见 ADR-017；不要把本地原型当作生产文档沙箱。
全项目开发进度见 `docs/plans/2026-11-15-project-backlog.md`；导入阶段证据保留在 `docs/plans/2026-11-15-auto-execution.md`。
