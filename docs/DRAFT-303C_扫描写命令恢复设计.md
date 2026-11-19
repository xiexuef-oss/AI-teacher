# DRAFT-303C 扫描上传与确认命令恢复设计

状态：设计已形成，客户端实施准备；不改API/契约/数据库迁移。后端只读，真实OCR仍禁用，Q-04A/Q-07不冻结。Parent固定构建588与真实浏览器验收独立，未编译的新Scan源码不冒称由旧包覆盖。

## 服务端事实与边界

planned.py/实际services/api/tutor_api/services/scan_service.py：createUpload可仅metadata原key重放；content/createScan/confirm在幂等前检查资源归属/TTL。媒体TTL由media_temporary_ttl_seconds配置（默认7200秒），Scan共用媒体expires_at；过期404不能证明原动作未成功。createUpload旧成功回执还可能指向已过期媒体。

GET仅owned scan，能读当前payload及matched_question_id，不读upload metadata，也不ACK原命令。confirm仅匹配published/self_authored工程样题，不建session/attempt/draft；Scan已确认后新key再confirm返回409。FS reserve/put与SQLreceipt非同事务，只保证客户端固定意图，不夸称跨崩溃exactly-once。

## 本机状态与隐私

新增owner级单bundle，以真实本地workspaceId分离各图片/扫描；它是本机标识，不伪造mediaId/scanId/questionId。文字、编辑代际、active workspace、四类命令历史原子局部修改；LocalSerial短队列不含网络。HTTP必须生成DTO，body roundtrip/路径/ID/owner严格校验。

- createUpload：固定purpose/mime/size/sha256生成body和key，无码无图也能恢复metadata；真实mediaId仅从已持久成功回执绑定。
- content：固定真实mediaId、原图digest/长度、canonical wire body指纹及key；不存字节/base64/文件路径，重选同字节重建完全相同body才重试。不同图不能用旧key。
- createScan：固定真实mediaId和生成body/key，原content未确认不跨步；真实scanId来自成功回执。
- confirm：固定scanId、完整生成body/key和来源编辑代际，A未决期间新B独立保留；重放始终A，A结果不清B、不把匹配结果移给B、不触发B导航。

收到结果先typed安全持久再ACK；result_known支持纯本机ACK，无需原图/HTTP。新workspace、页面/账号/role/token/picker lease都捕获并检查，每次后续HTTP前再守卫，旧A只更新旧history，不抢新B。页面serial覆盖未落盘编辑，写失败提醒并保留输入。

未知原动作遇TTL/404保留unknown/unavailable，不改说原失败；学生明确新workspace后保留旧历史与文字，再选图开始新意图，不延长原图留存。GET当前观察独立保存，不据相等宣称原ACK；未确认不自动开始练习。

## 旧v1迁移

scan_draft.dart旧key内原文保留不改；合法文字可迁入新版bundle。旧keys没有完整body/digest，不包装成可精确prepared，更不能旧key配新body。旧mediaId/scanId仅历史关联或明确GET观察。未知版本/字段、坏数据、错owner/receipt均保留原文并阻断覆盖；新bundle存在后不从旧投影复活旧值。避免复制未知raw里的可疑图片字节，优先原key保留+引用与合法字段迁移。

## 文件所有权与验收

Store负责人只新增scan_command_store及独立tests；集成负责人新增scan_actions、修改scan_page及必要scan_draft兼容/Scan测试模拟；后端保持只读。主线程统一Flutter测试串行/构建、真实浏览器和全门禁。Parent当前固定Web/API不修改，验收期间不重建其静态资源。

先红后绿覆盖四动作成功丢响应、metadata无图恢复、content同图/异图、A/B编辑与写失败、已知结果离线ACK、TTL未知与新workspace/迟到、v1原文、picker晚到与切号。真实浏览器仅自编PNG/手工确认Mock，禁止读取原始试卷或连接OCR。

## 固定构建工程验收（2026-11-16）

家长/扫描合并构建Flutter608、analyze、Web/APK与适用后端/Dart/后台门禁已通过；实际浏览器15流程538项分两次均有通过证据：首轮其余14流程484/484，家长周报仅旧成功文案工具断言失败，查看截图及产品实现后修断言并同构建54/54复验。新增家长写恢复31/31、扫描恢复27/27均在首轮通过；不是单次538全绿。固定包、日志、精确scope见`var/writing-recovery-build-artifacts.json`。新包尚未真机安装，真实OCR/身份/生产就绪不在该阶段验收内。后台审核ABA及并发问题另已复现，下一包修复，不将本阶段通过外推为整个项目安全。
