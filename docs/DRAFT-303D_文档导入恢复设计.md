# DRAFT-303D 文档导入写命令恢复设计

状态：只读设计，2026-11-16。未实现新恢复逻辑，未改 API、契约、数据库或运行服务。真实 OCR 仍禁用；本设计不冻结 Q-04A、Q-07，不延长现有原型留存。

## 范围、依据与合并基线

依据实际 `routers/document_imports.py`、`idempotency.py`、`services/document_import_service.py`、`document_import_batch.py`、`document_import_worker.py`、`schemas.py`，以及 ADR-017、现有 `import-recovery.ts` 和生成 TypeScript 类型。此处不重复已确认的旧 upload 缺实际文件指纹、异步调用链缺 binding 盘点。

**未来实现必须以最终合并的 Media 版本为基线。** 本次只读核对 `D:/tutor-admin-media-stage-20261116/src/views/DocumentImportView.vue` 的接口；该候选仍可能变化，不宣称已验收或已经合并。禁止用本次读取的旧 actual `DocumentImportView.vue` 整文件覆盖 Media 成果。

Media 候选已经包含 `QuestionEditor local-only`、`persist-draft(form,body,{isCurrent})`、`draft-revision`，以及 `persistCandidateDraft`、`writeCandidateDraft`、`editorInputSerial`、`draftSources`、`documentSourceConflict`、`adoptDocumentSource`。回调检查 owner/session binding、真实 job/candidate、编辑器 lease、数组/对象身份、输入代际和留存界限；只有本机持久成功后才允许编辑器应用附件。Doc 恢复必须接续这一 Promise 与 guard 协议，不能让深 watch、GET show 或旧回执先覆盖候选，再补写草稿。Media 的具体内部实现由其负责人交付，不在本设计改动。

## 实际 wire、revision、receipt、TTL 顺序

所有列出的写路由先经过 reviewer 身份依赖和请求 schema，再进入 `run_idempotent`。该函数先算包含 method/path/经 Pydantic dump 的 body 指纹、查 owner 范围回执；存在同指纹成功回执时直接重放，不执行 service 的 owned_job、状态或 revision 检查。不同指纹同键返回 409。首次执行进入 reserve/action/finish；通常业务与回执由同次外层 commit 提交，**文档 submit 有明确的中间提交例外**。

| 动作 | 首次 wire 与业务顺序 | 恢复含义 |
|---|---|---|
| create `POST /admin/import-jobs` | `DocImportJobCreate` 含 title/defaults；检查来源，创建 uploading、revision=1、服务端 expires_at，再随通用回执 commit | 原成功回执可晚到且已过期；返回真实 jobId 不代表当前仍可用。没有 jobId 时不能用列表相似标题推定原请求成功 |
| upload `POST /{job}/files` | `DocImportUpload` = 原 expected_revision、filename、content_base64；owned_job/TTL → uploading 状态 → 解码、限额、实际内容 detect_kind → CAS advance → 文件/实际 SHA 与 audit → 回执 commit | 已有回执先于 TTL/CAS 重放；无回执才会重新过 TTL/CAS。文件名、全部内容及原 revision 都是原请求，不允许 GET 后改 revision 再用旧键 |
| process `POST /{job}/process` | `DocImportRevision`；owned_job/TTL、uploading、至少一文件 → CAS +1、queued → commit | 200 只表示已入队。工作器领取 processing 时、逐文件完成时及最终状态均可能推进 revision；旧 queued 回执不能回退已完成的当前状态 |
| cancel `POST /{job}/cancel` | `DocImportRevision`；owned_job/TTL、允许状态 → CAS +1、cancelled、清 lease、取消未完成文件 → commit | 不能撤销已导入题目，也不保证让在途请求从未执行。旧回执只确认原取消动作，不授权取消新任务或新 revision |
| candidates `POST /{job}/candidates` | `DocImportCandidatesEdit` 含原 revision 和完整有序 items；owned_job/TTL、可编辑状态、无未完成提交批次、候选/原文位置/确认及来源校验 → CAS +1 → 保存/删除/排序 → commit | 是完整候选集合替换语义。拆合、排序、null id、确认、payload、locations 均冻结在 A body；新编辑 B 不得替换其中任何部分 |
| submit `POST /{job}/submit` | `DocImportSubmit` 含原 revision 和完整有序、去重 candidate_ids（最多50）；owned_job/TTL 后查固定 digest 的 DocumentImportBatch；新批次先 CAS、记录 intent/submit_start 并 commit，再逐题持久；结尾完成 batch response 后通用回执 commit | 同 key/body 恢复未完成 batch 走 checkpoint，不拿当前 revision 重建原 intent。GET 中已有 question_id 或 imported_count 不等于原命令 ACK |

