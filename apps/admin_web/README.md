# admin_web（未实现）

内容审核后台（docs/03 的 P11 `/admin/review`，Vue 3）不在 ADR-006 的本地纵向切片范围内，这个目录目前只是占位。

对应的接口 `POST /api/v1/admin/questions/{question_id}/review` 已写入 `contracts/openapi.yaml`，状态为 `planned`，服务端返回 501。
