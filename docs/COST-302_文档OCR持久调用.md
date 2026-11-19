# COST-302 本地文档 OCR 持久调用

状态：2026-11-17，显式启用的本地切片已实现，合入后相关回归128项、真实MySQL两组并发及6项专项变异通过。生产文档任务存储、真实供应商账单与授权样本评测仍未完成，不能据此关闭全项目或 COST-301。

## 上下文与兼容

`contracts/model_invocation.schema.json` 保留 v1 的学生会话／题目版本记录，增加 v2 的 `document_ocr`、资源摘要、文件摘要和页号。v2 禁止伪造 `session_digest`、`question_version`，两种记录都禁止保存提示、图片、响应和密钥。`InvocationStore` 复用既有 014 表，旧列 `active_session_digest` 在 v2 存放带独立命名域的资源摘要，不回写迁移。

资源和调用 ID 从稳定服务端密钥、创建者、任务、文件与页号派生，不随工作器租约或 HTTP 请求 ID 改变；请求指纹包括最终消息与系统提示。预算沿用创建者的服务端去标识账户桶及平台桶，不能据此给该账户增加学生权限。

## 调用与恢复

应用先初始化持久调用存储，再把它注入文档工作器。默认 `durable_model_invocations_enabled=false` 和 `import_ocr_mode=disabled` 不变；启用持久调用仍须稳定去标识密钥及显式 SQL 回执。managed 环境继续不启用本地 proto 文档工作器。

准备调用只选择一个候选，不消费额度或发送。真正发送前，在同一短事务校验任务租约与文件归属／摘要、插入本地逐页发送标记、写共享 dispatch 状态并预占账户／平台请求数与估算金额。任一额度拒绝全部回滚，再取消未发送意图；没有伪造审计、单边扣费或已发送标记。

事务结束后使用 `invoke_single_attempt`，不走旧 invoke 的自动重试、回退和独立结算。得到响应后独立幂等写审计／金额差额；未知用量不退回预占，超预占时不应用模型正文。页面结果、本地页完成标记和共享 applied 状态同事务提交，写入失败全部回滚。

恢复时复用已完成且指纹一致的页；结果未落库时转人工核对，不重新发模型请求。恢复方持有新租约，按任务→意图锁序重读当前状态：未知发送关闭为 closed_unknown，审计已结算但结果丢失则安全结束为 applied；不从旧快照把已结算状态倒退为 unknown。迟到审计仍能幂等记账，不重新应用识别正文。取消／接管后的迟到结果保留审计，业务意图转 stale、释放活动资源槽，页面不写入。

本地页标记随工作区到期删除，正文只存在原有有界临时文件工作区。共享审计和摘要的生产留存仍待 Q-07，数据库记录删除不代表磁盘安全擦除。

## 验证与边界

- v2 存储接入先取得两项 KeyError 红测，修复后共享状态机、契约、存储与辅导兼容检查42项通过（`var/document-invocation-store-red.log`、`var/document-invocation-store-green.log`）。
- 真实隔离 MySQL 的 v1/v2 两组8线程准备、dispatch及审计重放测试通过，无跳过（`var/document-durable-mysql-final.log`）。此证据覆盖共享存储，不冒称 proto 文档工作器已在生产 MySQL 运行。
- 工作器接线先取得5项功能缺失失败；启动依赖和已应用审计重放也先取得2项失败，再修复。后续发送丢失、页面事务丢失、迟到审计、取消与接管的测试见 `tests/api/test_document_durable_ocr.py`。
- 迟到结算竞争在隔离目录复现：旧快照随后遇到已结算状态，错误地把文件标为失败；持锁重读修复后恢复相关16项通过（`var/document-ocr-settlement-race-red.log`、`var/document-ocr-settlement-race-green.log`），修复已合入。
- 最终合入回归128项通过（`var/document-durable-integrated-regression.log`），6/6 OCR变异捕获、无skip或无效运行（`var/document-durable-final-mutations/mutation-evidence-t9tel718/summary.json`）；恢复后的隔离快照820个文件与主工作区一致（`var/document-durable-mutation-restore-verification.json`），Ruff通过（`var/document-durable-final-ruff.log`）。
- 全量后端仍在运行（会话23157，`var/document-durable-full-backend.log`），开始时未含最后的竞争修复；此前220变异在另一旧快照运行（会话78019）。不能把这些旧快照结果作为当前完整226项变异／全量源码门禁。

所有模型结果均由自编 ScriptedProvider 返回，测试域名为 `.invalid`，未调用真实供应商。持久超预占事件与共享暂停后续已由COST-303实现（默认仅记录）；旧入口、真实价格与图片计费、服务商协议／地域、外部告警投递、正式队列／对象存储、授权OCR评测仍在原计划内。
