# DRAFT-303B 辅导与复测恢复设计

状态：固定Web/APK的本地工程整合验收完成，全部12条真实浏览器流程443/443通过；原生安装/手写笔/读屏仍待设备。下述调查段落保留历史基线，实际最终结果见文末。303A在固定Web/APK构建上完成整合回归，后续303B源码单独验收，不冒称旧构建覆盖新代码。审查与复杂开发角色请求Sol high，实际运行模型ID未知。

## 资源与持久协议

当前SolveController.tutor与_completeReview仍使用内存PendingKeys。服务端幂等回执与业务同事务，原键重放返回历史响应；历史响应不代表最新会话或复测状态。

辅导以session/<id>为journal目标；复测完成以review/<id>为目标。不能仅增加attempt lane：同会话副本共享教学状态，多个复测会话共享review，必须对目标资源串行并只保留一个未解决动作。来源仍固定owner、question/version、发起workspace/attempt、generation与activeEpoch，迟到结果只记原资源，不抢当前选择。

先持久完整生成请求类型序列化的body、method/path、随机intent/key，再HTTP；结果先落盘再专用ack。成功后的同类新动作生成新intent，不按相同body永久去重。未知/损坏/异账号/资源不符保留原文并阻断；不开放任意路径自动离线重放。

## 辅导

冻结POST /tutor/sessions/{sessionId}/next的完整TutorAction（action、confirm_end_independent）。确认位恢复时不得false变true。independent_attempt_in_progress是明确拒绝；学生再次明确确认解析时创建新的已确认intent，不能改旧body或自动确认。未知结果/重启后显示明确恢复入口，不后台补发教学动作。

先保存回执，校验事件所属资源，按事件ID/seq去重合并；再GET最新session并分页读完events，不能固定只取前200条或把旧回执直接替换当前session。assisted、used_solution、independent_ended不能从true退false，提示层级不能降低；confused_streak和普通state采用最新服务端值，不能对所有字段机械OR/max。刷新失败保持result_known，不能生成第二次教学动作。

受控运行验证规则/审核事件的事务一致性。orchestrator本地网关路径在调用前提交，不能据客户端journal宣称外部调用/费用exactly-once；外部调用发生后、业务保存前崩溃属于PROD-302B/COST待办。保持真实供应商关闭及Q-04/Q-06边界。

## 复测完成语义

Wire仅路径reviewId与body attempt_id。本机还冻结对应session、题面版本、真实已确认提交intent/结果；不能发送本机计算的passed/stage/due。

当前review_scheduler.complete以本人会话组→组内作答→ReviewItem锁序处理；provided Attempt可以是draft，实际采用该会话submission_no=1的提交。该提交必须submitted且verified；正确且independent才passed，其他verified可合法failed，因此不能仅对正确作答调用完成。pending/uncertain不能完成。review必须scheduled且到期。

review_already_completed、review_not_due、attempt_not_verified、attempt_not_for_this_review均为业务拒绝，不是本intent成功；记录拒绝并刷新状态，不换键/自动另开会话/推进本机stage。

后续实现须区分两类来源证据：本机已有未知submit intent时，先恢复原303A回执，不能以GET submitted替换该intent的结果；另一设备已提交而本机没有原intent时，学生明确发起“记录已提交复测”属于新的review动作，可单列server-observed来源，固定本人真实首次提交/session/review/题面版本并明确确认，不声称恢复了原提交回执。不得默默把未知本机intent降级到此分支，也不能因本机缺ACK永久拒绝其他设备已提交的合法作答。该分支尚需具体UI/红测，服务端history/legacy_unknown仍是推进是否允许的权威。

现GET /reviews/due即使all也过滤scheduled和已发布题目，列表缺席不能证明完成。契约先增加学生本人GET /reviews/{reviewId}/state，跨账号404，紧凑返回review/question ID、status、stage、total_stages、due_at、last_result、last_attempt_id、updated_at；不返回题干或未发布内容。历史回执结果与当前阶段分别显示，当前状态来自新GET。

## 服务端历史去重（已复现并修复，待整体门禁）

当前只比较last_attempt_id。C1完成→到期C2完成→再次到期旧C1用新key，真实API返回200并将stage2推进为mastered。红测tests/api/test_reviews.py::test_old_completed_submission_cannot_advance_a_later_due_window，日志var/draft303b-review-history-red.log，1项因预期409实际200而失败；不是依赖/编译错误。客户端去重不能提供跨设备保护。

该段描述修复前实现。修复已增加ReviewCompletionRecord及009追加迁移，唯一(review_id, first_attempt_id)。在既有R锁之后原子占据凭据，避免缺失行SELECT FOR UPDATE的gap锁再插入模式；只有冲突的已有行才current read。历史写入与阶段更新/幂等回执同事务，业务拒绝与回滚不留下假完成记录。