GET detail/list/original/preview 是当前观察。owned_job 对不存在、他人、已过期统一 404；原文件还要求原内容存在。GET 没有原动作 key，不能证明某个未知 intent 未执行或已成功。预览/原文件返回 base64 只能留在内存展示/下载，不进入 journal、draft、snapshot 或诊断 JSON。

工作器的条件 lease、心跳及逐文件提交属于后台处理，不是客户端上传回执。轮询可能读到更高 revision；不得把“处理尚未完成”转成重发 process 新键，也不得把旧 process/cancel/save 回执直接作为最新 job 投影。

## 两类 batch 的事务边界

文档导入 submit：新批次先记录 intent；逐候选在锁定批次后跳过已有 checkpoint。每一项用保存点处理可预期失败，候选 question_id 映射与新建待审草稿、item 结果、job revision 同次 commit。已经提交的项不会因后续进程退出而回滚。已导入候选返回 already_imported；失败项也进入本批次检查点。结束时再保存批次最终响应，与通用幂等回执完成提交。恢复原批次必须保留原 candidate_ids 顺序，不能把旧失败项的修改自动塞回原 batch；修正并保存候选后，由用户明确生成新键、新 revision 的提交，只选应重试的失败项。

审核 `question-reviews/batch` 不采用上述逐题 commit。它逐项保存点隔离普通校验失败，成功项与整批回执在同一外层事务提交；fatal/数据库异常回滚整个未提交批次。两者不能共用“逐题 commit”文案，也不能仅凭 HTTP 都为200就共享恢复状态推导。

文档批次中途取消/到期时，已经持久的草稿与映射仍在；尚未完成项会在服务端执行相应校验。客户端不得把部分结果称为整批未执行，不自动重新导入已成功候选。

## 本机权威、精确上传与 A/B

建议新增 Doc 专用 adapter/state，复用现有 owner `WriteCommandStore` 与真实 browser WebLocks，但不能用通用 owner `pending().at(-1)` 捞其他模块命令。先过滤 method/path/resource，再绑定本机 workspace、真实 jobId、候选组及有序来源；创建前只有真实本机 workspaceId，不伪造 jobId/fileId/candidateId。每个题组/任务独立 draft，切换任务不删除其他未决或历史。

非文件命令先持久完整生成 DTO JSON、原 key、method/path、owner、来源 revision、编辑代际和 workspace/job 关联，成功后才 HTTP。payload 持久仅限该任务有效临时留存窗口中的人工文本/结构化题目，不保存 auth、原文件、base64、File、Blob、文件路径或预览 data URL。资源、编辑器表单中的任何附件只用已审核的合法引用，不通过嵌套字段绕过文件禁存。

upload 的生成 DTO 确实含 `content_base64`，不能整份落盘再删。先读实际 bytes，在内存建立 canonical Base64 与首次完整 wire DTO；持久安全 metadata（原 filename、expected_revision、job/path、实际 size/SHA-256）与完整 canonical wire 指纹、key。使用现有 file-reference/sendFile 能力，不修改生成协议。首次指纹基于实际原请求，不以 filename/size/lastModified 代替 SHA。

**MIME 边界：** 现上传 wire 没有 MIME 字段，不擅自加字段。浏览器 File.type 仅作不可信输入提示/本机选择描述，不能证明文件类型。服务端 detect_kind 读取实际 bytes 并返回规范化 media_type/kind，结果可作安全 metadata。重选同 bytes 时必须保留原 filename 和 expected_revision 重建原 wire；若需改名，则明确另起新意图，不能改旧键内容。不同 bytes 即使同名同大小、同 MIME 或 lastModified 相同，也零 HTTP 拒绝原操作重试。恢复前检查实际 byte SHA、长度及完整 wire 指纹；原图/文件缺失但已经 result_known 时仅本机 ACK，不要求重选、GET 或网络。

多文件选取分别形成命令，顺序固定；一个上传结果未确认不能跳过并给下一文件借用原 key。前一文件 ACK 后可在同一选取意图、同一 owner/job/选择 lease 下准备下一文件；若期间另一端推进 revision/任务切换/新编辑，则停止后续 HTTP，展示冲突并要求明确选择，不把历史 A 回执自动当作新 B 的 current/source。

编辑在每次输入时先本机保存；题目、结构化表单（含无效但合法可保留的输入）、原文配对、排序、拆合和确认状态都属于同一候选快照。draft 保存记录首次编辑的 baseRevision、当前 editGeneration 与跨 tab 本机 CAS generation。后续 GET 只更新独立 current；不能把 job.revision 写回既有编辑来源。未知 legacy base 不填1，也不借当前 GET 隐式补齐；必须比较双方后明确采用来源。

