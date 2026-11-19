# PROD-302 辅导事务与恢复设计（分层任务，尚未全部实现）

本设计承接PROD-301受控运行中next暂404的缺口。A和B是独立交付与验收任务；A完成不等于外部模型调用和恢复边界已经完成。真实登录/监护方案Q-03、供应商协议与能力Q-04、留存政策Q-07均不由本工作冻结；prod发布护栏继续保留。

## 当前证据

- `orchestrator._rephrase` 无受审换讲文案时，会先 `tc.db.commit()` 再调用网关，之后刷新session并写教学状态。
- `DbAuditSink` 与 `DbBudgetStore` 各自使用短事务。不能简单删除提前commit而让持有正式回执占位的SQLite写事务等待另一连接写审计/预算。
- 正式回执要求业务结果、事件及回执同事务提交，明确禁止action提前commit。SAVEPOINT释放允许，但在nested里手动Session.commit仍会在外层before_commit被拒绝，已有真实MySQL回归证明。
- `events.append_event` 通过max(seq)+1追加事件；不同幂等键对同session的动作需要额外串行，单靠回执唯一键不能保证session状态或事件序列一致。
- ModelCallAudit.request_id目前只有普通索引，不能把它当恢复去重或计费去重凭据。

## 独立任务 PROD302-A：受审内容与规则事务切片

目标：恢复managed next的已受审内容与规则动作，移除整条next暂404的状态；不调用真实或Mock gateway来冒充已完成模型分支。

范围：

- hint、standard、fast、visual、understood，以及有受审concept_rephrase时的confused，继续复用原教学规则。
- 没有受审换讲文案而原本需要网关时，产生明确的schema合法safe fallback；meta.source为rule_engine、degraded为true，不伪造provider/model/trace，不伪造网关审计或用量。
- 同一事务内先校验学生token及owned session，再取得该session写锁/条件写锁并刷新最新状态，执行动作，写教学事件与session状态，最后完成正式回执。
- 同key同请求只执行一次并重放；同key不同指纹仍409；不同key的同session动作串行，不能丢hint层级或重复seq。
- 保留独立作答泄题确认、used_solution记录、复测禁辅、主观题pending、schema/visual白名单、DONE拒绝等现有规则。
- local SQLite原型保持兼容，不通过本切片悄悄改变原有网关测试或启用外部模型。

专项验收：真实MySQL+正式回执+已授权隔离Redis；测试明确写入自编工程样题和fake身份用户，不启动seed。覆盖受审文案、无文案safe fallback且gateway.invoke从未被调用、角色先行/跨owner404、解析显式确认、同key并发重放、不同key层级/seq串行、写事件后异常全回滚。变异与浏览器窗口互斥。

状态：A已取得当前404的红证据，主线程批准后实现；最终验收结果以执行记录为准。B仍未实现。

选定保留RR的实现：owned session按id+student_id取得FOR UPDATE并populate_existing；SQLite使用同归属条件no-op UPDATE取得写事务。next/create_attempt/submit/sync_draft统一按session→attempt→draft→尾事件顺序写锁；attempt入口先只读session_id投影，锁session后重新读取/锁attempt并复核。GET路径不持写锁。锁标记绑定当前SQLAlchemy事务对象，commit/rollback后不沿用。

尾事件序号使用ORDER BY seq DESC LIMIT1 FOR UPDATE current-read，不用RR快照MAX；submitted_count读取current-read ID集合计数，open_attempt/attempt_no使用current-read并刷新ORM缓存。确定性真实测试先建立第二连接旧read view和旧ORM缓存，再等第一连接session锁、第一提交后恢复第二，验证状态和尾seq均刷新。另覆盖next-vs-submit及并发create_attempt。ID集合计数仅适合当前小切片；规模增大后需要索引/计数器及一致性方案，不能不加评审直接改回快照COUNT。

SEC304图示门控保持：未提交且未used_solution只给notice，确认flag本身不绕过；明确查看标准/快速解析并记录used_solution后才允许完整图示。

A明确不包含：外部调用、持久模型任务、发送状态不明时的恢复、供应商exactly-once承诺、严格费用预占。这些保留为B/COST301，不据此缩减原目标。

## 独立任务 PROD302-B：外部调用与持久恢复边界