专项证据：var/draft303b-history-local-static.log共69项（复测API33、本地升级11、迁移静态25），var/draft303b-history-real-mysql.log共14项（新增history5、迁移执行器6、首次提交迁移3），均通过；真实MySQL覆盖独立复测同时完成、同项RR并发passed/failed、回滚、known/unknown回填与无效last阻断。009与真实验证候选逐字节一致后冻结，001–008未修改。紧凑状态GET另4API通过，130真实样例已刷新；完整门禁/新目标变异正在执行，不能据此关闭整个303B。

先红测：至少三个间隔，创建到期stage0；S1/C1正确独立verified以K1完成到stage1；到期S2/C2以K2完成到stage2且scheduled；再到期旧C1以新K3请求，期望409 review_already_completed，stage/due/status/last_attempt不变。另测failed重置、mastered拒绝及provided draft副本B仍只采用实际first C。只有运行证据后才标已复现。

修复候选：追加迁移（001–008不回写），唯一(review_id, first_attempt_id)完成历史，保存实际C而非provided B；在既有S→A→R锁内检查历史/verified/due，更新stage并写凭据，与幂等回执同事务。相同成功key仍优先历史回执；不同key重复C业务409。真实MySQL并发证明不能重复推进，不以死锁重试替代锁序。

旧历史不能从不可逆fingerprint或缺字段回执猜测。可靠last_attempt关联可回填已知凭据；其他迁移前合格首次提交标legacy_unknown，结果/完成时间未知，不伪造passed/failed。unknown专用409保留内容，学生在到期时可明确开始新复测，不自动另开。旧成功key仍优先重放。回填需校验本人/目标review/first/verified；不一致关联阻断并保留证据。此为待实现保守方案，须明确记录对旧会话的影响并测试，不将所有旧作答虚构为已完成。

## 验收与执行顺序

1. 契约先行、状态读取与历史去重红测；追加迁移、兼容、真实MySQL实现验收。
2. Store增加明确session/review目标scope与专用ack；不伪造空草稿以满足attempt lane。
3. Controller/page接固定命令、确认/恢复入口、最新状态与事件去重。A未结束前不争用文件。
4. 丢响应后重启原键恢复：提示层级/事件数/stage不重复；新点击可合法进入下一提示层。
5. 多副本/多会话共享目标、旧回执不回退solution/DONE、晚到不抢C、各落盘窗口失败、跨账号与损坏恢复、业务409不冒充成功、mastered/下线仍能读本人紧凑状态、legacy_unknown与旧回执兼容。
6. 生成Dart/后台类型/真实样例，专项与门禁、关键变异、实际浏览器；真机独立保留。

## 固定构建整合验证（2026-11-16，完整浏览器回归中）

后端历史去重、本人状态GET、首次提交定位、资源journal及页面恢复均已实现。真实浏览器还发现并修复两处产品缺陷：显式已提交路由重启时恢复上下文被302旧保护拦住；迟到提示刷新到服务端DONE后，页面仍保留答题操作。两处均保留真实脱敏状态快照，先行为红测再修复；DONE不禁用已有固定命令的明确恢复，也不把GET当未知提交的ACK。

最新固定构建通过537项完整Flutter与静态检查、221项Dart、197项后台及类型/契约检查。后端完整2255通过、100项未配置skip；后续变更的浏览器工具模块另103通过，不能说它们都来自同次完整后端收集。显式真实基础设施101项通过且无skip。

专项真实浏览器R3四条链36/36通过：辅导真实成功丢响应、旧提示迟到且已完成、复测成功丢响应、当前草稿B与他端真实首次提交C分离并明确确认。对应var/draft303b-browser-resource-r3.log。当前全12流程回归日志var/draft303b-browser-all-final.log，进程82861，须等退出与总计再标整体通过。

最新APK SHA256 cfb41c929e762a25e1eeab4c6e81aea417aaedaa998828d7cfb8c3a6633accc6，207758752字节，尚未安装真机。A完整206项变异与B新增首次提交定位2项变异是不同源码快照、独立运行，均捕获并核对源码恢复，不声称一次208全量验收。工程验收完成后继续303C；设备/读屏/笔验收另保留，不据此关闭全项目。

最终退出确认：原句柄82861 exit0，var/draft303b-browser-all-final.log总计443/443、失败0，全部12流程同次运行。固定APK保存在var/artifacts/draft303b/student-debug-cfb41c929e76.apk，元数据var/draft303b-build-artifacts.json。源码锁已解除并转入303C，后续资料保存修改不冒称由旧B构建验收。
