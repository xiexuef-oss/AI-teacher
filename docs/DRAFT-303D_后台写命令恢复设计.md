# DRAFT-303D：审核后台写命令恢复设计

状态：实施中。审核双CAS/当前读及单题导入恢复已整合，编辑/单题审核与批量恢复在隔离实施，媒体/文档恢复仍待实施。以下初始调查范围保留，最新证据见文末。本文依据 `apps/admin_web/src` 静态读取及 `contracts/openapi.yaml` 契约检查编写；未做动态验证。不得据此推定生产身份或版权政策。实际模型 ID 未知，与本设计无关。

## 目标与基本约束

审核后台的服务端写入都采用同一恢复原则：先在本机持久化一个不可变命令，再发送；超时、断线、关闭页面或响应丢失时，只能重放同一命令及同一幂等键。历史命令绑定 `owner + method/path/资源标识 + key + 精确body`，不绑定一个永久 token generation。token 不落盘；用户重新登录同一 owner 后，可显式恢复/重试历史命令。每次显式恢复捕获当时的固定 token 与当前 auth epoch，网络发送前及每个 await 返回后验证 owner、token 身份/epoch、命令epoch、资源ID、页面/组件代次；旧响应不能覆盖新账号、新页面或新资源状态。一次恢复流程中不得在 await 后悄悄改用新的 session token 继续原链路。

区分三类事实：

1. **命令已落盘**：请求可能尚未发送，也可能服务端已执行但响应未到；不得据此显示写入成功。
2. **服务端结果已知**：收到并验证了该命令对应的成功响应，原始结果与命令一起持久化。这个本机状态可命名 `result_known`，它只是客户端持有的服务端 ACK 副本，不是服务端 receipt。
3. **当前资源状态**：随后 GET 得到的当前资源视图。GET 可用于刷新/对账，不能单独证明某个旧写命令成功或失败；资源可能后来又被其他人修改。

浏览器存储写失败时必须在发网络请求之前阻止写入，并给出明确错误；不能退化成“先发再说”。敏感数据只存必要的写命令与短期草稿，设置可解释的期限。损坏或无法解析的记录必须原样保留并隔离，不能删除、覆盖或按过期数据清理，因为其中可能是唯一的未知命令证据；提示用户需要人工恢复/对账，不能静默生成新 key 重发。多 tab 之间需要原子占有/冲突提示；若无法可靠协调，要求用户回到持有原命令的 tab，不能以新 key 猜测重试。

## 当前写入口与证据

