# DATA-304 学生数据范围与删除边界

状态：2026-11-17，依据当前源码完成范围盘点与实施依赖；不是已上线的完整导出/删除能力。Q-03真实身份注销、Q-07留存/备份/供应商处理条件仍未冻结。本轮没有删除任何数据库记录、设备数据或文件。

## 当前数据范围

最新静态盘点为 `var/student-data-model-inventory-diagnostics-20261117.json`：6个源码文件、39张表，包含源码SHA-256与字段名，含声明式模型及内部Table声明。原盘点 `var/student-data-model-inventory-20261117.json` 的5文件/36表是加入摸底计划之前的快照。盘点不连接数据库，不含用户行数或数据，不证明部署已应用迁移。对应源码为 `models.py`、`proto_models.py`、`media_models.py`、`scan_models.py`、`services/invocation_tables.py` 及新增 `diagnostic_models.py`；不能据此称导出完整。

| 范围 / 实际存储 | 归属路径 | 当前可导出内容 | 仍缺少的部分与删除依赖 |
|---|---|---|---|
| 摸底计划：diagnostic_states、diagnostic_runs、diagnostic_items | state/run.student_id，item经run归属；绑定session另由普通作答接口校验 | LEARN-301D本人历史分页及服务端学习记录导出已包含全部计划与当前工作区；绑定会话作答仍由原学习记录部分导出 | 新导出字段为可选兼容，旧文件缺失不代表无记录；SQLite/当前MySQL RR下验证读取快照。删除先清state.current_run_id引用，再删items和runs；items引用固定question_version及session，不拥有公共题库；结束不删草稿 |
| 本机摸底恢复：u/本人/diagnostic_bundle | 本机身份user_id及请求捕获的凭据/激活代次 | 摸底页单独导出本人缓存进度、固定请求/键与原回执；白名单不包含token、未知私有字段或其他学生。既有草稿导出范围不变 | 文件可查看、尚不可导入，也不因导出而自动清空历史；200条/2Mi字符上限仍拒绝新增而不自动裁剪。清理/归档待留存条件；停止重试不删除历史、不取消服务端请求 |
| 账户：users、student_profiles | 当前token user_id；profile.user_id | DATA-303B资料白名单，包括称呼、地区、年级、学科、教材与考试年份 | 账户状态/创建时间等不在资料接口；email_hash不作登录凭据或身份确认依据。真实身份注销、令牌撤销与身份服务协同待Q-03 |
| 学习：study_sessions、attempts、handwriting_drafts、attempt_self_checks、tutor_events | session.student_id；其余经session/attempt关联，不能只凭请求中的ID | DATA-303B会话、全部作答与副本、已同步笔迹、保存的自查选择与既有事件 | 不输出未请求的题库解析。删除须先处理事件、自查、笔迹与作答间依赖；复制关系 copied_from_attempt_id 需要从后代作答开始处理，不能直接按任意主键顺序删除 |
| 复测：review_items、review_completion_history | student_id；完成历史另核对first_attempt所属会话 | DATA-303B复测列表和完成历史 | 完成历史引用review和attempt，须在删二者前处理；删除不能把未知结果补造成通过/失败 |
| 授权：parent_student_links、parent_invites | student_id；家长token不能借此读学生内容 | DATA-303C已纳入本人现存授权/邀请记录白名单，含撤销/过期/兑换时间，固定history_complete=false；新字段缺失的旧文件不代表无记录 | 同一关系重新授权会覆盖consent_at/created_at，不能将现存行伪称完整历史或补造旧时间。不含code_hash、一次性明文码、家长ID/资料或兑换者身份。完整授权事件历史/留存仍待Q-03/Q-07；撤销与删除应立即切断家长汇总访问，不删除家长账户 |
| 媒体：media_assets 与 BlobStore 元数据/字节 | MediaAsset.owner_id；Blob.owner与有效期再次检查；新导出仅学生token | MEDIA-301C/D支持当前本人学生用途Blob枚举及ZIP主动下载：已可读字节和状态清单；预留/待确认不伪造文件，排除审核用途/过期/删除，不修改/续期。当前主要为拍题原图，未新增手写Blob上传，笔迹坐标仍走学习/本机JSON | 学生拍题不写MediaAsset，空表不证明无图片。源码扫描/总字节限额，坏数据/读失败整次失败；不含存储键/路径或完整历史。S3跨对象一致快照/持久索引、手写上传和生产留存仍待，不从已清理对象重建内容；Q-07未冻结 |
| 拍题：proto_scan_records | owner_id；payload只按学生可见字段解释 | DATA-303D已将本人现存文字/表达式/确认状态及原图引用纳入学习记录导出，包括尚未清理的过期行；读取只读、无原图依赖；受控环境null/旧文件缺失表示范围未提供 | 已清理历史不能恢复；空数组不表示从未拍题。坏数据整次503、超限整次413。不得调用会清理/commit或要求原图可读的scan_service读入口。原图字节另按媒体能力验收，本机拍题文字和现存恢复信息已由DATA-303E独立导出，不含原图和旧版废弃键；其他本机命令范围仍待；清理不能删除公共题库 |
| 模型用量：model_call_audits、model_budget_usage | 服务端HMAC伪名；预算只限student桶，绝不导出platform桶 | DATA-303H已纳入当前服务端伪名对应的调用白名单与student预算日桶，history_complete=false；旧密钥关联未补造 | 不是没有个人关联的数据。须定义本人字段白名单与密钥轮换关联，不能由客户端自行提交伪名；账单、审计与预算事实的留存/去关联方式待Q-07，不直接删掉未知调用预占 |
| 外调恢复与保护：model_invocation_intents、model_budget_incidents、model_dispatch_gate | actor_digest/上下文摘要；共享暂停是平台状态 | 不把内部原始metadata当作学生备份 | 删除前必须处理在途/未知调用及迟到审计，避免删账后重发或重新释放额度。不能因某学生请求而解除平台暂停。必要留存与去关联条件待Q-07 |
| 操作与幂等：audit_logs、idempotency_receipts、proto_idempotency_records | actor_id / user_id；不是请求传入的student_id | 原始审计/回执未导出；既有事件里公开的trace/request元数据仍保留 | 回执可能含一次性邀请响应或旧个人内容，不能因是“技术日志”就忽略其数据范围，也不能整包返还。删除/脱敏与故障恢复、重放约束需一并验证 |
| 本地身份：proto_local_identities | user_id；只存token_hash | 凭据不导出 | Mock身份注销必须令原token失效；不把删本机token当作服务器注销。真实身份联动待Q-03 |
| 审核员文档任务：proto_document_import_jobs/files/ocr_attempts/candidates/batches | job.actor_id；属于内容审核流程，不是学生练习存储 | 不纳入学生导出 | 不因题目被某学生练习过就给出审核员原始文档、授权证据或导入命令；审核身份的数据请求另行处理 |
| 共用内容：knowledge_nodes/edges、questions/versions/question_knowledge、solutions、rubrics、exam_region_rules、question_region_applicability | 题库/地区规则权限；不是student_id数据 | 仅保留学生已收到的事件/引用内容；不导出答案全集 | 不按“学生做过这题”删除共用题、其他学生数据或学科审校历史；创作身份与学生身份未来如何关联需独立授权 |

