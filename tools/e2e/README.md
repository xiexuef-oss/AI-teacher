# tools/e2e：浏览器联调

用真实的后端、Flutter Web 发布版和审核后台，让无头 Chromium 像用户一样走完整的流程。
Widget 测试和 API 测试都用假数据或测试客户端，抓不到"页面和真实服务端对不上"的问题；这一层抓得到
（前几个功能的联调里发现过：从用户输入拼出的非法幂等键、旧页面用另一个身份的 token 重新请求、
成功提示被并进了输入框的读屏标签……）。设计取舍见 `docs/ADR-014_联调脚本进仓库.md`。

## 运行

第一次：

```
uv sync --group e2e                                  # 装 playwright（可选依赖组，默认的 uv sync 不装）
uv run --group e2e playwright install chromium       # 装浏览器；机器上已有对应版本的 Chromium 就不用
cd apps/admin_web && npm install                     # 审核后台的依赖（流程要用到审核后台时）
```

之后：

```
uv run --group e2e python tools/e2e/run.py                       # 全部流程
uv run --group e2e python tools/e2e/run.py --list                # 列出流程
uv run --group e2e python tools/e2e/run.py --only parent_weekly  # 只跑某几条（可以写多个）
uv run --group e2e python tools/e2e/run.py --headed              # 显示浏览器窗口，排查用
uv run --group e2e python tools/e2e/run.py --no-build            # 不检查、不重新构建 Web 版
```

全部流程现在二十三条，耗时随流程和构建变化。退出码：0 全部通过，1 有检查没通过，
2 环境问题（缺依赖、端口被占、构建失败）。

后端默认用 8000，可用 `TUTOR_E2E_API_PORT` 指定空闲端口。PowerShell 中可先运行
`$env:TUTOR_E2E_API_PORT = '18080'`，再运行联调命令。学生端和审核后台会使用同一个后端地址，
独立 Web 构建及日志分别写入 `apps/flutter_student/build/web-e2e-18080` 和 `var/e2e-18080`。
学生端静态服务仍用 8081，审核后台仍用 5174，运行前相应端口需空闲。

**Web 版过期会自动重新构建**：`apps/flutter_student/build/web` 比 `lib/`、`assets/`、`web/`、
`pubspec.*`、契约包 `lib/` 里任何文件旧，就先 `flutter build web --release`。过期的构建会让联调测到旧代码、
给出"通过"的假象，所以默认不跳过；`--no-build` 是你明确知道它没过期时才用。找不到 flutter 时用
`--flutter C:/src/flutter/bin/flutter.bat`，或设置环境变量 `FLUTTER_BIN`。

## 它做了什么

- 每条流程用**全新的 SQLite 数据库**和一个新起的后端（`var/e2e/<流程名>/`），互不影响，也不碰本机的演示库
  `var/tutor_dev.sqlite3`。
- 学生端和家长用不同的浏览器上下文（本机存储互相隔离）。
- 输出在 `var/e2e/`（已被 .gitignore 忽略）：每条流程的后端日志 `api.log`、数据库、`screenshots/`；
  流程中途出错时会给所有打开的页面各截一张图作为现场。