跨端门禁/变异推进：审核后台429、Dart契约242、Flutter620均终态通过；Flutter首轮唯一失败为周报session计数写死7，而真实新响应样例为8，现按fixture实际计数验证UI，未改产品汇总（`var/prod302-full-flutter.log`、`var/prod302-full-flutter-r2.log`）。analyze、admin typecheck/checkapi、Dart生成检查及全Ruff通过。后端旧测试快照终态4 failed/2538 passed/116条件skip，4失败已在60专项修正；新全量35425正在当前树复跑，尚不计完成。新增PROD302B三条变异全部caught，JUnit基线有效、0skip，主线程核对两源码SHA恢复一致；证据`var/prod302-mutations/mutation-evidence-zjoz6j93/summary.json`。220全变异在814文件隔离源码副本`var/prod302-mutation-snapshot-151c074432af`运行（78019），排除.git/var/密钥/原始题库，不触碰当前测试树；两活跃句柄及日志登记`var/prod302-gate-live-jobs.json`，恢复时必须重新poll，登记文件不代表仍活跃。220未终态不得计全变异通过。

整包门禁进行中（2026-11-17）：首次全pytest因api/gateway同名test_content_references模块无法收集，网关文件已改唯一名test_gateway_content_references.py；全Ruff修正多行fixture参数noqa位置后通过（`var/prod302-full-ruff-r2.log`）。全量第二轮原进程38177继续运行，产品源码保持该轮快照，未终态不计通过。隔离复现已定位其最早4个失败：旧导入/版本/固定会话测试修改题干或移除solution却原样带过旧reference_links；输入现显式清除失效注记，未改产品校验，独立“旧hash编辑仍拒绝”负例也通过。受影响三文件完整60 passed（`var/prod302-legacy-edit-regression.log`），原红/绿见`var/prod302-first-failures-isolated.log`、`var/prod302-first-failures-green.log`、`var/prod302-pinned-regression-red.log`和green同名日志。原全量仍会保留其收集时旧测试的4个失败，须等其终态再区分新增失败，不能把60专项替代全量门禁。

定向维护入口已补：`tools/retire_model_invocation.py --student-id <UUID> --session-id <UUID>`默认仅预览eligible/applied计数，加`--apply`才在User→owned session→intent锁序下终结停用账号或DONE会话的活动意图。必须稳定服务端secret、已存在表；prod拒绝，不增HTTP入口、不自行批量扫描/删除或确定留存期限。健康会话/不存在或不归属的目标不处理，写入只CAS stale/释放活动槽，不退预算、不发模型，迟到审计仍可补。停用/DONE两个分支及预览不改、重复应用、健康不动、另学生目标不动已覆盖；HTTP既有组合11通过（`var/prod302-maintenance-green.log`），所有权专项见`var/prod302-maintenance-targets.log`，CLI帮助入口见`var/prod302-maintenance-cli-help.log`。初`var/prod302-maintenance.log`是测试块错位的工具错误，不计行为红。维护命令未针对任何真实用户库执行；是否自动调度以及生产留存仍属后续运维/待决边界。

真实MySQL到期并发恢复补证：自编发布题、实际HTTP、实际Mock发送后中断，时限内409，到期8线程同时恢复。首红`var/prod302-expired-concurrent-mysql.log`复现真实竞态：cleanup使用旧active快照，在另一线程已closed_unknown后仍尝试stale，抛ValueError。现capture持锁后再以FOR UPDATE当前读核验意图终态/代际，终态不重复清理。原启动/成功/超时/并发组合4 passed无skip（`var/prod302-expired-concurrent-mysql-green.log`）；再分别真实Redis协调与无Redis仅SQL两场景2 passed无skip（`var/prod302-expired-concurrent-redis-db.log`）。两者均8线程只1个fallback事件/1份对应key正式回执、adapter1次、两桶各1请求、无证据时审计0，不靠Redis保证业务正确性。并发过程允许409提示重试，最终原key回执可重放。后续仍需陈旧/用户停用维护、关键变异和全门禁，不将本组合视为整包关闭。

启动装配已接通：Settings增加durable_model_invocations_enabled（默认false，.env.example保持外调false），开启前必须显式注入SqlReceiptStore和稳定pseudonym_secret，缺任一立即拒启动，防止重启后调用ID/预算身份漂移。local原型只在显式开关下追加意图表；managed只读核验既有014表、必要列、主键及活动session唯一约束，不自动DDL/修复。lifespan校验后装配带同一clock的InvocationStore；关闭开关时state为None。4项本地配置/实际启动/缺表不DDL测试通过（`var/prod302-startup-wiring.log`，首次lint已修）；真实MySQL/Redis显式启用启动及原两HTTP链合计3 passed无skip（`var/prod302-startup-mysql.log`）。本轮无行为红证据。prod原拒绝仍保留，真实外调仍未启用；启动装配不代替未知/陈旧MySQL并发、关键变异和整体验收。