## 设备端不能遗漏的内容

DATA-303A仅导出当前身份 `u/<owner>/draft*` 对应的内容白名单，包括已保存作答、笔迹与副本。它不等于整个设备的个人数据。

DATA-303E已补本机拍题全部现存工作区的文字、表达式与现存命令/回执的只读导出，按学生隔离，包含未同步和旧工作区；过滤上传地址/凭据/原图，不改变未知结果或原记录。旧版草稿只解释现有文字和旧引用，不重建废弃重试键。它不等于完整设备备份。

设备还保存 `auth.*` 身份凭据、`profile_bundle` 的资料修改与分支、`resource-journal` 的辅导/复测恢复命令、拍题命令/文字、家长授权命令、按身份缓存的题目与教学事件。检查依据是 `core/storage.dart`、`features/solve/draft_store.dart`、`resource_journal_store.dart`、`features/profile/profile_journal_store.dart`、`features/scan/scan_command_store.dart` 与 `features/parent/parent_command_store.dart`。未同步内容不能从服务端导出推断已被备份。

DATA-303F已补“导出本机恢复记录”：本人资料修改/缓存、辅导与复测命令/压缩回执/缓存视图、学生授权命令/现存摘要；只读且过滤凭据、邀请码、家长身份和运行时代次，非跨bundle一致快照。Flutter733、实际离线下载41项、九项关键变异通过，见[范围与证据](DATA-303F_本机恢复记录导出.md)。resource-journal实际覆盖辅导/复测；建会话/建作答/同步/提交/自查等写历史仍位于DraftStore，不应将二者混为已完成导出。其他缓存、模型用量、导回恢复与完整删除仍待。