| 类别 | 实际服务端写入口 / 当前调用点 | 当前恢复事实与缺口 |
|---|---|---|
| 单题 JSON 导入 | `ImportView.vue:65–91` → `api/admin.ts:17–18` → `POST /admin/question-imports` | body 指纹及 key 仅组件内存。刷新/关闭 tab 后丢失；无法确定请求是否已执行。 |
| 题目版本编辑 | `QuestionEditor.vue:119–133` → `api/admin.ts` 的 `createQuestionVersion` → `POST /admin/questions/{id}/versions` | 编辑 body 与 key 未落盘。草稿刷新丢失。 |
| 单题审核 | `DecisionPanel.vue:63–99` → `api/admin.ts:39–50` → `POST /admin/questions/{id}/review` | 审核 body/key pending 在组件内存；刷新丢失。 |
| 批量审核 | `BatchReviewView.vue:27–47` → `api/admin.ts:68–69` → `POST /admin/question-reviews/batch` | 完整 body/key/expires 在 `sessionStorage` (`:15–19, :34–45`)；结果也在 sessionStorage。可跨 reload，不保证关闭并重新打开 tab 保留。提交响应检查 owner (`:32–40`)；`refresh(row)` (`:21`) 没有 owner/代次 guard。 |
| 媒体创建/内容上传/确认 | `MediaAttachments.vue:21–49` → `api/media.ts:4–6` → `/media/uploads`、`/media/{id}/content`、`/media/{id}/confirm` | sessionStorage 保存 fingerprint、media id 和三把 key (`:14–19, :32–40`)，不存 base64。相同文件需用户重选，重新读取得相同字节/hash 才能沿用命令；关闭再开 tab 不保证恢复。请求链固定 token/owner 且多阶段检查 owner (`:26–45`)，但服务端写已发出不能由前端 guard 撤回。 |
| 媒体删除 | `api/media.ts:9` 暴露 `POST /media/{id}/delete` | 在当前 `src` 调用点搜索未发现实际 UI 调用；不得把附件“移除本题引用”（`MediaAttachments.vue:94`，仅本地 model 变更）说成服务端删除。若后续接线须纳入命令恢复。 |
| 题目媒体审校声明 | `MediaAttachments.vue:68–80` → `api/media.ts:11` → `POST .../review-confirmations` | sessionStorage 保存按 owner/question/version/media/sha 分区的 key/expiry (`:70–74`)，body 未直接保存但可由绑定值重建 (`:77`)；返回有 owner/资源字段 guard (`:78`)。 |
| 文档导入任务建立 | `DocumentImportView.vue:71–80` → `api/document-import.ts:8` → `POST /admin/import-jobs` | localStorage `:requests` 保存精确 body/key (`DocumentImportView.vue:26–45`)。成功后先 GET job 再清 pending (`:77–79`)，GET 结果不应成为 ACK 的替代定义。无 owner/页面代次 guard。 |
| 文档文件上传 | `DocumentImportView.vue:85–104` → `document-import.ts:9` → `POST .../{job_id}/files` | localStorage 只保存 revision metadata 与 key (`:96–101`)，完整 body 还含 filename/base64 (`:98`)。文件内容不落盘；恢复必须用户重新选择同一文件字节，核对 name/size/lastModified/hash 后重建原 body。现代码只用 name/size/lastModified 作为 action 标识，需补内容摘要。 |
| 文档 process/cancel | `DocumentImportView.vue:106–112` → `document-import.ts:10–11` | revision body/key 落 localStorage；无 owner/epoch guard。 |
| 候选保存 | `DocumentImportView.vue:215–226` → `document-import.ts:12` | `DocImportCandidatesEdit` 完整 body/key 落 localStorage；未固定 owner/epoch。候选编辑草稿另在 `:248–250` 按 job 存 localStorage。 |
| 候选批量导入 | `DocumentImportView.vue:228–239` → `document-import.ts:13` | submit body/key 落 localStorage，成功 batch 结果另存 `:batch:{job}`；`failedOnly` 依当前结果重构新命令 (`:231–235`)，应作为新命令单独持久化，不能改写旧命令。 |

接口契约已声明这些操作均带 Idempotency-Key；契约说明同键同请求重放首次响应、同键异 body 返回冲突（`contracts/openapi.yaml:12–13, 2628+`）。具体操作见该文件的 `/admin/import-jobs`、媒体、`/admin/question-imports`、versions、review、batch 路径。静态检查尚未证明服务端对每个写操作都以事务方式持久化幂等记录、记录 owner/请求摘要/结果、与业务状态原子提交；也未发现独立的查询命令 receipt API。必须先读后端实现及测试确认这些事实，不能假设契约的重放表述等于已实现的持久 ACK。

## 本机命令记录格式与恢复

建议命令记录至少含：schema_version、owner_user_id、命令epoch、method、规范化 path、资源 ID、idempotency_key、精确 JSON body、文件摘要元数据、创建时间/过期时间、状态 (`prepared` / `sent_unknown` / `result_known` / `reconciliation_required`)、成功响应副本或错误类别。token 与 auth epoch 只存在本次恢复的内存上下文，绝不落盘，也不作为历史命令的永久绑定。每次恢复由用户当前登录状态捕获固定 token+auth epoch；发送前及每个 await/链路下一次发送前检查 token/epoch 仍有效且 owner 匹配。账号切换不得把 A 的 pending 命令拿给 B 发；重新登录 A 后可显式继续 A 的命令。