陈旧意图终结已实现：409路径在原业务事务回滚后，独立短事务按真实账号/归属session重新capture（仅此清理允许DONE），确认context_digest确已变化才CAS stale并释放占位；原指纹不匹配的请求不允许清理他人原意图。新key准备时也会持锁比较已有活动意图，旧上下文失效则同事务终结；同上下文仍占用则明确409而非唯一约束错误。stale保留请求/费用，迟到审计可补记但状态仍stale。真实HTTP测试在adapter期间再发实际request_hint改变上下文，旧调用409且占位释放、新key成功、旧key重试不重发，HTTP+prepare10 passed，Ruff通过（`var/prod302-stale-intent-http.log`）。本轮无行为红证据；身份停用时请求在鉴权前被拒，其遗留意图仍待有权限的维护机制处理；全MySQL到期/陈旧并发与启动装配继续未完成。

未知发送超时恢复已落地：dispatch原子记录由既有gateway plan.timeout_s推导的recover_after（metadata JSON，未另定供应商SLA），时限内同key409且不发送，到期CAS outcome_unknown。原上下文仍有效时，用正式回执事务写安全rule fallback并终态closed_unknown、释放活动槽；预算保持占用、没有真实结果证据不伪造审计。业务超时不证明供应商worker已停止；同attempt永不重发，迟到结果只能同事务补审计/差额，保持closed_unknown，不应用模型正文、不重新激活槽。真实HTTP测试在实际Mock调用后、结算前抛异常，时限内等待/到期fallback/原回执重放/迟到审计两次仅1行全覆盖；组合27 passed，Ruff通过（`var/prod302-unknown-http-red.log`实际409行为红、`var/prod302-unknown-http-final.log`终态0）。中间late-audit测试块错放导致的测试辅助错误不算行为红，已修正。旧无recover_after记录不自动推定过期；原上下文失效、账户停用/DONE时的陈旧意图终结、真实MySQL到期并发与启动装配仍待继续，B不关闭。

真实MySQL/Redis完整HTTP补证：受控staging、隔离新库001–014、真实身份适配测试用户、经独立审校发布的自编题、ScriptedProvider单次调用和正式SQL回执，成功/超时两项HTTP流程通过且无skip（`var/prod302-full-http-mysql-green.log`，进程终态0）。adapter调用前独立连接确认dispatch_unknown、两桶请求槽已落库、审计尚无行；结束后applied、审计1行、两桶各1请求，同key原响应重放且adapter仍1次。首轮真实红测发现applied接口错误要求Engine对象同一，实际应用与store两个Engine连接同一DB；现比较完整URL配置（含凭据，不输出），同库多Engine允许、跨库仍拒。首红`var/prod302-full-http-mysql.log`，SQLite跨库拒绝回归`var/prod302-engine-binding-regression.log`。这证明当前两种HTTP业务路径，不扩展为所有旧RR竞态或未知发送恢复的完整验收；真实外部调用仍未启用。

额度拒绝HTTP缺陷已修：平台/学生额度耗尽原先从底层抛ValueError成为未处理服务错误，真实HTTP行为红证据`var/prod302-budget-http-red.log`。现专用InvocationBudgetExceeded区分无发送的额度拒绝；事务已回滚后仅取消仍未发送意图，再用正式回执事务生成BUDGET_EXCEEDED规则降级。成功候选adapter0次、审计0行，原满额桶不变、另一个桶不存在，意图cancelled_unsent。两个范围均覆盖，HTTP+store组合9 passed，Ruff通过（`var/prod302-budget-http-green.log`）。底层其它状态/存储故障不冒充额度拒绝。应用启动默认仍未启用持久流程，后续继续活跃执行者恢复和真实MySQL HTTP整链。

