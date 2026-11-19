# DRAFT-303C Profile 保存恢复设计

状态：固定Profile Web/APK本地工程整合验收完成，原生安装/笔/读屏仍待设备。303B固定构建已443/443通过；本包后端/CAS/幂等/010及本机store初版已实现并有专项，客户端已将最初两条行为红测转绿，独立审查发现的编辑来源/确定拒绝/离线配置缺口继续先红后绿。随后继续家长敏感动作、扫描及后台入口，不据此关闭全项目目标。当前真实身份仍为显式本地Mock，不冻结Q-03或Q-07。

## 已核对基线

ProfileController.save先updateProfile，成功后state与_remember；没有先持久编辑或请求快照。_remember读取响应返回时的userIdProvider，缺少发起账号/代际保护，迟到A响应有污染B缓存的风险，尚未行为红测。

生成客户端updateProfile不暴露幂等键；PUT /profile契约仅RequestId，router直接调用profile_service.update_profile，未经过run_idempotent。同值PUT可以自然重发，不代表有固定指纹与成功回执；updated_at及地区变更审计仍可能变化。

资料更新整体替换可编辑字段，exam_year按既有保留/估算规则处理。有updated_at，无revision及更新前置条件，不能依靠时间戳检测跨端冲突。准确来源为core/data.dart、contracts/openapi.yaml、routers/profile.py、services/profile_service.py、models.StudentProfile；静态调查未替代行为验证。

## 实施不变式

- 新增/修改API先契约再红测；每个资料写动作有固定幂等键与完整生成类型body，成功回执、资料与审计同事务。重放原成功key先于当前版本校验，不把GET相等当未知intent成功。
- 采用单调revision进行CAS，不能以updated_at代替。新字段只用追加迁移，001–009不回写；MySQL与旧本地SQLite都要验证。请求缺key/版本的旧客户端如何明确拒绝及升级，须写清兼容边界并更新全部本地调用方，不能为了旧测试静默放开并发覆盖。
- 资料响应的revision需要兼容旧缓存缺字段：缺省表示未知，不当作0。离线可保留编辑，但不能拿未知旧缓存版本自动覆盖云端；初次创建与旧资料并发更新要用真实当前读/原子创建守门。
- 编辑、prepared body/key、来源版本和编辑代际先落本机；网络失败重试原快照。A请求期间的新编辑B独立保留，A回执与最新云端资料分别保存，不能把历史A回执覆盖B表单或较新云端资料。
- 冲突保留本机/云端双方并明确选择；采用本机或合并后是新intent及新版本条件，不改旧key/body。新冲突不能自动循环覆盖。
- 发起时捕获owner、账号代际、API认证上下文及缓存key；每次异步后校验是否仍可应用。不能在响应回来时临时读取B账号而写入A数据。原A结果可落A记录，不更新B状态，不在B身份下发送A请求。
- 不伪造question/session来复用学习journal。复用LocalSerial/规范化校验等底层能力，资料使用真正owner/profile范围；网络不放在短存储队列里，不虚称跨key/跨tab事务。
- 唯一本机资料bundle作为恢复权威；旧u/owner/profile缓存只作兼容投影，不能在投影写失败或重启时复活旧值覆盖新资料/编辑。未确认请求与双方冲突不得因摘要压缩被删除。

## 必须先取得的行为红测

1. 服务端真实保存后丢响应，重建仍原key/body，审计与revision只增加一次；不同body不得复用key。
2. 请求A挂起后编辑B，A返回/旧回执恢复不覆盖B；刷新最新资料不抹掉本机未保存改动。
3. A保存挂起→切到B账号→释放A响应，B状态及缓存完全不变；A原命令仍在A空间可恢复。
4. 两端读同revision，A先保存，B明确409且无副作用；双方资料留存，新intent按学生明确选择提交。
5. 相同时间戳的两次更新仍靠revision区分；真实MySQL RR等待后读到当前资料，首次创建并发不重复或绕过CAS。
6. 编辑/prepare/result/ack各落盘失败不得误报已保存或丢输入；未知格式/错owner保留原文，旧无revision缓存不能误当新建0。
7. 地区/考试年/教材/科目仍按现有规则与学生明确选择，历史Session快照不回写；家长没有资料写或学生内容读取入口。

验收：生成Dart/后台类型与真实样例、资料/归属/幂等/CAS及审计变异、相关全门禁、真实浏览器丢响应与切号、真机条件具备后独立验证。Model与调用成本治理、真实登录、授权题库、OCR及设备待办均不被本包替代。

## 实施方案已明确（后端修改仍等待303B固定回归退出）

ProfileUpdate新增必填严格非负整数expected_revision，新服务StudentProfile响应始终携带revision（OpenAPI可选以兼容旧缓存）；PUT必需幂等键。缺版本422、缺key400，升级所有本地调用方，不在通用ApiClient.request里自动补版本。测试可显式使用save_profile helper真实GET版本；CAS专测直接构造请求。冲突profile_revision_conflict返回本人expected_revision/server_revision/server_profile以保留双方。