跨 tab 同 snapshot 去重不加代，不重复建等价分支；实际 A→B→A 是独立变化，不能粗暴按历史内容去重。冲突分支保留原 baseRevision、本机来源和有序候选集合。载入仅查看，采用须校验 head generation、选中分支和页面 serial；选择本机前当前内存输入必须先成功落盘，失败时拒绝替换。草稿保存状态应公开区分正在保存、已保存、冲突已保存、仅内存未保存，真实浏览器等待该边界，不用 input 事件数量猜测。

A save/submit/上传在途时 B 可继续编辑并先本机存。A 回执先安全 recordResult，再 ACK；只确认 A，保留 B，不能清空 B 的确认、意见、配对或让 B 自动导航。页面 serial 还要保护“B 本机写失败、store 仍停在 A”的窗口；仅 store editGeneration 不够。逐候选历史导入资格须分别判断，不能因 B 改了 q2 就保留/复活已成功 q1 的旧勾选，从而阻挡或夹带到后续失败项新提交。

## 身份、页面、任务、来源与迟到响应

一次动作开始即捕获 `captureSessionBinding()`、固定 token、viewEpoch、workspace/job 身份、编辑 serial、candidate 真实 id/对象或本机临时候选 id、picker/file selection lease、原 command ticket。每次 await 后重验；每个后续 HTTP 发出前再次检查，不能在网络返回时临时读取当前 session.token。旧响应可写回其原 owner 的历史命令，不能改 B 的 current/UI、触发新 GET、退出新身份或继续下一文件/下一候选。

GET 另有 request generation；同 job 迟到较旧 revision 不回退 current，切任务、切账号、卸载、候选数组重建、拆合删除或 structured editor lease 失效后不应用旧结果。revision 相同也不能单靠对象相等确认本机来源；错误处理同样使用原 binding，迟到401不能清 B 登录。网络刷新和轮询不能自动调用 show 重置 B 表单或拿最新 current 给 A 改体重发。

result_known 提供纯本机 ACK；历史结果与当前 job/candidate 映射分别展示。共享 store 的读校验成功与 receipt 存在才可本机 ACK，不合成成功、不给缺图路径强制重传。明确永久422只有在该请求被确定拒绝且拒绝落盘成功后才能放开新意图；网络/5xx/原文件过期404保持 unknown/unavailable。submit 可能已有逐题提交，不把最后的失败 HTTP 一概当作“整批无副作用”。

停止本机重试必须先持久 disposition，再释放 lane；保留 body/key/receipt 证据，说明不取消服务端请求、不撤回已导入草稿，旧请求仍可能完成。迟到 A 不复活已停止 lane，不覆盖较新 B 结果；按 intent 顺序展示历史，不按响应抵达时间排序成最新状态。

## TTL、清理与未知结果

沿用 ADR-017：默认120分钟由 import-options/服务端配置给出，读取真实 expires_at；不写死为新产品规则，不延长已有 deadline。服务端清理会删原型 job、文件、候选和 DocumentImportBatch；`cleanup_expired` 还按响应内 job/id 清理原型幂等回执，已创建题目不删。此为数据库记录删除，不保证磁盘安全擦除。其他 receipt 后端的过期/清理等价性须单独验证，不从本地 proto 路径推断生产留存。

**有回执与已清理是两条路径：** 清理前，相同成功 key 可先于 service TTL 检查重放历史成功；清理后原资源404不能证明原动作失败。对 create 尤须限制：其旧 receipt/job 被清理后，同 key 可能重新执行 create，产生新 job，不能承诺任意延迟的 exactly-once。create 无已知 job TTL 时只在已建立且可信的临时恢复窗口内允许精确重试；不能确认窗口仍有效则先 unavailable，要求明确建立新任务，而非盲试旧 create。

已有 job 的 expires_at 和尚未获响应创建命令的保守本机截止分别记录；不能用每次点击/GET/新 File.lastModified 重置保留时间。服务端返回更晚的历史 expires_at 不使已到界的临时内容复活；本机未知/格式异常期限不能伪造一个新120分钟窗口。

当前 `expireImportRecovery` 会清理整个 owner 文档前缀，无期限 legacy 也会清理，`show` 还可能以 Infinity 触发清理。这与“未知请求原文永远留着”不能同时宣称成立。实施必须先写留存边界红测：迁移不借解析失败或 GET404主动覆盖/擦除尚在有效界内的未知 raw；已到既有期限的敏感文本/文件内容按现行临时政策清理，不为了 journal 移到无期限 owner 通用键逃避清理。过期展示 unavailable/无法确认，不改记 failed/acked；清理后不承诺还能恢复原 body。