已结算正文丢失的HTTP恢复已补：settled_metadata且无正式回执时，同key不再请求模型；持锁校验原上下文后生成不含模型正文的rule fallback，与applied/正式回执同事务提交。测试在供应商完成并结算后、finalize前抛异常，再通过真实HTTP同key恢复；adapter仍1调用、审计1行、两桶1请求，后续回执原响应重放。原4类HTTP加此恢复共5通过，Ruff通过，`var/prod302-settled-recovery-green.log`。`var/prod302-settled-recovery-red.log`实际为测试辅助函数重构顺序错误（adapter未定义），不作为产品行为红证据；已修正并复验。dispatch_unknown仍不能据重试判断原worker死亡，保持409且不重发，尚需明确活跃执行者/未知结果恢复边界；正式启用仍受后续验证和Q项约束。

HTTP编排首次接通（显式依赖注入，默认未启用）：tutor.next仅在app.state.invocation_store存在且mark_confused无受审换讲时调用durable_rephrase；正式回执先重放，再稳定意图prepare→最新上下文dispatch/预算同事务→gateway单次调用→独立审计结算→run_idempotent内事件/应用状态/回执提交。模型超时无重试，结算后发合法rule fallback；无候选则取消未发送意图、零供应商/审计/预算并由受审规则降级。真实HTTP契约客户端4项通过（成功/超时/候选禁用及同key原响应重放），仅使用自编种子/ScriptedProvider，无外调；`var/prod302-durable-http.log`。此轮无行为红证据。应用启动尚未装配invocation_store，已有dispatch_unknown/settled_metadata无回执的恢复仍409且不重发；额度拒绝异常分类、恢复fallback、真实MySQL完整HTTP锁序、超估算与配置不可用处理仍待完善，不能据此关闭B或启用真实供应商。

网关单尝试接口已新增prepare_single_attempt/invoke_single_attempt：按现有配置、外调门控、价格与熔断选择一个候选并固定请求JSON；发送前重新检查配置与估价，价格涨过计划估算则不发。同计划实例进程内锁保证最多消费1次；无自动重试或跨候选回退，超时返回未知上游结果，供应商异常仍不外泄。该接口刻意不调用旧_finish，不额外写预算/审计，由持久编排事务负责。4项新增测试覆盖超时只调用1次、不fallback、重复消费与8线程复用、请求快照、禁用候选；网关213 passed，Ruff通过，`var/prod302-single-attempt-red.log`与`var/prod302-single-attempt-green.log`。初红为缺失方法，不当作既有行为缺陷。接口本身不查询dispatch DB许可，必须由前述dispatch_rephrase成功之后受控调用；尚未装配到HTTP路由，不单独提供对外入口。

发送前上下文守卫已新增invocation_dispatch.dispatch_rephrase：服务端核对actor/session/budget绑定，结束请求级读事务后，在store.dispatch独立短事务内先require_context锁User→session→固定教学材料，再锁意图→平台预算→学生预算，与finalize保持同方向。此服务不做网络IO；只有dispatch事务返回成功后的调用方才可发送。真实API会话hint改变后旧意图发送拒409、状态仍prepared且无预算桶；显式取消旧未发送意图/新key捕获新上下文可准入，重复dispatch拒绝且两桶仍1请求/3估算。上下文/prepare/finalize/store组合9 passed（`var/prod302-dispatch-context-guard.log`），Ruff通过。本轮无行为红证据；guard路径真实MySQL锁序并发、adapter单尝试接口及路由编排尚待，原始无guard底层store仅限内部测试/后续受控调用，不作为应用授权入口。

HTTP键准备映射：新增prepare_rephrase，服务端secret对actor加盐key_digest作域隔离HMAC形成稳定内部ID；按原请求fingerprint识别冲突，命中原意图时返回其原上下文/代际，不按会话新状态重绑。不允许在正式receipt保护中准备或提交无关ORM改动；首次capture后结束读事务才在独立短事务落意图。测试会话hint变化后同key仍取原意图、改body同key409、正式回执阶段拒prepare；与finalize/store组合5通过（`var/prod302-http-intent-mapping.log`）。quota_day在prepared阶段仅暂定，dispatch首次实际准入时用store注入时钟UTC日固定并同事务保存；prepare重放不拿旧暂定日覆盖已准入日，跨年恢复测试证明固定2027-01-02。迁移静态清单已追加014；该变更的首次静态失败日志保留`var/prod302-mapping-migration-mysql.log`。服务仍未挂HTTP/发送，dispatch前最新上下文复核及过期意图回收/留存政策待继续。

