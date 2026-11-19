# MEDIA-301B 本机 S3 兼容存储验证

2026-11-17。MEDIA-301 的独立工程切片；生产存储和 Q-07 仍未验收。

后续MEDIA-301C已补内部本人媒体只读枚举和真实两页遍历验证，见对应专篇；文件打包、学生端下载、S3全局快照及生产条件仍未完成。以下保留本切片的原验收记录。

## 范围

`services/api/tutor_api/s3_blob_store.py` 实现既有 `BlobStore` 协议，可通过现有
`create_app(..., media_store=store)` 显式注入 local 原型。没有新增自动选用 S3 的配置，
默认媒体仍关闭，显式开启的默认 local 媒体仍使用文件系统。dev/staging 的既有只读启动
检查仍仅接纳文件系统媒体，prod 仍拒绝启动。

客户端继续访问后端媒体 API，不持存储密钥、不获取供应商地址。原始图片与元数据存放在
同一个有界 JSON 对象中，字节用 Base64；不是两个需要协调提交的独立对象。

- 创建使用 `If-None-Match: *`，后续状态写入及过期清理使用读取时的 `ETag`。
- 每次写入有随机修订，避免相同内容覆盖后的 ETag 重用。冲突不覆盖、不自动换新请求。
- 构造时以唯一的 `_probe/` 私有键验证条件创建、陈旧覆盖和陈旧删除确实被拒绝；
  探针不含学生内容，失败拒绝使用该实例，不回退本地存储。探针不能代替真实并发验收。
- UUID、归属、用途、有效期、媒体大小、摘要、状态和编码均校验；重复 JSON 字段拒绝。
  远端响应长度先检查，读取有上限，流始终关闭。损坏或越权对象不返回字节。
- 删除使用不可读的墓碑；清理每次最多扫描 100 个对象，通过游标继续下一页。
  该游标只用于维护，不参与授权，不保证一次调用清空整个命名空间。

SDK 为可选依赖 `boto3`，锁定版本见 `uv.lock`。`local_s3_client` 只允许明确端口的
字面回环 IP、显式测试凭据，禁用代理和 SDK 自动重试，并阻止跳转到其他地址。
连接超时 3 秒、读取超时 15 秒；这是 socket 等待上限，不是整个操作的总截止时间。
15 秒来自本次真实八路同对象争用实测：冲突响应约按 1 秒间隔返回，最晚约 6 秒。
最初的 3 秒读取超时失败日志保留，不计为通过。

## HTTP 与恢复

契约先为媒体及拍题的 13 个操作补充 `503 ServiceUnavailable`；既有 409 继续使用。
统一错误处理返回 `storage_conflict`（409）或 `storage_unavailable`（503），固定中文说明、
空 details、禁止缓存，不返回 SDK 异常、端点或密钥。

冲突异常独立于 `ValueError`，避免被图片格式或摘要校验误报为 422。存储超时可能已有
外部写入结果，不能当成未执行；重试复用原 HTTP 幂等键。数据库确认失败后的未关联
对象不通过 API 暴露，沿用既有归属、数据库可见性及临时对象清理规则。

删除先提交数据库逻辑删除和成功回执，再处理对象墓碑；若后处理暂时失败，原键重试
重放已提交成功并继续后处理。逻辑删除期间 API 不再提供该图片。

后台媒体命令原本就保留未知结果，新增回归覆盖 409/503 后重建与原键重试。学生拍题
调整为：`409 storage_conflict` 与 503 保留原命令；其他业务 409、400、422 仍按明确
拒绝处理，404 仍标不可用。原图字节不写入命令日志，内容重试仍须重选同一原图。

## 验证证据

全部只使用自编字节、图片与本地 Mock 身份，未连接生产桶或真实供应商。

