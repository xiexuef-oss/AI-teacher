# DATA-303D 现存拍题文字导出

2026-11-17。本地工程验收完成；不关闭完整个人导出、删除或全项目目标。

## 范围

沿用学生专属 `GET /profile/learning-export`，增加可选、可为null的 `stored_scan_records`，没有新增接口或迁移。

- local返回本人仍保存的拍题记录：原图引用 `media_id`、原有效期 `expires_at`，以及已有Scan契约的文字、表达式、置信度、确认状态和匹配结果。
- 保存的过期文字仍可导出；不要求原图存活，也不续期、清理、确认或修改记录。已清理历史不能重建；空数组只表示当前无保存记录。
- dev/staging不查询本地原型表，明确返回null。旧文件缺失字段或null都表示未提供此范围，不代表从未拍题。
- 不包含原图字节、存储路径、未知payload字段或其他学生记录。media_id只是旧引用，不承诺图片存在或可读取。
- 家长仍不能调用学习记录导出；身份来自token。现存授权/邀请、摸底及学习内容继续保留各自范围说明。

复用现有10000条源记录、32MiB和一致读取快照。拍题记录计入共同上限，超限整次413；保存的身份、状态、布尔标记、置信度或必要字段无效时整次503 `export_unavailable`，不输出半份文件或原始坏数据。读取不调用会清理和commit的scan_service入口。

用Pydantic输出模型过滤未知字段；`exclude_defaults=True`省略唯一有默认值的空mock_notice，其他必需可空字段仍保留。没有为此新增存储、索引、队列、工厂或供应商调用。

## 已取得的证据

- 契约先行，新增API最初7项因功能缺失而失败，见 `var/data303d-api-red.log`；后续补齐并发快照和更严格坏数据用例。
- 最终相关API40项通过，简化前后均通过：`var/ponytail-export-before.log`、`var/ponytail-export-after.log`。原有测试断言未因简化而放宽；另一次72组序列化比较输出一致，并保留必需null字段。
- 实际MySQL/Redis的dev和staging范围测试2项通过，SQL观察器确认没有查询proto表：`var/data303d-managed.log`。
- 实际MySQL摸底/导出6项通过：`var/data303d-mysql-export.log`。两个旧测试的直接调用上下文由虚假的local改为实际staging，不通过表不存在时回退空结果来掩盖运行模式。
- Dart与TypeScript类型已由契约重新生成；147份实际响应样例及364个公式片段已导出：`var/data303d-fixtures.log`。
- Flutter全量682、Dart契约285、后台432及typecheck/check:api通过：`var/data303d-full-flutter.log`、`var/data303d-dart.log`、`var/data303d-admin*.log`；Dart analyze、Ruff及生成新鲜度通过。
- 新Web release的真实页面下载21/21通过：`var/data303d-browser.log`。自编图片和文字通过真实上传/确认API准备；导出通过页面实际下载，检查本人文字/表达式、原图引用与另一学生排除，并保留离线本机导出的验证。
- 已查看 `var/e2e-data303d-20261117/local_draft_export/screenshots/server-export-downloaded.png`，范围说明和下载提示正常。

- 后端全量2859项通过、137项因可选基础设施配置缺失跳过，进程已终态：`var/data303d-full-backend.log`。全量收集早于等价序列化简化，简化后另有40项相关回归、72组结果比较和以下19项变异验证；不将跳过记作真实基础设施通过。
- 新拍题10项、SQLite快照1项、现存授权/邀请5项及学习导出3项变异全部捕获，没有存活、无效、损坏、基线失败或未运行。每条原始JUnit重新分类核对，见 `var/data303d-mutation-coverage.json`。这是当前305目标中的19项相关检查，不将此前DATA-303C的295项证据冒充本次全矩阵重跑。
- 隔离副本906份文件已恢复，运行终态时与主区对应文件逐字节一致；随后仅更新说明文档，源代码、契约及样例未改变：`var/data303d-source-verification.json`。本轮所有检查进程已终态，恢复执行状态见 `var/data303d-status.json`。

## 仍未完成

后续DATA-303E已补本机未同步拍题文字/恢复信息的独立离线导出，见对应专篇。本轮不是完整扫描历史或完整个人备份。媒体完整归属枚举/字节导出、模型用量的本人关联和密钥轮换、本机未同步拍题及其他命令仍需补齐，见DATA-304。
真实身份注销、留存/备份/供应商处理条件仍待Q-03/Q-07。没有原卷导入、真实模型调用、真机/iPad安装或发布部署。
