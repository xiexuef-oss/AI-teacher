# CONTENT-303 来源定位与引用

## A：正式题版本来源快照

2026-11-16实现并整合。文档候选保存的文件/页定位在批量建题时重新核对actor、job、file和页序，随正式QuestionVersion同事务保存provenance_json。013只追加nullable JSON列，既有001–012不改；旧SQLite通过独立启动升级补列，原行保持null。

响应Question、AdminQuestionDetail和AdminVersionSnapshot提供可选nullable provenance。仅包含当时来源声明快照、文件SHA-256、文件格式、页/片段序号、块序声明与派生父版本；不含原文、文件名、长期job/file外键或原文件访问地址。PDF物理页、Word有序片段、JSON片段与图片页分开标识。块序不代表已经验证的精确文本位置，SHA或来源标签不代表版权授权。

临时任务清理不删除正式版本的来源元数据，也不延长原文件期限。编辑新版本从实际上一版本深拷贝已有来源，标记derived_unverified及parent_version；旧版本null不从latest或相似文本回填。学生既有session与审核历史读取各自实际版本。

审核后台当前题及对比页显示对应快照。左右来源标题使用实际snapshot.version，请求代次阻止迟到响应错标版本；不提供原文件下载或预览入口。无记录明确显示暂无导入定位。

验证：受影响后端135、真实SQLite7、真实MySQL迁移/运行10、UI专项9及实际全后台412、Dart224、Flutter608与静态分析通过；实际浏览器8项、1份safe JSON禁敏感字段0命中，原75413终态0。133响应及364公式样例已导出，包含非空来源、派生版本与旧快照真实响应。实际后端全量原23759已终态0：2421通过、109项未配置基础设施而跳过；本功能真实MySQL10项另行执行通过。

## B：固定版本内容引用（已实现，验收尾项保留）

目标保留完整span引用：服务端固定question/version的白名单内容块、文本摘要和明确Unicode计数的范围，客户端验证版本/摘要/区间后回看，数学公式不因截断破坏。导入来源声明与题面内容引用分开，不能从metadata_only制造已清理原卷的引用。

引用必须遵守独立作答防泄题、已揭示提示、主观题提交后自查以及完整解析used_solution门控。模型给出的任意URL、其他题目ID或未授权内容不得成为引用权威。旧无引用事件保持兼容，真实厂商模型不是实现前提。

当前已冻结引用契约并生成Dart/TypeScript，服务端与学生端接线实施中；尚未完成整个功能包验收。Q-05版权审校、Q-07生产留存/条款仍未据工程功能视为已冻结。

## B实施契约（2026-11-16冻结并实施中）

- ContentSpanRef：block_id、block_sha256、start、end。范围为Unicode codepoint左闭右开，0 <= start < end <= 原文runes数；摘要为DB完整block原字符串UTF-8，不trim/normalize/改换行。
- ResolvedContentSpan：上面四项加block_text、label；事件信封新增可选references，question/version继承服务端event.meta固定session身份，不引入任意文件/版本查询。
- 教学材料新增可选teaching.reference_links（target_block_id、source_span），由import/edit验证候选版本、人工审核标安全提示条件。无注记不向模型开放题面任意选区；旧无refs事件仍兼容。
- 来源目录由服务端固定QuestionVersion及其solutions/rubric构建，不接受模型URL/JSON Pointer或客户端目录。前独立作答保守只可用审核标安全的已见题面条件范围；不引用选项暗示、答案、未来hint。提交并不自动解锁全部隐藏块，完整解析仍需used_solution，主观rubric/reference_cells/reference_steps仍需实际提交及SUBJECTIVE_MODES。
- 网关只提议ContentSpanRef，API按真实DB目录解析ResolvedContentSpan；先验ID/hash/范围，再对实际选区及上下文检查泄题，避免把hash数字当作答案而误拒，也不能跳过整个引用子树。模型调用前后目录权限取交集，旧请求不得利用状态变化扩权。
- Gateway DTO/validation/prompts/Mock同步更新，prompt版本更新；一条审核hint、一条Mock改讲、一条完整解析必须产生非空、非整块的实际span，不能用空字段交付。
- Flutter公共事件卡增加查看依据；验证session/question/version、白名单、UTF-8 SHA与runes范围后回看完整context并强调普通选区。公式保持完整MathText，不截断TeX；选区在公式内时完整渲染公式并显示精确原文选段，不假称已高亮公式子结构。任何不匹配显示引用不可用，不相似重定位。已保存事件断网可回看。
- 注记存现有teaching_json，授权快照存event_json，预计不新增迁移。编辑内容改变导致原hash/范围失效必须明确清除或重审，不自动按新文字补坐标。后台编辑器必须保留注记，避免普通编辑静默丢失。
- 契约先同时更新OpenAPI、tutor_event.schema、Gateway形状；再生成Dart/TS与中文/emoji/组合字符/换行/公式的真实样例。重点验证越界、小数/bool、错hash、隐藏块、v1固定/v2发布、调用期间状态变化、损坏缓存降级及一条真实browser点击引用闭环。

此草案保留完整span目标；元数据A不替代B。实际字段上限和现有函数接线在实施前核对，Q05/Q07及评分/高风险实验边界不改变。

## 当前验收边界（2026-11-16补录）

离线恢复补充已完成：控制器仅从当前账号、可信attempt工作区的已确认resource view恢复教学事件，并核验session、题目版本、origin与review归属；缓存不冒充远程session，不使断网动作成功。回归先红后绿，完整控制器141通过，dart analyze无问题（`var/citation-offline-controller-r2.log`、`var/citation-offline-analyze-r2.log`）。最新release Web实际浏览器39/39通过，`var/citation-offline-browser.log`，产物`var/e2e-content303b-20261116T153405Z-d28f2933`；实际覆盖API阻断后页面重新载入展开依据、联网重新载入后提交并点击还是不懂的审核换讲引用。下述r6缺口已据本次证据修复；整机无网络且静态资源未缓存的首次启动不在Web API离线验收范围。全项目目标及生产、设备任务继续保持未完成。

固定版本引用已接通契约、网关提议校验、API授权解析、后台注记编辑与Flutter依据展示。实际release Web与隔离API浏览器记录为`var/content303b-browser-r9.log`，34/34通过，截图和安全证据在`var/e2e-content303b-20261116T150024Z-97a24af2`。覆盖审核提示、明确确认后的常规解析、在线刷新回放，以及页面已载入后阻断API仍可展开依据。

该记录不证明离线冷启动恢复：r6阻断API后重新载入，依据按钮未恢复；启动恢复目前依赖远程session/attempt读取。也不证明换种讲法的页面入口闭环：r4/r5所选作答阶段没有该按钮。后续需完成可信本机事件只读恢复及相应实际页面验收，不能用已载入页面的内存回看替代“已保存事件断网可回看”的完整验收。此前宣布B整体完成的口径据此收窄为已实现主要链路、两项验收待完成。下面旧实施进展保留为历史记录。

实施进展：引用/已解析引用/审核注记已写入OpenAPI与教学事件Schema，Dart/TS已生成；Gateway新增24项专项及旧验证/Mock合计64项通过，后台编辑往返与旧编辑合计53项通过、strict通过，契约80项通过。Flutter新增11项先红后绿，Dart损坏引用解码11项先红后绿（另补版本小数测试待跑）。坏引用局部标不可用并保留正文；不把小数坐标截为整数。API权限、固定版本及真实非空事件接线仍在开发；尚未导出本功能真实响应、未跑最终全门禁或browser，不计B完成。
