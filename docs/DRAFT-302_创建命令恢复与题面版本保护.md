# DRAFT-302 创建命令恢复与题面版本保护

状态：本地工程阶段验收完成，真机独立待验。统一九门禁全通过：后端2204项、Flutter483项、Dart218项、后台197项及静态/类型/生成检查；显式真实基础设施92项和额外驱动单元1项通过。新四场景浏览器75/75，其他九条流程经定向补跑共292项通过，十流程367项均覆盖同一最终产品构建；Web/APK构建完成，USB为空未安装。详见var/quality-gates/draft302-final/status.json及var/draft302-artifacts.json。200变异首轮196捕获/4Redis基线失败，后续5目标补跑捕获且五轮基线各11绿，历史失败原因未重现，不称同次全绿。不得将本包创建恢复视作303其余写请求已完成。

## 已确认的缺口

`solve_controller.dart`的`PendingKeys`仅在内存。`_attachRemote`先createSession/createAttempt，再持久化active；服务端成功但响应丢失、结果未落盘即退出，重启会失去原键和ID。可能重复新增会话，或遇到attempt_in_progress。retry也使用内存键。

未绑定LocalDraft没有来源题面版本。离线v1写作答后服务端发布v2，createSession默认固定当前v2，客户端会把v1稿提升并同步到v2。重启已联网时还可能先用v2覆盖scope题面缓存。已绑定session固定题面API不能补救这个未绑定场景。

## 契约增量

SessionCreate增加可选integer、minimum=1的expected_question_version。旧客户端缺省行为兼容；提供时创建动作仅接受当前published版本相同，否则409 question_version_conflict，details给期望/当前版本，不返回答案、不建会话。题目不可提供沿用404，不开放任意历史版本。

版本检查在首次幂等动作内部；已经成功的同键重放仍返回原session，即使之后已发布新版。必须验证版本读取与创建的一致性，防止检查后又选新版本。契约→红测→实现→Dart/后台类型及真实样例生成。

## 持久命令与来源上下文

按用户/题目/workspace保存版本化创建记录：不可变intent_id、workspace、期望版本、origin/review/parent、两个阶段各自固定键和完整body、已确认session/attempt ID及版本、阶段和代际。首次创建与retry使用不同intent。

阶段：session_prepared → session_known → attempt_prepared → attempt_known → attached；异常blocked保留原记录。严格先保存准备记录，再发请求，再保存结果，再准备下一阶段；重启重放原body和原键，不能依据最新界面重新生成。最终目标草稿、active及完成标记单bundle提交，成功前不能清理命令。

沿用同KeyValueStore实例串行队列、scope lease，并检查intent/body指纹/代际。晚到响应不能切换新页面或覆盖新输入；账号切换禁止用新token重放旧账号操作。范围不等于跨进程事务或真机强制退出绝对无损。

每个workspace保存question_id/version及可信题面快照或不可变引用。缓存按题目版本隔离，最新GET不能覆盖已有离线输入的来源。启动先读取本机草稿/上下文/pending，再决定联网恢复；已绑定session读取固定题面，未绑定稿按来源版本创建并再次核对返回版本。

旧记录无可靠来源版本时fail closed：有可信session可经固定题面验证；未绑定记录不能用网络latest或可能已覆盖的旧缓存猜版本。保留原文，明确选择另开新版workspace，旧答案不自动迁移。版本冲突保留旧题面/答案/笔迹，不自动改body或换键。不改动其他attempt scope、pending copy及冲突留档。

## 失败规则

网络失败/超时/500/丢响应保留阶段重放；401暂停等待同账号恢复；已知资源404阻断，不能另建会话绕过。版本409、幂等body冲突、损坏记录阻断并保留证据。attempt_in_progress不把任意返回ID当作原命令结果，应明确选择已有草稿。作答已提交需读最新状态，不能恢复为可编辑。服务端成功、本机写回失败，原prepared记录必须仍可恢复。

## 红测与实施顺序

1. 契约/后端：旧请求兼容、新版本409、无半份session、并发发布与创建、先成功后发布再同键重放仍原版本。
2. 存储：两个创建阶段各窗口磁盘失败、键/body跨重启相同、上下文不可变、阶段CAS与租约、未知旧格式原文保留。
3. 控制器：session/attempt/retry丢响应后销毁重建不新增资源；收到响应但未落盘重启；晚到结果/继续输入/账号切换不串稿；404/409/已提交明确阻断。
4. 版本：v1离线输入后发布v2、重启已联网均不覆盖原题面或向v2 PUT；v1已创建丢响应后发布v2仍恢复v1；缺来源版本旧稿不猜版本。
5. 界面和整合：保留旧稿另开新版、阻断恢复、已有稿选择；真实浏览器服务器实际执行后丢响应/刷新/离线旧版，回归301B副本与固定版本。统计不能新增提交或重置辅助状态；真机单独验收。

另开工作区必须同时完成路由恢复引用、会话展示状态与异步回调代际切换。显式旧session/attempt不得在新workspace继续恢复，浏览器地址也必须切换，刷新后仍为新稿；原云端草稿列表主动选择的优先级保持有效。旧events（尤其完整解析）、evaluation、自查、复测结果不能留在新独立会话页，旧历史保留在原会话。迟到submit/tutor/同步/自查回调及finally不能更新新视图、清新稿或改变新请求busy状态；需实际红测覆盖。

本包仅创建命令。submit、辅导、复测完成、自查等跨重启命令恢复仍需单独登记，不能声称所有写命令已持久化。Q-07留存和判题政策不变。审查使用reviewer角色，实际模型标识未知。