| 检查 | 当前证据 |
|---|---|
| S3 单元与真实服务 | `var/media301-s3-expanded.log`：31 单元 + 3 真实服务，共 34 通过 |
| 媒体/缓存/拍题及故障重试 API | `var/media301-s3-http-green.log`：40 通过；此前 10 条失败见 `*-http-red.log` |
| 真正服务重启 | `var/media301-s3-restart.json`：进程从 34256 到 11108，同一对象字节和 SHA-256 一致，验证探针已清理 |
| 定向变异 | `var/media301-s3-mutations/mutation-evidence-h9tkg_9r/summary.json`：6/6 捕获，无跳过/执行错误 |
| 源码恢复 | `var/media301-s3-source-verification.json`：隔离快照 368 文件全部恢复，关键源码与主工作区一致 |
| Dart 契约 | `var/media301-s3-dart.log`：276 通过；生成器检查当前最新 |
| 真实响应样例 | `var/media301-s3-fixtures.log`：140 份，包含实际 HTTP 409/503 错误响应 |
| 后台 | `var/media301-s3-admin-test.log`：431 通过，typecheck/check:api 通过 |
| 学生端新增恢复 | `var/media301-s3-scan-red.log`：四阶段 409 原先误拒绝；修复后四阶段 409/503 原键恢复已验证 |
| 整体门禁 | `var/media301-s3-full-backend.log`：2712 通过/123 可选环境跳过；`var/media301-s3-full-flutter.log`：648 通过；学生端 analyze 与全仓 Ruff 通过 |

真实测试使用 SeaweedFS 4.54 Windows amd64 官方发布包，SHA-256 与官方发布页核对：
`6d02c72bda207320b69236d34280d827bbedf6cef79d6c37da5b0db2299f28bc`。
程序、数据目录及随机测试凭据均在仓库外。已核实本次服务全部监听地址为 `127.0.0.1`；
验证结束后只停止本次创建且可执行文件路径匹配的服务进程，没有停止其他服务。

学生端首次全量的新增业务拒绝测试错误地从 active 读取已拒绝记录；该记录按既有设计
保留在历史、不会继续 active。仅修正为检查历史 rejected 且 active 为空，复跑全量
648 项通过，没有为测试修改业务拒绝规则。变异运行器后续只格式化三处引号，AST 与
已验证快照一致，运行器 35 项回归通过，记录在源码核对 JSON 和 `*-runner.log` 中。

可复跑检查：先自行启动隔离回环 S3 服务，在仓库外的 JSON 配置中提供
`test_only: true`、`endpoint`、`region`、`bucket`、`access_key`、`secret_key`，然后：

```powershell
uv sync --extra s3
$env:TUTOR_S3_BLOB_TEST_CONFIG = 'D:\独立测试目录\credentials.json'
uv run --extra s3 pytest tests/unit/test_s3_blob_store.py tests/integration/test_s3_blob_service.py -q
```

配置缺失时真实服务测试明确 skip，不能算真实通过。每例使用随机独立前缀，只清理自己
前缀内的对象；测试桶须预先存在。服务重启证据是此次额外执行的停进程/重新启动检查，
不伪称上述 pytest 命令会自动下载服务或重启操作系统进程。

## 仍待完成

生产供应商、地域、留存与删除策略、加密和访问策略、服务凭据管理与备份恢复须待
Q-07 和实际环境确定；未据此选定 SeaweedFS 为生产供应商。受控 MySQL/Redis/S3 联合
生命周期、生产只读启动探测和故障演练尚未实现或验收。尚无浏览器访问本机 S3 的
本轮联调、最新 APK 真机安装、手写笔或 iPad 验收，不关闭这些任务。

依据：
[AWS PutObject 条件参数](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html)、
[AWS DeleteObject 条件参数](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/delete_object.html)、
[SeaweedFS 条件操作说明](https://github.com/seaweedfs/seaweedfs/wiki/S3-Conditional-Operations)、
[SeaweedFS 4.54 官方发布](https://github.com/seaweedfs/seaweedfs/releases/tag/4.54)。