正式回执保护补证：finalize测试增加真实run_idempotent+SqlReceiptStore.protect路径，callback在事件后故障时自动回滚事件/应用状态/正式回执；同key重试成功后再次重放，响应bytes相同且Idempotency-Replayed=true，回调仅执行失败和成功各一次，事件与正式回执均1条。另finalize必传服务端expected_fingerprint并与准备意图比较，错误原请求摘要409；测试准备摘要取实际method/path/body规范化函数。2 passed，Ruff通过（`var/prod302-finalize-formal-receipt.log`）。这是直接调用真实回执组件的服务集成证据，尚非HTTP路由/鉴权适配器/真实MySQL上下文锁序全链；不启用外调，后续还需稳定HTTP-key→invocation映射与发送恢复编排。

实际换讲finalize服务已新增`invocation_finalize.finalize_rephrase`：在调用方事务持锁重捕上下文，按服务端pseudonym派生actor/session绑定，复核记录/代际/版本/事件序号、settled审计task/status/schema与成本；重新运行OutputValidator及固定版本引用目录交集检查、复测门控，再同事务CAS applied、标assisted、写合法model hint事件。外部调用正文不持久化到意图；服务本身不commit。测试使用真实样题/DB/教学Schema，显式写正式IdempotencyReceipt模型，证明外层rollback同时撤销事件/应用状态/回执，提交则共同保留，危险标记输出拒绝且保留settled_metadata；相关组合7 passed，Ruff通过（`var/prod302-finalize-transaction.log`）。首次失败为测试将dict事件当对象的断言错误，不算产品缺陷红证据。该测试没有经过run_idempotent/SqlReceiptStore.protect或HTTP路由，不能作为正式路由已接通证明；下一步接线前须验证正式回执保护和真实MySQL上下文锁序，dispatch编排/恢复fallback/超估算告警仍未完成。

最终事务基础接口已实现：InvocationStore.applied_in_transaction要求调用方已有同数据库事务，仅允许settled_metadata且fence/context_digest匹配、全部attempt已settled，CAS转applied并释放活动占位；接口不commit，也不生成教学事件或正式回执。SQLite验证错摘要拒绝、外层rollback保留settled_metadata及占位、外层commit后applied并可开新意图，组合19通过、Ruff通过（`var/prod302-apply-transaction.log`）。本轮无行为红证据。接口的context_digest必须由持锁require_context/capture_context获得，不能来自客户端；当前尚未由orchestrator调用，最终事件+回执同事务闭环仍未完成，不把基础接口称作完整finalize交付。

上下文完整性补强：实际两条行为红测证明旧helper未包含Solution变化、未复核停用用户；现先锁并刷新User验证active/student，再锁归属session与固定版本，并用current-read纳入按kind排序Solution及Rubric。仅保存摘要不保存其正文。内部Schema必填context_digest且prepare重放身份比较包含该值，不能将恢复意图绑定到另一份上下文。4项API通过，状态/存储/Schema/API组合23通过；`var/prod302-context-guards-red.log`、`var/prod302-context-guards-green.log`、`var/prod302-context-binding.log`。真实MySQL上下文旧视图和全锁序审查仍待，未接入finalize。历史“Solution/User未覆盖”缺口据新证据已修复。

服务端上下文基础：新增invocation_context.capture_context/require_context，在现有lock_owned_session事务锁内读取固定QuestionVersion当前内容、教学与答案、会话/提交/活动作答状态和current-read事件尾序号，只产出SHA256摘要。require_context不提交事务，保留锁供后续事件+回执原子提交。真实API创建会话后捕获、请求hint改变会话再验证旧摘要返回409，以及独立账号404两项通过，`var/prod302-context-green.log`；首轮缺模块收集失败不计行为红，另账号测试最初错误复用同一fixture已修正。此helper尚未绑定意图Schema或finalize；不覆盖Solution表内容变化、用户active再校验或真实MySQL旧RR视图证据，后续须补，不能据此接通外调。

结算输入补强：dataclass不提供运行时类型约束，实际红测证明负估算成本可写入审计并推进settled_metadata。现在写事务前严格验证非负整数（拒bool/小数）、status白名单与布尔标记；非法元数据不能推进状态。`var/prod302-audit-validation-red.log`、`var/prod302-audit-validation-green.log`，组合222通过，Ruff通过。finalize源码调查确认：正式SqlReceiptStore只允许业务+完整回执同事务提交，原orchestrator先commit再调用网关不能直接装入该保护；StudySession没有context_generation字段，最终接线须先明确定义服务端上下文摘要/代际，不能仅相信存储调用者传来的数字。未完成finalize，不以metadata结算代替教学事件已应用。