| 流程 | 覆盖 |
|---|---|
| `student_diagnostic` | 高一资料→创建真实成功丢响应→重载不自动POST→原键/原体恢复→三题逐题经UI提交与重载，验证固定会话、首份计数及工程样题说明 |
| `student_experiment` | 引导 → 练习页 → 实验题：安全提示、数据表、填格子、本机草稿落地与云端同步、重新打开后恢复、提交（不评分）、对照参考数据、自查、学情 |
| `student_proof` | 引导 → 练习页筛"证明题" → 证明题：已知（编号）与求证、一步一步写（每步带依据）、添加与上移与删除、本机草稿落地与云端同步、重新打开后恢复、提交（不评分）、你的证明与参考证明并排对照、自查、学情 |
| `student_draft_recovery` | 自编单选样题：页面正常同步后用真实 API 模拟另一端更新，页面再编辑产生真实409；双方留档、刷新恢复冲突、API离线重载与联网后不自动上传、学生明确采用云端、通过本机副本菜单恢复原稿并保留恢复前内容 |
| `student_draft_copies` | 真实409后明确创建服务端副本，原稿保持、同会话固定版本、刷新恢复确切作答ID，练习页云端草稿列表选择并独立编辑两份；不自动提交 |
| `student_creation_recovery` | 会话/作答成功丢响应后刷新重放；真实二审发布新版后保留旧稿并明确另开空稿；显式旧路由重试被阻断后另开、刷新恢复新稿且不带旧解析。302构建实际75/75通过（var/draft302-browser-creation-r3.log）；后续产品改动需重新构建复验，工具测试不代替浏览器 |
| `student_write_recovery` | 303A提交实际成功丢响应/刷新原键恢复、在途A后编辑B并明确在原会话续稿、自查A→B→A实际服务端状态、另一端真实笔迹修订竞争409；303A固定构建已验收；后续产品改动须另行复验 |
| `student_resource_recovery` | 303B辅导丢响应后明确恢复、旧hint晚到不回退DONE、复测完成丢响应明确恢复、另一端首提交后本页B明确记录C；只此流程使用真实本地复测间隔1/2/3分钟，未改数据库或调时。303B固定构建全部12流程443/443通过；后续产品改动须另行复验 |
| `student_profile_recovery` | 303C资料真实保存丢响应后固定key/body明确重试、期间B独立保留、409双方、GET不能自动重基未提交编辑、完整API离线刷新与恢复后明确保存、切号迟到回执隔离；当前专项实际验收中，不读写产品存储造状态 |
| `subject_diagrams` | 自编流程题与坐标证明题：必要题设完整、独立作答无图示答案、明确完整解析后展示对应白名单图解，证明仍pending与自查 |
| `student_scan` | 原生浏览器文件选择、自编PNG临时上传、空候选/未知置信度与明确Mock说明、本机文字刷新恢复、确认后唯一匹配且不建草稿、学生主动开始后才进入练习；不验证真实OCR或真机相机 |
| `student_scan_recovery` | metadata、图片内容、202扫描创建及确认四阶段真实成功丢响应；刷新不自动重发、原图仅同字节重选恢复内容、固定key/body、确认A回执不覆盖续改B；不持久化图片原文 |
| `admin_experiment` | 审核后台：队列、审核页（安全提示、数据表、参考值、要点）、下线、改安全提示存成新版本、版本对比、改成高风险时程序校验拦住 |
| `admin_write_recovery` | 单题自编 JSON 导入真实 201 丢响应、A 在途续改 B、刷新不自动发送、原 key/body/题目 ID 恢复及 B 明确新意图；同 owner 双标签普通输入触发真实 WebLocks 草稿 CAS、双方持久及明确载入/采用并备份主稿，多行粘贴与等价冲突分支去重。仅在 `Context.out_dir` 保存不含认证材料的截图与只读草稿/命令证据；不模拟配额失败或冒称覆盖本机 ACK、账号迟到 401 |
| `admin_question_recovery` | 自编公开样题的题目编辑 201、单审 200 真实成功后丢响应，固定 key/body 与双 CAS 来源恢复，续改 B 保留；其他正常 UI 动作将当前题目推进至已上线 v3，原审核重放不增审核历史、不回退当前状态；真实 409 后明确停止本机重试、保留未知记录，再单独采用新来源发新意图。同 owner 双标签载入 B 时比较预览显示最新主稿 C，明确采用后预览为 B、C 备份持久且原标签仍为 C。等待公开草稿持久状态，不按输入事件数猜测完成；仅只读 journal 与 API 留证，不写产品存储 |
| `admin_batch_write_recovery` | 独立 UI 审核员逐题确认两份公开自编样题；另一作者真实更新 q2 后，批量 200 回执保留 q1 成功/q2 版本冲突。A 回执在途续改 q2 的 B 意见与确认先落本机，关闭标签重开不自动 POST，原 key/body 明确重放历史部分结果、q1 审计不增加、B 不被清空；q2 明确刷新当前双 CAS 后以新 key 仅重试失败题。审核每项保存点、成功项及整批回执外层单事务，不能称逐题 commit。安全截图/JSON 在 `Context.out_dir`，不保存认证材料；未覆盖真实双标签草稿 CAS、配额故障或离线本机 ACK |
| `admin_media_write_recovery` | 公开自编样题上传媒体后，真实确认成功再丢响应；刷新不自动重发，原 key/body 恢复原确认，纯本机 ACK 后明确选择当前草稿，先经父草稿持久化再关联，刷新保留引用并真实保存新题目版本。独立 Mock 审校员预览图片后，声明真实成功丢响应、重载与原 key/固定版本 body 重放、本机 ACK 不额外 POST。本流程沿用文档导入的受控媒体开关，安全请求 JSON 和截图写入 `Context.out_dir`，请求 JSON 不含图片 base64 或认证材料 |
| `admin_document_write_recovery` | 自编公开 JSON 经真实 create/upload/process/candidates/submit/cancel 六类写入成功后丢弃完整响应，刷新及明确选择原任务均不自动 POST；普通 UI 操作明确恢复原 key、完整 wire 与历史结果。创建 A 在途续改 B 先落本机，恢复不覆盖 B；提交恢复后正式题目仅增加一份。真实 WebLocks，安全请求摘要和截图写入 `Context.out_dir`；文档提交逐题 commit/checkpoint，不等同审核 batch 的每项 savepoint/外层单事务。未覆盖全部故障、真实磁盘故障或真实 OCR |
| `document_import` | 自编 JSON/PDF/DOCX 多文件上传、提取、人工校对确认、批量部分失败、修复后仅重试失败项、草稿对学生不可见、导入者自审拒绝、草稿编辑新版本、独立二审及明确发布后学生可见 |
| `parent_write_recovery` | 家长邀请真实成功丢响应原键恢复、码不落产品存储、迟到已被替代码不展示、历史撤销回执不影响新授权、兑换重启需重输匹配原码；仅自编Mock账号、无外部通知 |
| `parent_weekly` | 学生生成邀请码授权 → 家长输入邀请码、看周报与翻周 → 学生撤销 → 家长什么都看不到 → 再授权 → 来回切换身份 |

