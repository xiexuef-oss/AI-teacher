# SEC-303 HTTP资源与通用限流

状态：工程实现与专项验证中；默认关闭，生产发布护栏不变。

开启 `TUTOR_HTTP_LIMITS_ENABLED=true` 后，除GET `/api/v1/health`外，先限制应用实例内在途数量，再按ASGI peer及全局窗口检查，随后有上限地接收请求体；认证成功后按token关联的真实user_id检查账号及配置的路由额度。资源ID、请求体student_id和Bearer原文不作为账号身份。

配置项：

| 环境变量后缀（均加TUTOR_） | 默认值 | 口径 |
|---|---|---|
| HTTP_LIMIT_WINDOW_MODE / HTTP_LIMIT_WINDOW_SECONDS | fixed / 60 | 可选sliding；活动窗口配置改变时保守拒绝，不重置额度 |
| HTTP_LIMIT_PER_PEER / HTTP_LIMIT_PER_ACTOR / HTTP_LIMIT_GLOBAL | 120 / 120 / 1000 | 尝试次数，包含认证/业务拒绝及幂等重试，不是剩余额度公告 |
| HTTP_ROUTE_REQUESTS | `{}` | 认证路由单账号窗口额度，例如 `{"POST /scans":10,"GET /sessions/{session_id}":30}`；必须用契约METHOD及模板，拒绝具体资源ID和匿名路由 |
| HTTP_MAX_INFLIGHT | 16 | 每个应用实例内的在途上限，不是跨实例并发总数 |
| HTTP_MAX_BODY_BYTES | 25165824 | 实际接收字节上限；业务接口原有更小上限仍有效 |
| HTTP_BODY_TIMEOUT_SECONDS | 30 | 接收body的墙钟期限，不是端到端业务或Redis总时限 |

每层独立计数，后续层拒绝不退还前层的尝试次数。429 `rate_limited`附Retry-After秒数；413 `payload_too_large`、408 `request_timeout`在业务执行前返回，不写业务/幂等回执，客户端继续保留本机草稿并复用原键重试。请求ID及允许来源的CORS头同样保留。健康探针和本地CORS预检不消耗此通用额度；健康可用不等于所有外部依赖可用。

local默认使用进程内窗口；重启/多个实例不能共享内存额度。dev/staging启用时必须显式注入 `RedisHttpLimiter`，不能回退RAM；启动仅PING，不创建桶或消费额度。Redis适配器使用独立namespace，复用已验证的原子双桶窗口机制，peer/actor/route彼此隔离。Redis故障统一拒绝429，不把内部连接信息返回调用方。

注入的Redis客户端必须配置有限socket/connect timeout（有效值各不超过10秒）且 `retry=Retry(NoBackoff(), 0)`；阻塞连接池也须有限pool timeout，不接受可能无界等待连接锁的single-connection模式。缺失/无限超时或SDK重试会在构造时拒绝。这里不通过取消Python线程冒充终止Redis I/O；operator还须提供受控DNS/标准连接池和部署层健康监控。服务不会复制或打印Redis凭据，也不擅自选择端点。

## 信任及容量边界

- 应用不自行解析X-Forwarded-For。Uvicorn可以在应用之前改写ASGI peer，所以本机直连入口已显式 `proxy_headers=False`；非local反向代理必须由部署者明确可信代理与头清理规则。
- body按实际字节检查，不信Content-Length；使用bytearray累计，避免保留大量极小分片对象。完整body交下游时仍有一次bytes复制，JSON/解码/响应和解析器还有各自内存开销；这不是整进程硬内存上限。
- 只缓冲本次请求，不长期保存body。取消、超时、断开及异常都会释放本实例槽位；SDK操作仍受注入客户端的网络预算约束。
- 此功能不替代邀请码专项限流、COST-301预算、上传/存储总量控制、解析器隔离、入口代理和生产容量/SLA验收。

## 已执行证据

API先复现3项失败后实现；随后审查发现默认Uvicorn代理头可换peer桶、碎片缓冲开销、无界Redis等待三项，补5项红测试后修复。
路由额度先复现更换session_id可继续访问后，改为认证后的契约模板分桶。另先复现最终body帧过期仍进业务、无界连接池/single连接配置后补强。当前专项25项通过，包含真实Redis两个API实例共享窗口、8请求只放行1个、账号及路由共享额度，以及真实MySQL managed启动不消费配额。
实际ASGI生成408、413、429响应并经契约校验导出；尚待最终整合门禁、目标变异及新增图示浏览器验收，不将专项等同完整生产部署。