结算重放补强：同attempt/fence且审计字段一致时返回settled_metadata，不重复差额或审计；不同审计内容明确冲突。审计时间要求带时区，写入/比较归一UTC毫秒，与MySQL DATETIME(3)一致。SQLite重复结算行为先红后绿（`var/prod302-settle-replay-red.log`、`var/prod302-settle-replay-green.log`）。真实MySQL从迁移、8线程prepare、故障dispatch回滚、8线程dispatch到未知恢复再8线程同attempt结算完整组合1 passed无skip，最终审计1条、两桶各1请求/5估算；`var/prod302-settle-replay-mysql.log`。settle读取使用FOR UPDATE当前读以串行同意图；结果正文仍不持久化，应用级事件/回执finalize、超估算处理与网关接线仍待实现。

审计结算基础已实现：内部状态新增settled_metadata（仅用量/状态已确认，模型正文未持久化，不能据此恢复教学结果）。settle_metadata按actor/fence/attempt校验，将attempt标settled、审计以稳定attempt_id作为PK写入；报告估算高于发送前预占时，差额按固定quota_day同时补至平台/学生，低于预占不退款。全部与状态CAS同事务，before_commit失败证明状态、差额和审计一起回滚；SQLite成功后两桶3→5、审计1条，组合19通过、Ruff通过，`var/prod302-settlement.log`。本轮无行为红证据。重复settlement目前拒绝，不重复写审计；仍需实现同元数据重放与不同元数据冲突校验、真实MySQL验证、超估算阻断/告警与最终教学应用事务，现不接入外部发送。

未知发送持久恢复已补：新store实例可将dispatch_unknown按actor/state/fence CAS转为outcome_unknown，重复恢复同fence返回原记录；不清活动占位、不退预算、不允许claim/cancel/再次dispatch。缺失方法红测后SQLite/状态/Schema19通过，记录`var/prod302-unknown-recovery-red.log`、`var/prod302-unknown-recovery-green.log`。真实MySQL在before_commit注入故障，确认marker仍prepared且预算桶全空；随后8线程唯一dispatch成功，重建store恢复未知、prepare重放仍未知且预算不变，1 passed无skip（`var/prod302-unknown-recovery-mysql.log`）。before_commit故障证明提交前回滚，不代表提交已成功但回包丢失的结果已知；后者必须读取持久marker，未知不重发。尚未接入应用/模型发送与最终审计事务。

预算身份已补齐：未上线内部Schema必填budget_key，固定为现有pseudonym函数生成的stu_加32位摘要形式，prepare重放将其纳入不可变绑定；dispatch使用该键而非actor_digest，避免新旧路径分桶。缺budget_key的早期隔离测试记录不补值、不发送。身份回归先红后绿，组合222 passed，`var/prod302-budget-identity-red.log`、`var/prod302-budget-identity-green.log`。真实MySQL新建唯一库运行001–014后，8线程同意图dispatch仅1个成功，学生/平台均只占1请求槽和3估算，重放prepare保留dispatch_unknown；1 passed无skip，`var/prod302-dispatch-mysql.log`。此字段仍只由服务端创建，客户端不能指定。真实MySQL故障回滚、上下文代际与最终审计结算仍待继续，应用未启用此新路径。

dispatch基础事务已实现：InvocationStore按prepared/state/fence CAS写dispatch_unknown与attempt估算，同事务按平台→学生占用固定quota_day的请求槽及估算成本；限额/commit失败整体回滚，重复dispatch拒绝而不重复占用。SQLite测试确认限额0、before_commit故障均保持prepared且无预算桶；成功写两桶各1次/3估算，二次dispatch不增。组合19 passed，Ruff通过，`var/prod302-dispatch-red.log`首轮因缺失方法失败，`var/prod302-dispatch-green.log`为完成后记录。当前预算学生key为actor_digest，尚未与旧网关student_pseudonym桶统一，未接入真实发送；下一步须先统一稳定预算身份、真实MySQL并发与故障事务、上下文再校验及审计结算，不能直接启用该路径。