单独运行题目编辑与单审恢复：`uv run --group e2e python tools/e2e/run.py --only admin_question_recovery`。2026-11-16 同一业务代码的临时 R3 入口真实浏览器 30/30 通过，证据保留于 `var/e2e-admin-question-recovery-r3-20261116`；R2 因测试等待普通提交按钮重新可用而超时，改为等待真实成功后的 GET 后完整重跑，R1/R2 证据未覆盖。正式入仓仅格式化和移除未使用导入，业务 AST 与 R3 相同；注册单测与 Ruff 通过不替代浏览器验收。此流程只使用公开自编样题、隔离 Mock 身份，不覆盖配额故障、真实身份或全部后台写入口。

## 数据从哪来

媒体恢复单独运行：`uv run --group e2e python tools/e2e/run.py --only admin_media_write_recovery`。2026-11-16 原探针 R2 使用同一业务 AST 真实浏览器 **13/13** 通过，证据在 `var/e2e-admin-media-recovery-r2-20261116`。R1 仅因 harness 等待 `confirm unavailable`，实际合法状态是 `prepared` 而超时（此前 3 项通过）；R2 正则接受两类未知状态后完整通过，未据此修改产品。正式入仓移除临时 runner/路径设置，注册与格式检查不替代浏览器验收；本流程不声称覆盖跨标签页声明竞态、配额故障或全部媒体恢复阶段。

单独运行冲突副本验收：`uv run --group e2e python tools/e2e/run.py --only student_draft_recovery`。该流程只读 localStorage 留证，不直接写入产品存储；另一端更新走实际 API。凭据来自本机 Mock，仅用于隔离联调环境，不打印凭据。API离线通过阻断浏览器到本机 API 的请求实现，静态 Flutter 资源仍加载，不能称整机断网或真机持久性验收；不模拟磁盘满、不验证手写笔体验。刷新、API离线及恢复后的页面截图保存在此流程的 `screenshots/` 下。预期409不计为失败，其他错误响应及未捕获异常仍检查。

2026-11-16 实际验收：新流程25/25通过。使用已核对包含最终DRAFT修补的既有 Web 产物，显式 `--no-build`；此结果不覆盖同时开发中的新图示版本。为保留此前联调证据，调用入口时临时将 `run.OUT_ROOT` 指向 `var/e2e-draft301-20261116-r2`，未修改入口或产品代码；日志为 `var/draft301-browser-r2.log`。首轮脚本误用不随 imperative push 更新的地址导致回到首页，现场保留在 `var/e2e-draft301-20261116`；修正为明确题目路由后重跑通过。

题目的标题、数据表、参考值、要点数量、答案都从样题（`services/api/seed/`）和测试里的答案表
（`tests/support/flows.py`）取，脚本里不重抄一遍。样题改了，联调跟着变；改得让联调对不上
（少了一道题、某个答案不再判对、周报的最小样本数变了），`tests/unit/test_e2e_tooling.py` 会先红。
这个测试不需要浏览器，随 `uv run pytest -q` 一起跑。

## 写新流程

在 `tools/e2e/flows/` 里加一个模块，定义 `run(ctx)` 和 `FLOW = Flow(name=..., title=..., needs=..., run=run)`，
再登记到 `flows/__init__.py`。几条约定：

- 期望值从样题里取（`e2e.data`），别写死标题和数字；
- 造数据用后端接口（`e2e.api_client`），比在界面上点快、也稳；界面上只走要测的那一段；
- Flutter Web 的元素靠语义树找：`page.get_by_role("button", name=...)`，短名字加 `exact=True`；
  文字读 `all_text(page)`；输入框的值读不到（Web 上的语义输入框不回显没聚焦字段的值），
  要验证"恢复了什么"可正常点击聚焦后读取连接的原生编辑器值（Profile流程保留聚焦前后读取证据），并核对真实请求体与截图；不通过脚本改DOM值或把localStorage值冒充UI验证；