- **原 A 与续改 B**：A 一经发送或进入不确定结果状态即冻结，精确 body/key 永不改写。用户继续编辑得到 B，B 使用新 key，作为独立命令排队；明确展示 A 的待确认状态及 B 的差异。A 已成功 ACK 后，B 仍基于预期版本/CAS检查，不自动覆盖服务端后续版本。
- **result_known**：`result_known` 是可纯本机保存的 ACK 副本，不要求额外 HTTP 查询，也不需要原文件字节。只有收到符合原命令身份和资源的成功响应才记录。写响应应先原子落盘 result_known，再更新界面；若结果落盘失败，维持 sent_unknown 并告知“服务器可能已处理，本机未能保存确认”，原 key/body 仍须可恢复，不能显示确定成功。
- **跨 tab**：优先用 IndexedDB 事务做 read-modify-write 和命令状态迁移；或以 Web Locks 包住完整的读取、校验、写回临界区。禁止仅靠 localStorage 读写或 BroadcastChannel 广播充当原子锁。准备命令、标记发送、保存 ACK 均需检查记录版本/epoch，防止旧 snapshot 覆盖另一 tab 新增的 B 命令或更新后的状态。sessionStorage 的历史恢复数据可跨同一 tab reload，但 tab 关闭后不保证存在；不得承诺重开恢复。
- **重启**：localStorage 记录通常跨浏览器关闭/重启保留，但用户清理、隐私模式、配额、浏览器策略会造成丢失。存储不可用/配额异常必须 fail closed；已送出的未知命令若记录确实丢失，界面只能进入人工/服务端对账状态，不能新 key 重做。
- **损坏**：校验 schema、hash、key 与 body 一致性；损坏记录不可自动重建 key、清理或覆盖。必须保留原始字节/条目并隔离到只读区，提示人工处理；对仅本机编辑草稿可允许用户另存，不得混同服务端命令。无法解析/不明版本的记录不得套用 TTL 自动删除，因为可能保存了服务端结果未知的命令证据。
- **退出与清理**：现有 `session.ts:42–44` 清除当前用户的文档恢复、batch sessionStorage、媒体 sessionStorage。新方案需明确 logout 是否清待发送命令：未发送本机草稿可按策略清理；sent_unknown 不能静默删除，须先提示仍有不确定写入并保留到期限/对账完成。切换账号只清理/隔离原 owner 区域，不把记录迁移给新 owner。按短期限清理并避免把 token、文件原文/题目原卷写入存储。

## 文件上传的字节恢复

文档文件和媒体图像一律不把 base64 文件内容持久化到恢复记录。上传命令记录文件名、大小、MIME、lastModified、SHA-256、服务端资源/job ID、幂等 key 及非文件字段。重试必须让用户重选文件，并在任何网络发送前重新计算摘要；只有字节摘要及请求元数据匹配时，才可用原 key 重建原 body。不同字节必须视作新命令，旧命令保留不确定状态并走对账。单纯文件名相同不代表同一请求。

媒体当前客户端有 SHA-256 指纹及分阶段 key；文档上传的 action 目前只用 name/size/lastModified，需扩为内容摘要。文件被选中到读取完毕前组件卸载/账号切换也要用 owner/epoch 检查丢弃读取结果。

## 服务端 CAS 与 receipt 先决调查

改 API 前逐项核实服务端实现、数据库事务和测试：