prepare重放补强：真实重复prepare先因唯一约束失败（`var/prod302-prepare-red.log`），现冲突事务结束后另开事务按actor读取并比较完整身份绑定，匹配返回当前意图及当前fence；不同fingerprint/actor/session等拒绝，不回退到初始状态。SQLite/迁移规则/Schema组合18通过（`var/prod302-prepare-green.log`）。真实隔离MySQL执行001–014迁移后8线程同ID均取得同一记录，表仅1行，claim到fence2后重放仍2，1 passed无skip（`var/prod302-prepare-mysql.log`）。旧“014未验/重复prepare拒绝”描述保留作历史，以上述新证据为准。dispatch与预算事务及应用接线仍待完成。

持久准备记录第一步：追加014_model_invocation_intents.sql（不回写历史迁移），独立内部InvocationStore保存Schema限定元数据；active_session_digest唯一占位限制同会话并行意图，按actor读取，prepared更新同时比较state/fence，取消未发送任务才释放占位。SQLite真实文件中新store读取、跨actor不可见、同会话不同ID冲突、8线程旧fence仅1个成功、取消后新意图可建立的组合测试通过（`var/prod302-store.log`），Ruff通过。本轮没有行为红证据，不能称TDD缺陷复现。该store尚未装配到应用启动或网关，也未验证014真实MySQL迁移；现有SQLite升级不自动创建此表。重复prepare当前依赖唯一约束拒绝、尚不返回同ID原意图，下一步须补稳定身份重放语义与dispatch/预算同事务。不能据此启用外部发送或声称完整恢复实现。

状态迁移基础已实现于`services/ai_gateway/ai_gateway/invocation_state.py`：prepared领取递增fence；旧fence不能dispatch；dispatch_unknown不能领取或撤销为未发送，只能恢复为outcome_unknown；quota_day及身份绑定保持原值，输入snapshot深拷贝。6项新测试及网关/Schema合计220通过，Ruff通过，`var/prod302-state-green.log`。首轮`var/prod302-state-red.log`仅为模块尚未存在的收集失败，不称作行为缺陷红证据。纯迁移函数不授权发送；下一步持久store须在同事务CAS原state/fence、写新记录与成本预占，提交后才允许adapter调用。当前尚未接入持久存储或生产路径。

内部元数据契约起点已落地：`contracts/model_invocation.schema.json` v1与11项契约用例（`var/prod302-invocation-schema.log`）。只允许内部ID、身份/会话摘要、内容版本与代际、fingerprint、固定UTC额度日、fence及attempt估算/状态，拒绝原始prompt/response/input/image/key等额外字段。prepared/cancelled_unsent禁止存在发送attempt，dispatch_unknown/outcome_unknown/applied必须有attempt。Schema仅验证记录形状，不证明合法状态迁移、唯一ID或原子持久化；持久store与fence CAS、发送前预算事务、恢复处理仍待实现。无原始结果留存，schema没有result_ready状态；以后若获批准存结果需显式版本升级。未接入外部模型发送或生产路径。

本节是待评审设计，不授权立即创建保存原始内容的表或新增留存政策。

建议持久意图/attempt的最少元数据：actor、幂等键摘要、fingerprint、session及question_version、明确的上下文版本/代际、owner fencing token、预算准入固定UTC日、稳定内部invocation ID、prepared/running/result_ready/applied/outcome_unknown等状态。最终字段和迁移先经评审，不能直接把尚未完成的正式回执reserved状态单独提交。

阶段划分：

1. prepare短事务：授权校验、建立唯一意图与上下文快照，提交意图，不推进教学结果。
2. dispatch：每个attempt有唯一ID；条件领取后，将“可能已发送”的durable dispatch标记与该attempt成本预占在同一短事务提交，之后才允许adapter发送。Redis只协调，DB状态/fence仍是权威。
3. 结算：attempt结算、调用元数据及唯一审计记录须同事务，不能分别成功或吞掉审计错误。候选结果即使通过schema仍需留存评审；未经批准不落盘，不把原始响应脚本、原图、prompt或学生输入存入意图。
4. finalize短事务：重新核验用户active、owner、session未结束、题目版本和上下文代际；条件匹配才原子写教学事件、session与最终正式回执。迟到旧owner不能覆盖新状态。

需要统一所有相关session写入的锁序或单调代际。DATETIME(3)的updated_at不足以充当并发fence；仅依赖同key锁也无法拦住另一动作或提交改变上下文。具体跨模块修改范围须在B评审时列明。

### 崩溃与不确定性