后续DATA-303G已将DraftStore现存创建、同步/提交/自查、压缩回执、未绑定提交、待建副本、后续分支、来源/编辑状态和引用追加到同一恢复文件的practice字段；公开题面只取工作区已收到的固定版本，不读取共用答案或审核文档。最新Flutter751、实际离线/提交后下载48项、12项关键变异及283份源恢复核验通过，见[DATA-303G](DATA-303G_练习命令与分支导出.md)。独立题目缓存、个人模型用量、大档案导出与正式删除/注销仍待，不称完整备份。

后续本机清理必须限定选定身份及关联文件；保留其他身份和未处理的冲突副本。清理前应告知未同步内容范围，由学生明确选择。服务端注销后须阻止旧离线命令重新建立数据；重新登录不能自动恢复已删除身份。已由学生下载/分享的文件不在应用可控制的删除范围内，不能承诺远程撤回。

## 删除实施的依赖顺序

1. 冻结真实身份注销/令牌撤销与必要留存范围（Q-03/Q-07），据此定义可删除、待处理、保留的类别；不自行指定保留天数或供应商删除承诺。
2. 先提供本人范围预览和明确确认。客户端删除意图先落本机，固定幂等键跨重启重试；家长不能代学生发起内容导出或删除。
3. 服务器阻止新增学生写入与外调，同时撤销家长访问；对已在途事务/模型调用逐项收敛，不用本机退出登录替代这一步。
4. 按上述实际外键与复制关系处理业务记录、媒体和客户端恢复状态。用任务结果逐类别报告已处理/仍待处理/按政策保留，不以一次HTTP成功代表全部备份和外部系统已消失。
5. 保留足以阻止旧令牌/旧幂等命令/备份恢复重新引入数据的机制；其内容与期限依冻结方案决定。备份恢复、迟到外调审计、多个设备离线、重复删除和中途失败必须单独演练。

现存授权/邀请及服务端拍题文字已分别由DATA-303C/D补齐；DATA-303E又补本机拍题；下一工程增量补媒体、其他本机命令与模型用量导出范围，复用现有归属和短期访问；完整删除在依赖冻结前仍只做上述设计与Mock验收方案，不提供可误认为已执行真实清除的成功入口。

DATA-303H已追加model_usage，独立保留调用估算及预算预占、不作为账单；本人token派生伪名，排除平台桶与内部request/trace等标识，继承共享条数/字节上限及快照。详见[范围与验收](DATA-303H_个人模型用量导出.md)。真实身份、密钥轮换历史、留存与删除仍未冻结。

DATA-303I已将本人根及attempt/local题面缓存纳入同一恢复文件question_cache；生成类型过滤未知字段，不从服务器补题或重建版本，缓存独存可离线保存。Flutter766、浏览器50及七项最终变异通过，见[独立缓存范围与证据](DATA-303I_独立题面缓存导出.md)。仍不代表整个题库或完整个人备份。
