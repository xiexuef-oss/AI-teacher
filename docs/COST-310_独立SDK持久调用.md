# COST-310 独立SDK显式持久调用

2026-11-17。本地工程切片，不关闭COST-301或全项目目标。未启用真实供应商、未选择计费/留存政策，没有新增SQL迁移或HTTP接口。

## 接线与使用

独立构造ModelGateway后，可信服务代码可以显式调用：

```python
gateway.bind_durable_invocations(invocation_store, secret=stable_secret)
response = gateway.invoke(request)
```

invocation_store复用既有InvocationStore、InvocationTransitions和已迁移数据库；绑定不建表、不创建后台任务、不发送请求。secret由服务配置提供且跨重启稳定，不在客户端生成或保存。不允许把同一网关重新绑定到其他store/secret。

request_id是本次逻辑调用的稳定键，重试和重启必须复用；trace_id可以随传输改变。request_id长度1～128、trace_id长度1～64，student_pseudonym沿用服务端生成的stu_加32位小写十六进制。SDK不是认证入口，调用方仍负责确认学生权限。

绑定后，旧invoke复用单次计划和SQL状态机：先持久化prepared，再原子提交dispatch_unknown、双范围请求计数和保守金额，才允许适配器发送；结算唯一审计和金额差额之后才交付正文。SDK不另外调用旧预算/审计sink，避免重复记账。复用共享暂停，IO后重新检查应用策略、供应商可用性、价格和请求上限。

应用启动已施加的durable/disabled策略优先，SDK绑定不能绕过它们；API换讲和文档OCR仍使用原有业务编排器。默认未绑定SDK保留原兼容行为，外调默认关闭。

## 恢复边界

内部metadata Schema追加v3：context_kind为sdk_request，按伪名和request_id生成HMAC域隔离身份及资源键，正文/图片/提示仅参与指纹，不写入元数据；不伪造会话、题目版本、文档或页码。v1/v2兼容。原成本只读清单能正确显示sdk_request，不新增恢复/删除HTTP入口。

- 同键但请求内容改变返回INVOCATION_CONFLICT，不重发、不新增计数。
- 已结算同键返回INVOCATION_ALREADY_SETTLED，不重发，也不假装恢复模型正文；调用方需要自行保存已交付业务结果。
- 已有可能发送记录返回INVOCATION_UNCERTAIN，不自动重试、退款或跨供应商回退。进程退出后仍保留保守预占和未知状态；已有操作员工具可只读核查。
- 存储故障不暴露底层异常；结算未确认时不交付正文。单次seam在发送之前阻止调用时，仍保守保留未知标记，不据此自动退款。

此切片只提供显式持久单次调用；没有声称旧SDK所有重试/多供应商行为已持久化，也没有提供正文恢复缓存、真实账单对账或外部发送exactly-once。未绑定旧入口的替换计划、持久多尝试、生产权限/存储和正式留存继续开放。

## 证据

首次八项因缺少绑定入口失败；另有一次业务策略切换和三项IO后配置变化红测，修复后通过。最终相关640项通过，包含SDK25项、真实退出子进程和隔离MySQL两项；既有换讲/OCR及变异运行器81项通过。真实进程以os._exit(23)退出后，父进程从新连接确认dispatch_unknown、两个非零预算桶及无审计，重启SDK无发送；真实MySQL同键并发只有一次发送/审计，不同伪名同键保持隔离。

最终21项新旧相关变异原始JUnit重新核验，340项矩阵不是本轮全跑；919份隔离快照验收时恢复且与主目录相同。首轮一项暂停变异因代码缩进调整而片段失效，未算抓到；同步片段后在新快照重跑相关21项全部捕获，保留原broken证据。Ruff和六个改动Python文件格式检查通过。

证据：`var/cost310-red.log`、`var/cost310-boundary-red.log`、`var/cost310-guard-red.log`、`var/cost310-final-related.log`、`var/cost310-business.log`、`var/cost310-mutation-coverage.json`、`var/cost310-r2-source-verification.json`。全库pytest终态2977通过、148项可选环境未配置跳过，退出0：`var/cost310-full-backend.log`及`var/cost310-full-backend-exit.json`；不把跳过算作真实环境通过。全量收集早于仅变异片段缩进修正，生产及测试代码相同，最终片段另由新快照21项补证。此SDK切片未改客户端，不重复Flutter/后台构建；后续本机导出增量另行验证。

后续[COST-311](COST-311_SDK逐尝试持久重试与回退.md)已扩展显式SDK的进程内逐尝试持久重试/回退；本文保留COST-310单次切片的历史边界和证据。跨进程确认失败续跑、结果交付与旧入口迁移仍未因此完成。
