# 05 API 契约与错误约定

权威文件 `contracts/openapi.yaml`，本说明仅描述契约原则；客户端通过 OpenAPI 生成类型，禁止手写不一致请求对象。

## 1. 通用格式
- Base `/api/v1`；JSON UTF-8；UTC ISO-8601 `date-time`；UUID；分页 cursor；全局 `X-Request-Id`（服务端回显）。
- Bearer access_token，refresh 轮换；`Idempotency-Key` 必须用于提交、评分触发、草稿同步、教学下一步等非幂等动作；服务端保留去重记录。
- 成功资源返回 `data` 对象；错误 `{error:{code,message,details,request_id}}`；不得将栈信息返回用户。

## 2. 状态码
200 查询成功，201 新建，202 异步接受，400 参数错误，401 未认证，403 无权限，404 资源不存在，408 接收请求体超时，409 状态/版本冲突，413 载荷过大，422 字段语义不合法，429 速率限制，503 模型或依赖服务不可用。

## 3. 核心流程
1. `GET /tasks/today` → 今日任务（无数据时空数组）；`GET /questions/{id}` → 题目与结构；
2. `POST /sessions` → 会话；`POST /attempts` → 作答草稿；`PUT /attempts/{id}/draft` → `revision` 同步；
3. `POST /attempts/{id}/submit` → 记录答案并返回评估状态；`written/experiment/proof` 一律 `pending`，不自动判对错，提交后对照参考材料自查；
4. `POST /tutor/sessions/{session_id}/next` → 事件 `hint/standard/fast/visual/ask`；
5. `GET /sessions/{session_id}/events` → 按 seq 恢复教学事件；
6. 学生通过 `POST /scans/uploads` 获取专用临时图片上传地址，再 `POST /scans`、`GET /scans/{id}`、`POST /scans/{id}/confirm`；当前仅显式开启的本地Mock/手工确认，不实际OCR，不确认就不匹配题目；审核附件上传另用 `/media/uploads`，权限不混用；
7. `GET /reviews/due`、`POST /reviews/{id}/complete` → 复习调度；
8. `GET /progress/summary`、`GET /parents/students/{id}/weekly` → 学情与家长周报；`POST /admin/questions/{id}/review` → 审核决策。

创建会话可传可选、非null的整数 `expected_question_version`（≥1）。仅允许当前已发布版本相同才创建，否则409 `question_version_conflict`，不创建会话；旧客户端省略时保持当前版本行为。已成功请求同键重放仍返回原会话，即使后来发布新版。省略新字段时保留旧请求规范体与历史幂等指纹。

`GET /sessions/{id}/question` 返回本人会话的固定版本题面，不能携带答案；`GET /questions/{id}/drafts` 仅列本人未提交草稿元数据。冲突时可明确调用 `POST /attempts/{id}/copies` 在同session保留新副本，源稿不覆盖、不自动提交；`attempt_no` 是创建次序，`submission_no` 才是实际提交次序。

## 4. 数据兼容规则
任何 JSON 字段删除或重命名视为破坏性变更；新字段默认可选，客户端忽略未知字段。AI 事件先经 JSON Schema 检验，失败不发送到 Flutter。`event.type=visual` 时还需严格验证模板与参数。所有请求的 student_id 只作为资源关联；权限来自 token 和持久授权。

## 5. 安全与限流

通用HTTP限流及请求体资源门控见[SEC-303](SEC-303_HTTP资源与通用限流.md)，默认关闭；启用时除健康探针外可在业务前返回契约声明的408/413/429，保留请求ID与本机草稿重试语义。原有专项限制仍生效。
媒体大小限制、格式魔数检测、病毒扫描、对象私有存储。对 OCR 和模型请求实行单用户额度与重试上限；对账户等身份相关接口实行额外限流；日志不保留完整学生聊天或草稿原文，除非为教学目的经合法授权并有留存周期。