| 状态/证据 | 可恢复动作 |
|---|---|
| prepared且确认未发送 | 可按唯一claim重领 |
| result_ready已持久化 | 复用已验证候选结果，不重新调用 |
| applied且正式回执存在 | 只重放DB回执 |
| 请求可能已发出、结果尚未持久化 | outcome_unknown；在供应商幂等/查询能力未核验前禁止自动重发 |
| 返回时上下文已过期/改变 | 不应用旧结果；保留真实调用元数据，采用受控规则降级/待复核 |

网络请求发送成功和本地持久化之间没有天然原子性。不能把重试或outbox说成供应商外部exactly-once。未知结果可采用已记录的安全fallback结束本轮，或明确待恢复状态；公共响应与重试语义应先核对契约。不能让客户端换一个新key就绕开仍在进行的同session意图。

### 审计、用量与费用

稳定内部invocation ID和数据库唯一约束用于防恢复重复记录，不依赖可变化的HTTP X-Request-Id。即使业务finalize失败，已发生的调用审计仍应保留；它不能被业务rollback抹掉。反过来，尚未调用时不能伪造调用审计。

usage缺失、发送状态未知仍是未知，不能按0费用处理或擅自退款。严格预算预占交COST301协调：现有原子累加只防计数丢失，不等于并发额度保障。预算预占、结算、审计幂等及供应商重试范围需共同设计。

与 [COST-301 并发预算预占设计](COST-301_并发预算预占设计.md) 共享服务端稳定的逻辑invocation ID；逐次供应商尝试使用其下属attempt ID，不能各自再创建无关联的重放状态机。invocation必须绑定actor/session/generation/fingerprint及预算准入固定UTC日；session.active_invocation_id或等价DB唯一占位阻止换新key绕开inflight。UTC日期在预算准入时固定，业务finalize失败不能把已可能发送的请求槽退回或转移到次日。PROD302-A无网关调用，也不应占用这一逻辑调用额度。



B不能原样带入现有gateway的自动timeout重试黑盒或吞审计异常行为；发送状态不明时是否可再次调用必须逐attempt作明确决策。refund仅允许能证明未越过durable dispatch边界、且旧owner fence已失效的未发送预占；否则保守占用，不能因为业务rollback就退款。

### 留存评审边界

当前只准备版本化受审内容引用、规则模板及prompt版本摘要；无法重建时failclosed，不补存原始内容。通过schema的候选事件也可能包含学生内容，不能因此默认落盘；留存审查须包含events、receipt、审计和备份等全部副本。不得在本任务中擅自建立原始prompt、图片、学生输入或原始供应商响应的存储。候选结果是否落盘、访问控制、清理周期、跨区域及第三方条款须在B/Q-07评审中明确。当前文档不将任何暂存时长定为生产政策。

状态：只读设计待细化；尚未实现持久意图、dispatch/result/finalize恢复或外部调用保证。

## Redis依赖组（已整合）

主线程已添加redis可选组并锁定redis-py 7.4.1；真实Redis回归使用两个显式依赖组：

```powershell
uv run --group mysql --group redis pytest tests/integration/test_durable_receipts.py tests/integration/test_redis_invite_limits.py tests/integration/test_managed_runtime.py -q
```

只写--group mysql可能因未安装redis而skip，不能当作真实Redis已验证。真实infra门禁统一使用mysql+redis组；未配置私密隔离环境的skip须单列，而配置存在但驱动缺失的门禁应失败而非悄悄skip。本包不修改pyproject或uv.lock，依赖组更新已由主线程完成。


## A执行记录

- 首红：受控next请求hint期望200，实际404，确认功能缺失。
- A实现保留RR与SEC304，不调用gateway；B没有追加意图/结果留存表或迁移。
- 最终相关组合278 passed、0skip，包含12项真实MySQL/Redis A用例、13项managed生命周期及旧tutor/attempt/proof/experiment/subjective/visual规则。另补next-vs-submit事件先后与independent/assisted对应断言，单例1 passed。
- A五条锁/刷新/尾序号/门控/禁止网关关键变异5/5捕获；更新后的managed原型路由隔离1/1捕获。由脚本owner互斥执行，baseline实际通过、无skip/error/not_run，源码finally恢复。
- 七个相关Python文件Ruff及格式检查通过。完整仓库最终门禁由主线程统一运行；本记录不把B或生产发布标成完成。
