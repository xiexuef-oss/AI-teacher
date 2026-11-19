# MEDIA-301D 本人媒体ZIP下载

2026-11-17。本地工程验收完成；完整个人备份/删除、生产存储和最新真机验收仍未完成，不关闭全项目目标。

同日Ponytail精简：文件数直接取写入清单前的ZIP条目数，删除手动计数状态，归属、完整性、限额和异常门控不变。新旧实现27组状态组合的响应及ZIP字节相同且存储不变；相关API/枚举/S3单元回归124项、全库Ruff及本文件格式检查通过。记录见`var/ponytail-media-export-focused.log`和可重跑的`var/ponytail-media-export-equivalence.py`。本轮全库pytest主动停止，未计为通过；未改契约、客户端或部署状态。

## 使用

“我的 → 隐私与数据 → 下载当前媒体ZIP”。需联网且显式启用本地媒体存储；默认未启用或dev/staging明确501，不生成空文件冒称没有图片。资料加载失败页仍可滚动找到入口。取消、失败或重复点击均不删除/重试原操作。

沿用学生token归属和角色检查，家长/审核员403，角色检查先于参数和存储；不接受owner/student_id或筛选参数。新GET `/profile/media-export`只读、禁止缓存，不创建服务器导出文件。

## 档案范围

只包含本人当前仍有效的ocr_source/handwriting用途。排除审核附件（即使归属相同）、过期/删除对象、已清理历史、本机未上传原图、凭据、存储路径/键及上传地址。

当前正常学生流程主要产生拍题原图；本切片没有新增手写Blob上传。作答和笔迹坐标仍从原学习记录或本机练习JSON导出，不会在ZIP中自动转换成图片。

ZIP包含manifest.json和受控UUID文件名，清单及对象结构已在OpenAPI的StudentMediaArchiveManifest/StudentMediaArchiveObject定义。使用标准库zipfile，不新增打包依赖或二进制传输层；JSON返回archive_base64、大小及SHA-256，由生成客户端读取、校验大小/摘要/ZIP标记后主动保存。

- reserved仅列not_uploaded，无文件名或伪造图片。
- pending手写仅列awaiting_confirmation；pending拍题沿用既有临时读取规则，ready按既有受控读取。
- 每次读验重新检查归属/有效期、数据大小及摘要。异常元数据、重复ID、读取失败或变动整次503，不输出半份档案或底层错误。
- 源扫描上限1000，档案最多16MiB；写文件之前以及包含清单/ZIP开销的最终大小分别校验。超限整次413，不截断、不清理、不续期。
- ZIP清单自包含范围、状态和排除项；对象数为0时客户端明确提示而不交付文件，不能推断从未上传。

复用MEDIA-301C的有限额归属遍历及元数据校验器、原有媒体读取、文件保存/取消反馈和身份切换保护。客户端不会在切换后或切回同一身份时交付旧请求结果，不把原图持久写入草稿缓存。

history_complete和consistent_snapshot固定false。S3分页没有跨对象一致快照，不能据此承诺某一时刻的所有媒体或完整历史；导出期间新增内容可能不包含。生产完整备份仍需快照/写入隔离或持久归属索引，以及Q-03/Q-07冻结。

## 验证证据

- 契约先行，首次10项因缺少接口/实现失败：`var/media301d-api-red.log`。追加重复ID和异常元数据失败用例后，分别补重名拦截、复用已有校验器，未另造一套字段校验：`var/media301d-boundary-red.log`、`var/media301d-metadata-red.log`。
- 最终媒体导出17项通过，含角色、不可用/真实空范围、本人文件、预留/待确认状态、审核用途排除、坏数据/读取失败、重验过期、源/文件/清单大小限制：`var/media301d-api-after-probe.log`。契约/API/联调工具443项通过的收集早于最后一项写入探针，最终由全量和17项专项补齐。
- 148份真实响应样例及364个公式片段重新导出；Dart/TypeScript类型由契约生成：`var/media301d-fixtures-final.log`。没有手改生成代码。
- 新UI15项、相关UI37项通过；初次测试中的契约导入、说明/按钮重复匹配和错误页滚动选择器已修正，没有修改产品权限来迎合测试：`var/media301d-ui-green-r3.log`。
- Flutter全量711、Dart契约286、后台432及typecheck/check:api通过：`var/media301d-full-flutter.log`、`var/media301d-dart.log`、`var/media301d-admin*.log`；analyze无问题，Ruff/格式/生成新鲜度通过。
- 实际MySQL/Redis的dev/staging两项通过，不读取本地媒体且明确501：`var/media301d-managed.log`。
- 实际本机S3五项通过，含103个本人对象跨页遍历以及新增HTTP ZIP用例；解包比对本人PNG字节，排除其他归属/内部链接，前后ETag不变：`var/media301d-real-s3.log`。只用回环测试服务/自编图像，已核对可执行文件路径并停止本次测试进程。
- 最终新Web构建的真实下载34/34：`var/media301d-browser-final.log`，产物在 `var/e2e-media301d-final-20261117/local_draft_export/`。检查实际.zip后缀、大小/摘要、清单契约语义、本人原图与引用、另一学生/凭据排除、无写操作/本机改写、离线明确失败；保留原练习、拍题和服务端学习记录导出检查。
- 已查看最终offline-export-downloaded.png，四个入口、范围说明及离线反馈显示正常。
- 后端全量2929通过、141项可选环境未配置跳过，退出0：`var/media301d-full-backend.log`、`var/media301d-backend-exit.json`。全量收集早于测试探针修正，生产实现/契约/样例未变；修正后17项及最终变异重新运行，差异仅tests/api/test_scans.py，见 `var/media301d-probe-revision.json`。skip不当作真实基础设施通过。
- 首轮后端保护11捕获/1无效，写入限制探针在ASGI回调里抛断言导致额外夹具清理错误，未计为捕获；原记录保留。改为记录调用后在测试层断言，保护要求不变。
- 最终新快照29/29相关后端变异全部捕获：新MediaArchive12、枚举10、S3既有6及需要更新片段定位的授权历史1。逐条原始基线/失败JUnit重新分类核对，见 `var/media301d-mutation-coverage.json`。当前327目标矩阵只重跑这29项，不将历史295项或首轮无效项冒称本轮全矩阵通过。
- Flutter五项归属、摘要、大小、范围、身份激活保护全部捕获；最终15项基线和原始断言日志核对，279份源码/配置/样例恢复：`var/media301d-ui-mutations/summary.json`。
- 后端最终隔离快照914份文件恢复，主区程序/契约/样例一致；后续文档更新单列：`var/media301d-r2-source-verification.json`。全部检查已终态，恢复执行状态见 `var/media301d-status.json`。

## 仍待

最新Android测试包/USB与手写笔/iPad验收、S3全局快照/持久索引、生产联合运行/留存、其他本机恢复命令及模型用量范围、完整删除仍待。没有导入原卷、启用真实OCR/供应商、替负责人冻结政策或发布部署。