1. 所有 write endpoint 的 Idempotency-Key 记录是否持久化，是否与业务变更同事务提交；是否记录 actor/owner、method/path、请求摘要、状态和可重放的完整响应；并发同 key 是否只有一个执行者；记录保留期是否覆盖客户端恢复期限。
2. 文档任务有 `expected_revision`，题目版本/审核有版本字段；核实这些字段是否在每个写路径做原子 CAS，冲突是否返回明确 409 且不会产生部分副作用。媒体 PUT 分段流程需核实上传/确认/delete 的状态转移与幂等语义。
3. batch 是否每题/整批原子性与重复重放符合契约；partial failure 的响应是否完整且可重放。
4. 若幂等记录不足，优先补服务端持久 receipt 查询/重放能力或完善已有幂等中间件；receipt 必须授权校验且按 actor/key/request hash 定位，避免仅凭 key 泄露他人结果。若无法确认命令结果，返回明确 unknown/expired，绝不把 GET 当前资源冒充旧命令 ACK。
5. 只有证据证明现有契约/实现不能满足上述要求后，才提出契约变更；按仓库契约先行流程修改 OpenAPI、测试、实现及生成类型。此草案不授权改契约，也不决定身份服务设计。

## 分阶段实施与独立文件包

按文件所有权拆分，避免并发修改同一文件；每包先写失败测试，再实现。以下均为建议，尚未实施。

1. **共享命令存储/身份代次**：新建独立 `api/write-command-store.ts` 与纯逻辑测试；定义 schema、存储适配、跨 tab 协调、损坏/配额/期限/logout 规则。先验证存储故障时零网络请求。
2. **单题导入**：独立包 `views/ImportView.vue` + 对应测试；保存完整 body/key、owner、epoch；重载恢复、原 A/续改 B、late response 丢弃。
3. **版本编辑与审核**：独立包 `components/QuestionEditor.vue`、`components/DecisionPanel.vue`；各自明确资源/version CAS，测试编辑内容与决策变化时创建 B，不改写 A。
4. **批量审核**：独立包 `views/BatchReviewView.vue`；迁移现有 sessionStorage 兼容读取，完整 body/key 迁至命令仓库；跨 reload、关闭 tab 不保证、同 key 重放、result_known、refresh late guard 测试。
5. **媒体**：独立包 `components/MediaAttachments.vue`；保留旧 sessionStorage 恢复兼容一个明确版本/期限，校验重选同字节摘要；分阶段 create/PUT/confirm 分别记命令；审校声明绑定版本/sha；删除入口仅在真实 UI 存在时纳入。测试不得把“移除引用”当作服务端删除。
6. **文档导入**：独立包 `views/DocumentImportView.vue` + `import-recovery.ts`；兼容 `document-import:*` localStorage 与旧 pending；完整 body/key恢复（文件例外仅摘要+重选）；保存、process/cancel、submit、失败项重试各自命令化，job/候选编辑草稿和服务端 ACK 分开；owner/页面代次与轮询刷新 guard。
7. **端到端接线**：单独整合变更，由主线程协调。每阶段跑对应单测/类型检查；最终依现有项目要求跑 admin_web 测试、typecheck、check:api，并完成真实浏览器恢复验收。当前主线程另有真实浏览器验收在进行，本清单不假称完成。

### 每个包的 TDD 与浏览器验收矩阵

- 先失败后实现：存储成功后才发送；存储拒绝时零请求；超时后同 key+同 body 重放；body 改动产生 B/new key；A 的迟到响应不覆盖 B；账号切换、token 代次变化、资源变化、组件卸载/page epoch 变化时不污染当前 UI。
- 刷新：pending 命令及 key/body 恢复；result_known 显示为“该命令已确认”，并与之后 GET 的当前资源分开呈现。
- tab 关闭再开：只验证 localStorage 命令能恢复；明确 sessionStorage 不保证重开恢复。两 tab 同命令时只允许一个发送者。
- 浏览器完全关闭重启：验证 localStorage 可用情况下恢复；清理站点数据/模拟 quota 失败时验证 fail-closed 与不误报成功。
- 文件上传：断网/响应丢失后重选同字节文件复用原命令；相同名称不同内容不得复用；不重选不能自动上传，不持久化 base64。
- logout/account switch：A 的 late response 不更新 B 界面；sent_unknown 命令按政策提示保留或对账，不静默重发/删除。
- GET 对账：服务端当前版本变化不得被显示成旧命令成功；只有对应 receipt/原 idempotent replay 才能确认为该命令 ACK。