- 往 Flutter 的输入框里输入用 `type_into(page, 输入框, 文字)`，不要自己 `click()` 之后马上 `keyboard.type()`：
  点完马上输入会丢掉第一个字符（联调里出现过）；
- 检查用 `ctx.check(名字, 条件, 出错时的细节)`，不要用 assert——一项不过不该拦住后面的检查。

## 没有覆盖的

- 只有 Chromium（无头、软件渲染）：没有 Safari/WebKit，没有真机，没有 TalkBack/VoiceOver；
- 鼠标滚轮和触摸滚动（视口开得很高，一屏放得下整页）、字体放大和手机宽度（这些由 Widget 测试覆盖）；
- 解答题（`written`）的浏览器流程：它和实验题、证明题共用自查那一段，但没有单独的脚本；
- 审核后台里证明题的浏览器流程（看、改参考证明、版本对比）：只有后端接口测试和审核后台的组件测试，没有 `admin_proof` 脚本；
- 手写笔迹单独提交。

2026-11-16 `student_scan`真实浏览器9/9通过，证据`var/e2e-photo301-20261116-r3`及`var/photo301-browser-r3.log`；使用修补Web选图尺寸检查后新构建的Web产物。首轮Flutter未聚焦textarea原生值读取误判，次轮实际ImageDescriptor.width不支持Web，两轮失败现场保留；最终不改DOM、不造localStorage，只走文件选择及产品输入。未实际OCR，不代替原生相机/系统分享真机验收。

303B资源恢复专项：`uv run --group e2e python tools/e2e/run.py --only student_resource_recovery`。仅此流程通过本地开发入口的 `--review-minutes 1,2,3` 使用真实分钟间隔，先为两个隔离学生准备错题，再执行辅导场景，最后轮询真实到期；不修改数据库、服务端时间或生产默认值。其他11条流程仍不传此参数。该工具静态单测不代表新B构建已通过浏览器验收。


文档写恢复单独运行：`uv run --group e2e python tools/e2e/run.py --only admin_document_write_recovery`，沿用文档受控媒体开关。2026-11-16 原 R3 会话 **31823 terminal 0，22/22**，除将 Playwright expect 导入延迟到运行函数以保持无浏览器依赖的 registry 导入外，与正式 Flow 的 scenario 业务 AST 相同。R1 为 18 过/2 失败：harness 错把文档 `imported` 当 `succeeded`，且新窗口需重新填写来源授权；R2 为 20 过/1 超时：多工作区刷新没有承诺自动选最近任务，harness 未明确选原 B；R3 增加真实按钮选择原任务后通过，三轮产品源码未改。正式注册仅验证工具包装，不重复浏览器或构建；安全 JSON 已检查不含 token/base64/secret 字段。单位测试覆盖更多边界，不能据此宣称真实浏览器覆盖所有故障。


2026-11-16 旧 `document_import` 全功能流程兼容验证（QA301 尾项，未通过范围保留）：R1 原会话 13331 退出 1，0 过/1 超时；五份自编 JSON/PDF/DOCX 上传均成功，旧 harness 等待已废弃“文件已上传”提示。已改为五份文件 summary 可见且处理按钮 enabled，并为新写操作等待公开草稿已保存、必要时明确采用当前来源。R2 会话 7492 退出 1，3 过/1 超时，等待 GET 自动覆盖候选；改为真实比较并载入当前候选。R3 会话 10937 与最后 R4 会话 18550 均退出 1，12 过/1 失败，R4 保存候选前没有发出 HTTP，公开提示为“请先比较并明确采用独立分支”。此分支选择路径留待 QA301 诊断，不认定为后端或产品故障，不减少原断言、不继续循环重跑。

R4 已验证自编文件处理、跨文件续题原位置、独立答案不进题干、刷新同任务、安全 PNG 原文、人工确认门控、四候选来源双向同步、人工答案配对和可视化编辑同步。后续候选保存、部分失败修复、二审发布、媒体学生读取与删除等原有断言仍保留，但本轮尚未执行到，不能称全流程通过。原日志 `var/document-import-regression-r{1,2,3,4}.log`，R4 截图在 `var/e2e-document-import-regression-r4-20261116/document_import/screenshots/failure_0.png`；tooling 103/103、Ruff/格式检查通过。本轮未改 API/admin/contract/generated/fixtures，沿用固定学生 Web，未重建。
