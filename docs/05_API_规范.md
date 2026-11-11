# 05 API 契约与错误约定

权威文件 `contracts/openapi.yaml`，本说明仅描述契约原则；客户端通过 OpenAPI 生成类型，禁止手写不一致请求对象。

## 1. 通用格式
- Base `/api/v1`；JSON UTF-8；UTC ISO-8601 `date-time`；UUID；分页 cursor；全局 `X-Request-Id`（服务端回显）。
- Bearer access_token，refresh 轮换；`Idempotency-Key` 必须用于提交、评分触发、草稿同步、教学下一步等非幂等动作；服务端保留去重记录。
- 成功资源返回 `data` 对象；错误 `{error:{code,message,details,request_id}}`；不得将栈信息返回用户。

## 2. 状态码
200 查询成功，201 新建，202 异步接受，400 参数错误，401 未认证，403 无权限，404 资源不存在，409 状态/版本冲突，413 载荷过大，422 字段语义不合法，429 速率限制，503 模型或依赖服务不可用。

## 3. 核心流程
1. `GET /tasks/today` → 今日任务（无数据时空数组）；`GET /questions/{id}` → 题目与结构；
2. `POST /sessions` → 会话；`POST /attempts` → 作答草稿；`PUT /attempts/{id}/draft` → `revision` 同步；
3. `POST /attempts/{id}/submit` → 记录答案并返回评估状态，若主观题异步评分只返回 `pending`；
4. `POST /tutor/sessions/{session_id}/next` → 事件 `hint/standard/fast/visual/ask`；
5. `GET /sessions/{session_id}/events` → 按 seq 恢复教学事件；
6. `POST /media/uploads` → 获取短期上传 URL；`POST /scans` → 启动 OCR；`GET /scans/{id}` → OCR 状态与可编辑题干；`POST /scans/{id}/confirm` → 用户确认题干；
7. `GET /reviews/due`、`POST /reviews/{id}/complete` → 复习调度；
8. `GET /progress/summary`、`GET /parents/students/{id}/weekly` → 学情与家长周报；`POST /admin/questions/{id}/review` → 审核决策。

## 4. 数据兼容规则
任何 JSON 字段删除或重命名视为破坏性变更；新字段默认可选，客户端忽略未知字段。AI 事件先经 JSON Schema 检验，失败不发送到 Flutter。`event.type=visual` 时还需严格验证模板与参数。所有请求的 student_id 只作为资源关联；权限来自 token 和持久授权。

## 5. 安全与限流
媒体大小限制、格式魔数检测、病毒扫描、对象私有存储。对 OCR 和模型请求实行单用户额度与重试上限；对账户等身份相关接口实行额外限流；日志不保留完整学生聊天或草稿原文，除非为教学目的经合法授权并有留存周期。
