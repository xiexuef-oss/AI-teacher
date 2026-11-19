# DRAFT-303C 家长授权恢复调查

状态：只读事实与待复现风险；尚未改契约或实现。先完成Profile包再实施家长包，Q-03仍为本地身份Mock，不新增监护关系推定。

## 当前事实

邀请生成、兑换与撤销均走run_idempotent；客户端三个动作仍用仅内存Map的PendingKeys，跨进程不保留原键。兑换输入及邀请展示未见本机持久化，不能据此声称已恢复。

services/api/tutor_api/services/parent_invite_security.py中derive_code用HMAC-SHA256后，对ALPHABET做10次divmod产生10字符，不是P-前缀或20位hex。DB保存邀请码SHA256摘要；成功回执剔除code，重放按固定密钥派生，并检查归属、过期、撤销、兑换和摘要，失效返回invite_response_expired。后续恢复不能把明文邀请码塞进通用journal、诊断或日志。

同一学生/家长的ParentStudentLink唯一行被重新授权复用，撤销后新邀请兑换清空revoked_at并改consent_at/created_at。当前撤销只按link_id、不带授权epoch。延迟且从未执行的旧撤销在新授权之后才到达，静态上无法区分授权代际；这是尚待行为复现的风险，不把已成功旧key的历史重放混同为再次执行。

页面没有请求发起账号代际检查；共享apiClientProvider的tokenProvider动态读取当前auth，捕获客户端对象本身不冻结身份。所有敏感恢复都需要固定原账号认证上下文和owner空间，并对晚到UI结果设置代际守卫。

## 下一步与验收

1. 先用自编账号复现旧撤销跨代，确认新授权不会被旧命令撤销；然后契约明确授权epoch/CAS与冲突，不用时间戳当版本。
2. 明确生成/兑换/撤销各自固定意图、最小可持久信息、有效期与敏感回执处理；不持久明文可兑换码，重入不能靠不可信GET相等宣称原动作ACK。
3. 本机失败保留原输入与键；切号不跨owner发送或污染页面；新授权不被历史回执覆盖。
4. 权限仍先角色后资源，跨账号404，撤销即时生效，家长仅已授权周汇总。
5. 契约/红测/实现/生成与样例，真实MySQL锁并发与幂等、隐私、目标变异、真实浏览器丢响应/重启/切号。外部真实身份与法定监护核验仍待负责人决策。

只读调查调用code_explorer与主线程核查；实际底层模型ID未知。没有读取原始试卷或向外部发送消息。

## 已取得真实API风险证据

主线程以全新隔离SQLite和本地Mock账号执行var/probe_parent_regrant_generation.py，var/parent-regrant-generation-probe.log确认：重新授权复用link ID，原来从未执行的旧撤销命令延迟到达返回200，家长可见学生数由1变0。不是旧成功key回执重放，也未触碰现有用户数据。风险现已行为复现，仍未修复。下一包将契约先行考虑每次grant/revoke状态变化递增authorization_revision，追加011候选；具体并发和敏感恢复设计仍在只读审查，未冻结真实身份决策。

生成侧也已行为复现：var/probe_parent_invite_generation.py与var/parent-invite-generation-probe.log以全新无端口TestClient账号验证，旧未执行生成intent晚到201会使另一端刚生成的邀请码兑换404，而晚到请求生成码可兑换。需要独立parent_invite_revision保护，不能仅靠Link代际或锁序声称解决。011和恢复测试草稿暂存var，Profile整合冻结解除前不修改运行源码。