缺期限/坏格式 legacy 的处理要与现有临时政策和硬规则一起经主线程审查，迁移本身不复制可疑内容、不制造新期限，也不自行改为永久保留。若产品需要跨 TTL 长期保留最小不敏感 tombstone/原始证据，属于留存设计，须由负责人在 Q-07 范围另行决定；本包不实现。不得把 unknown 的“本机不再重试/内容已清理”写成“服务器没有执行”。

## legacy 消费与权威顺序

旧 `document-import:{owner}` 的 requests、job、edits、batch/result 分开识别，在原有有效窗口内原 key/raw 保留，不回写新投影。新权威命令/题组草稿存在时，不从旧结果覆盖当前 history，不因新资源 scope 变化重 prepare 同 K。

先在 owner journal 找 K，核 method/path/资源关联、完整 canonical body、文件指纹和题组。相同已 ACK/已 rejected/已停止记录沿用原 identity/phase，不能重命名 resource 再 prepare 使 snapshot 冲突后复活 unknown。same key 异 body 阻断 HTTP、保留原证据。旧结果只有不存在新权威结果时可兼容显示，并明确是历史，不伪造 journal ACK。

旧 upload 只有 revision/文件名/大小/lastModified 元数据，没有原 SHA 与完整 wire 指纹，无法证明重选后是原请求；不能旧 K+新 bytes，不能用 GET 列表相似文件冒认成功。显示原 upload 无法精确恢复，明确保留未知并停止本机重试后才可新文件意图；新的当前 revision/原图读取不是旧指纹补丁。

合法完整非文件 legacy 可原 K/body 迁移，来源缺失或未知格式仅保留证据与人工草稿，不 cast 成生成 DTO、不补 revision、不把旧 expires 重新计时。消费标记只存最小摘要/终结状态，不复制不识别 raw 的潜在文件、base64 或认证字段；写失败不放行新意图。所有迁移与停止都在真实 WebLocks 内按 owner/job/题组串行，不声称跨浏览器/机器事务。

## 可执行文件分工与接口顺序

1. 主线程先合并并验证最终 Media 版本，记录 `DocumentImportView.vue`、`QuestionEditor.vue` 及对应 tests 的实际 SHA；再建立 Doc 隔离 stage。候选实现不能覆盖 Media 的 local-only、附件写入 Promise、lease/retention/serial/source 冲突防护。
2. Store/adapter 负责人新增 `src/document-write-recovery.ts` 与独立 tests：job/workspace/candidate-group draft、来源与跨 tab CAS、文件安全 descriptor、中央命令精确筛选/legacy消费、已有 TTL 的有界清理。仅在证明现有通用 store 做不到时另行分配共享 store 的最小增量；不能双人改同文件。
3. UI/controller 负责人以最终 Media View 为 base 修改 `src/views/DocumentImportView.vue`，必要新增 `document-import-actions.ts`；所有写调用转固定 binding/typed body，分离 current、draft、历史 receipt、公开持久状态与恢复按钮。`persistCandidateDraft` 必须等待同一权威 draft 的本机写入并遵守子编辑器 `isCurrent`，不能旁开一个独立兼容缓存抢写。
4. 审查者只读复核多文件状态/TTL/批次检查点、旧 ACK 不复活及 Media 附件回调。不改 API/contract/worker，除非先取得实际红测证明缺口且主线程另行授权。
5. 浏览器负责人新增隔离 `admin_document_write_recovery` Flow，先真实自编 JSON，再最小自编 PDF/DOCX/PNG；普通 UI 输入、选文件和明确恢复，实际 API 提交后压断响应。仅只读安全 journal/API/本地审计，截图/JSON不得含文件 base64、auth 或用户原卷。通过后再注册，不以本机配额 mock 宣称真实磁盘故障或真实 OCR 验收。

**API 结论：当前有界恢复不需要新 API。** 已有完整 typed DTO、同 key 回执重放、revision CAS、job/candidate GET 与逐题批次映射足够实现“临时窗口内精确恢复、过期未知可见、明确新意图”。本包不新增自动取消、幂等键状态查询或任意 TTL 后回执找回接口。若后续要求过期后也能安全证明原 create/submit 的命运，应先冻结回执留存与授权边界并单独契约设计；当前 GET 相等/不存在都不能替代。

## 先红清单与交付门禁