GET原本不创建缺失Profile，缺行404；PUT同样保留404，不引入不明确的残缺库自动修复。Mock身份预建的空资料revision=0；010为已有真实行追加默认0，客户端只有真实GET取得的0才可作为CAS条件。旧缓存无字段独立解析为未知，不能为解码生成模型补0。

服务端锁顺序为稳定User→Profile当前读；MySQL锁定读须绕过RR旧快照与ORM缓存，SQLite先取得写锁再条件UPDATE。CAS成功后才写User显示名、审计与revision，全部与回执同事务。PrivateRoute确保成功/错误/重放均no-store。

Flutter新增独立ProfileEdit本机编辑类型，不依赖伪造版本构造ProfileUpdate；prepare时从已确认资料构造生成请求。每个owner/profile最多一个未决写，A未决时新编辑B保留。回执与cloud按revision单调合并，错误user_id拒绝。core/data.dart及Profile/Onboarding页面由集成负责人修改，store负责人仅新增文件，后端负责人仅Profile模块及Python调用点；生成类型和样例由主线程统一操作。

只读审查已以内存SQLite服务层复现A地区→B地区→重试A导致覆盖回A且审计增加；这是顺序服务层证据，尚非HTTP重放或真实MySQL并发结果。新controller/page独立红测已准备，待运行记录后再声称验证。

## 审查补充与本轮执行证据

响应revision在OpenAPI为可选非null整数，生成模型旧缓存缺失为null=未知；服务端Pydantic仍必填真实整数，PUT.expected_revision仍必填。此兼容修改避免升级后离线旧资料无法展示，不将未知缓存补0。真实130响应/364公式片段已重新导出，Dart221、Python契约237及后台197/类型/契约检查通过，尚不等于客户端最终验收。

独立审查的来源缺口必须修复：编辑不仅保存fields/generation，还要固定editBaseRevision；GET读到云端新revision不能悄悄把旧编辑重基。没有prepared命令也要显式保留双方并选择。已确认本机A成功回执与A期间续改B的来源推进单独处理，不允许旧A覆盖更新的他端C。确定无副作用的422要记拒绝，纠正后由新intent保存，网络/5xx仍为未知原命令。真实离线重启要有已验证LaunchConfig缓存，不能只在widget覆盖配置假装完成。对应三条行为红测var/profile_review_red.log已取证，正在修复。

后端80专项、347相关回归及16最终Profile API通过；真实MySQL010旧行升级/noop、RR当前读、同owner竞争，以及回执finish失败事务回滚已覆盖。初版store13通过；当前来源版本补强后会再验证。根级完整后端/真实infra与不可变快照全变异已启动，句柄及日志见var/draft303c-live-jobs.json，未见终态不标通过。

## 当前固定构建验证

完整Flutter564通过、dart analyze干净，Web release/debug APK构建成功；APK冻结候选var/artifacts/draft303c/student-debug-7d8f131e0bab.apk，207798967字节、SHA256 7d8f131e0babf540f3f1bb0b030fdfad7d98c60f90f245f3c332013ccc1d90d0。字体UTF8重跑成功且前后SHA256逐字节相同，107字体/工具测试通过；没有安装真机。

完整后端R2为2291通过、102明确未配置skip；单独真实infra103通过零skip；Ruff及生成检查通过。首轮完整后端唯一失败是旧隐私验证请求缺新required版本造成错误字段顺序改变，补真实GET版本后33相关通过并完整R2重跑成功，未降低隐私断言。

真实五链专项R2 37/37通过（var/draft303c-browser-profile-r2.log），覆盖原key/body丢响应重放+新B、真实409、无prepared编辑GET来源冲突、API离线完整重启、切身份迟到回执。R1 31/37的六处失败来自直接读取Flutter未聚焦语义输入代理；截图与实际保存均正确，R2通过正常UI点击聚焦读取原生editor，并保留before_focus/after_focus/字段属性JSON。没有修改DOM值或以存储冒充UI。

当前全部13流程回归句柄89955，日志var/draft303c-browser-all-final.log；独立704文件快照完整变异句柄58391仍运行。两项尚未取得终态，不标工程整体验收完成。

## 最终工程验收结论

全部13真实浏览器流程同次480/480，原句柄89955 exit0；配套门禁及APK见var/draft303c-build-artifacts.json。完整变异原句柄58391 exit1的原因是唯一旧foundation验证测试未补required expected_revision而基线失败：完整运行211 caught/1 preflight_failed，其余0；修正后独立快照回环限制目标1/1 caught。主线程实际审计303份运行目录、10417条JUnit testcase及两份704文件快照逐字节恢复，合计212 distinct目标覆盖；不称一次完整212全绿。审计var/draft303c-mutation-source-audit.json；tester角色未执行审计，不能将等待答复当验证。

后续Parent契约/011/客户端开发已开始，固定Profile工程证据不冒称覆盖这些新代码；整个项目目标继续active。