## 未完成调查与限制

本次为源码和 OpenAPI 静态调查，未执行动态请求、服务端故障注入、浏览器刷新/重启验收或测试。服务端幂等记录事务性、receipt 可查询性、各 endpoint 实际 CAS、跨 tab 行为均未确认；必须查看后端实现和测试后再定方案。是否需要新增 API 不预设：先按实际服务端幂等和 CAS 风险核实，只有发现现有能力不足才提案。项目当前 Q-03/Q-05 等决策边界继续有效；本文不做生产身份、版权、模型供应商或模型 ID 选择。

## 实施补充证据（2026-11-16）

此节为静态草案之后的实际证据，不回写前述调查范围。`var/admin-review-generation-probe.log` 已以全新隔离SQLite/Mock API证明：旧未执行publish(v1)跨reject/重新approve(v1)仍200并追加审核日志；旧approve(v1)跨reject回draft也200。历史成功同key控制组仅重放原响应，audit不增加且当前仍draft。真实MySQL并发旧publish覆盖draft v2仍在探针验证，不能据静态风险称已复现。

前端原始实现三条行为红测见`var/admin-import-recovery-red-r3.log`：刷新丢导入JSON/命令、旧账号401清新会话、落盘失败仍发送。独立副本`D:/tutor-admin-auth-stage-20261116`已准备身份binding基础与单题页面身份检查，16专项和typecheck通过；共享store另在隔离目录实施，均未整合当前工作区。审核恢复前先修复代际与并发后端风险，公开契约改动仍按契约先行流程。

## 当前工作区与阶段证据

012追加单调review_revision，审核/编辑同时检查内容版本和审核修订，稳定Question锁与关联当前读；旧成功回执先重放，旧响应缺修订号为unknown。真实MySQL已分别复现并修复旧publish让未审v2上线、媒体声明旧RR快照问题。实际后端2357通过/109未配置skip，另实际infra110零skip和驱动1项；Dart221、Flutter608/analyze、Ruff与契约/样例生成通过。

共享owner命令store、定向auth record/legacy保留及单题导入已整合。实际后台255/255、strict/checkapi通过；真实Import R4 16/16，原键/原body/原服务端ID恢复、续改B、跨tab分支和显式采用全部验证。223相同多行事件只一代，B分支去重，最新未落盘serial不被旧save清除。registered admin_write_recovery是第16条Flow，工具103通过；main已看截图/审10份safe JSON无凭据字段。R1–R3保留，范围与日志见var/admin-recovery-live-jobs.json。

Question编辑/单审与Batch恢复仍在隔离开发：前者初11绿后审查发现未落盘serial与409后unknown lane缺口，先红后修；后者旧sessionStorage缺revision保持不可精确重放、不得HTTP或补1，原raw/key保留并明确另起。原稿保留不代表已提供legacy旧身份备份恢复UI。已有217变异在731文件独立副本运行中，新Admin变异代码子任务受工具限制仍未执行；不把它们合称全量通过。

## 后续整合更新

编辑/单题审核恢复已整合，固定双CAS、serial、unknown显式停止重试/新source分开采用、已known零HTTP确认、终态旧恢复入口通过实际274全后台/strict与真实R3 30项；另两条head预览红修后真实双tab证明比较依据与保存快照一致。相关Flow为第17条，日志/限定证据见var/admin-question-integration.json。

批量审核的事务说明以真实后端为准：每项savepoint允许普通校验错误逐项失败，但成功项和整批幂等回执在一个外层事务提交，致命/DB错误整批回滚；不要与文档导入逐题commit混同。Batch候选仍在隔离修legacyACK迁移边界。Media五动作均为JSON对象body（confirm为sha256、delete为{}），本包不扩展无body协议，也不新增删除UI；其journal与UI已独立TDD，文档导入恢复随后。