| 场景 | 必须先取得的行为失败与修复后证明 |
|---|---|
| 六类写动作丢响应 | create/upload/process/cancel/candidates/submit 真正服务端生效后丢包，刷新/关闭重开不自动 POST，显式恢复同 key、完整 wire/body；revision、文件、审计、题目映射不重复 |
| 文件精确重建 | 同名同大小异 bytes 零原键 HTTP；同 bytes 原 filename/revision 重建同 wire；不同名/MIME 布局不改已冻结 wire；journal/错误/截图/JSON扫描无文件原文/base64/path/auth |
| 无文件已知结果 | upload/submit result 写成 result_known 后 ACK 配额失败，重建离线只做本机 ACK，不依赖文件、GET、网络；旧 ACK+同 key legacy 不复活 |
| A/B 与多候选 | save A/submit A 在途改 B，含结构化无效表单、配对、拆合、顺序、意见和确认；B已落盘及B写失败两条都不被旧 A/旧 GET/选择覆盖，不导航，不把成功 q1夹带进失败 q2新提交 |
| 来源/CAS | 编辑初次 base r，GET r+1 后仍保留 r；显式比较/采用后才新 key+r+1。同 owner 真双 tab 连续输入冲突分支、刷新/载入/采用/主稿备份；相同多行 snapshot 不增写/分支，A→B→A 仍独立 |
| job/candidate/身份 lease | A选文件/读取/哈希/上传/GET/预览晚到时切 owner/token、卸载、切job、重建候选或编辑器失效；每个下一 HTTP 前守卫，旧结果只落原 history，不应用旧附件、不清 B auth |
| 文档 checkpoint | submit 第 k题 commit后进程退出、原 batch恢复只续其余且稳定映射；部分失败修正文案/保存后新 key只选失败项。并发 cancel/TTL/in-progress 锁序按原行为，不与审核 batch外层事务混淆 |
| TTL/回执清理 | 已有 receipt越过TTL的历史重放、清理后404、未知create窗口届满不盲重试、敏感草稿到界不延长；旧raw/消费marker/坏TTL不伪成功或失败。真实 receipt 后端留存差异单独列证据 |
| 故障窗口 | draft/prepare/result/ACK/reject/停止标记/采用分支每个本机写失败；缺WebLocks；422拒绝记账失败；均保留内存输入、原命令和零错误新HTTP，不误报成功/安全持久 |
| Media 兼容 | local-only不创建题目/会话；附件只在同candidate/lease且本机落盘成功后应用；新 Doc journal/深watch/轮询不覆盖最终Media的callback、source备份或quota失败保护 |

顺序：实际行为红测 → 独立 adapter → 最终 Media base 上的 controller/UI → 专项/既有组件 tests + strict/check-api → 主线程差异审查合并 → 新实际构建/真实浏览器 → 必要的全门禁。不得把隔离 stage 全绿当作包含并行未合并 Media/其他模块，也不得将只读设计计作动态验证。

本次仅形成设计；没有运行单元测试、浏览器、TTL模拟、故障注入或服务。模型继承父线程配置，具体型号未知。

## 动态探针后的结论更正

`var/probe_document_create_expiry.log` 已在新隔离SQLite/Mock API动态确认：create真实201响应全丢，任务及其create回执过期清理后，同key同body再次返回新201与不同jobId。首次响应丢失的客户端没有jobId/expires，不能用options配置TTL加本机时钟作为服务端防重建保证。因此本文此前“既有API足够”只适用于已有资源ID及仍在已知有效窗口的操作，不能覆盖这个create缺口。

实现create恢复前需先补最小固定创建窗口契约：服务端认可的deadline必须进入原不可变body；旧成功receipt优先，receipt miss且deadline过期禁止再创建。窗口须同时约束job与权威receipt保留，区分SQL成功回执与Redis协调lease，UTC/配置变化/legacy缺字段须有正式红测。字段和最小实现方案由主线程统一评估，当前尚未修改契约或产品，不以增加无限raw留存代替。

## 2026-11-16实施边界

媒体最终338项、真实恢复13项已整合验收。文档后端deadline契约与红测实现位于独立D:/tutor-doc-create-window-stage-20261116，实际API尚未改；前端从最终Media的DocumentImportView SHA 72eca424d2c98b697b146c3ebb2d18f01154bc2fe6efd6cf9a8dafdd479db3b1建立独立stage。旧无creation_deadline的create请求按新必填契约统一422，不绕schema寻旧回执；前端保留旧未知命令，不向旧key补deadline。本地已知成功的纯ACK不依赖HTTP，不受此升级限制。新协议有deadline请求仍先重放现存成功回执，再对miss检查窗口。
