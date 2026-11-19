# DRAFT-303C 家长授权与敏感命令恢复设计

状态：实施中，尚未验收。Profile固定构建全部13流程480/480完成后解除运行源码锁；Profile旧快照完整变异及审计继续独立运行，不能把旧产物当作本包验证。Q-03/Q-07保持未冻结，仅既有本地Mock授权原型。

## 依据与契约

调查专篇及两份var/parent-*generation-probe.log已确认：旧未执行撤销会撤销新授权；旧未执行生成会废掉较新邀请码。单纯幂等键、同link ID和串行锁不足以区分意图代际。

追加011候选：ParentStudentLink.authorization_revision BIGINT默认1，首次创建1、撤销/重新授权均递增；StudentProfile.parent_invite_revision BIGINT默认0，仅生成新邀请成功递增，与资料revision独立。旧行只是迁移基线，不伪造历史变化次数。001–010不改，010 SHA256为9fa1a42ed03f7057b4dd1cca91fdc12d089fa36cd2b1e88e6ae3cfcd65b45476。

生成请求ParentInviteCreate.expected_parent_invite_revision必填严格整数>=0，撤销请求ParentLinkRevoke.expected_authorization_revision必填严格整数>=1。响应新增对应版本可选非null以兼容历史回执/缓存缺字段；新服务始终真实输出，缺值unknown不补0/1。旧None-body明确拒绝升级，不把新版body折叠为None指纹；旧客户端内存在途请求可能中断，不能伪称无缝恢复。

历史成功key重放在CAS之前，不能重撤销新代或再生成新邀请。角色先于资源查询，跨账号404，本人stale409仅当前本人非敏感摘要；成功/错误/重放均no-store。写锁统一稳定学生User→Profile→Invite→Link，兑换先摘要定位、取得学生锁后重新锁定验证邀请码；MySQL当前读刷新身份映射，SQLite先取得写锁。更新/邀请码消费/审计/回执原子。

## 本机协议

按owner与role独立单bundle，短LocalSerial不包含网络；随机固定key及生成DTO body先落盘，记录source版本而不在GET之后偷偷重基。一个active lane，历史未知记录独立保留。发起认证token固定，每次异步前后检查账号和页面代际；晚到结果仅进原历史，不覆盖新输入或新账号。

生成返回的邀请码只能在内存短时展示；持久结果使用allowlist剥除code/token，成功落盘后才ACK与展示。不将完整API对象随手序列化到journal。重启可以原key/body重放，只有仍有效的原邀请允许重现码；失效明确拒绝，学生确认后新intent按当前版本生成，不自动废掉他端新码。

兑换首次发送前规范化为十位大写ASCII码，幂等指纹基于实际canonical wire body。只存随机salt、body指纹、key与阶段，不存码或可兑换token。重启需要重输匹配原码再以原key/body恢复，不能宣称无secret全自动重放。丢码可明确“保留未知记录，使用新邀请码”，仅放弃本机自动重试，不声称服务器已取消/失败；旧结果仍可能晚到，旧记录不抢新lane。GET当前绑定列表不是原intent ACK；already_linked只拒绝新动作，学生授权与撤销仍由学生发起。

当前授权与历史成功回执分别保存；较旧版本不回退当前状态，legacy无版本不冒充当前证明。明确拒绝允许纠正后新intent，网络/5xx保留未知。各落盘失败保留内存输入；冲突选择和页面导航同时检查持久代际与页面未落盘编辑serial。

## 验证与所有权

后端负责人仅Parent契约/服务/011/升级/Python调用方；store负责人仅新增journal与独立测试；集成负责人仅家长区/首页/控制器及Parent测试模拟。主线程统一生成Dart/admin类型、真实样例、整体验收与真实浏览器。Flutter测试严格串行。

先行为红测再实现：旧撤销/生成跨代、旧成功回执不碰新代、同key异body、归属/角色、MySQL RR/并发/回滚、旧SQLite与011、父母原始码不落盘、相同码规范化重输、新码不复用旧key、失码明确unknown归档、账号切换及存储失败。之后目标变异、适用全门禁、真实浏览器与固定构建；不因原型通过关闭AUTH-301/302或真机验收。

## 当前证据（未整体验收）

后端193相关、SQLite18及完整2335通过/105未配置skip；单独真实infra106通过零skip；Dart221、后台197/类型/契约检查、共享规范化Python14与Dartfixture使用通过。5新增+既有跨学生撤销目标6/6捕获，9份运行产物/112 JUnit及715文件恢复由主线程审计，见var/parent-recovery-mutation-source-audit.json；不声称一次完整217变异。

独立只读审查发现current刷新、本地result_known ACK与失效码展示三项并已先有效红测后修复；store15、页面相关91通过。真实本机历史确认不联网、不要求原码、不把GET当ACK。完整Flutter候选587/analyze/Web/APK已通过，但“不可展示旧码返回null后同页下一次明确生成”边界正补最后行为测试，若修源须复建，候选不能冒称覆盖后续变更。新的parent_write_recovery第14流程已注册，真实执行尚未开始。

先前一次页面测试与主线程真实样例导出临时清目录重叠，PathNotFound不算产品失败；主线程已导出完成并改为串行交接，后续有效测试91通过。旧日志保留，不将编译/收集错误或此类运行冲突计为行为红测。

## 固定构建工程验收（2026-11-16）

家长/扫描合并构建Flutter608、analyze、Web/APK与适用后端/Dart/后台门禁已通过；实际浏览器15流程538项分两次均有通过证据：首轮其余14流程484/484，家长周报仅旧成功文案工具断言失败，查看截图及产品实现后修断言并同构建54/54复验。新增家长写恢复31/31、扫描恢复27/27均在首轮通过；不是单次538全绿。固定包、日志、精确scope见`var/writing-recovery-build-artifacts.json`。新包尚未真机安装，真实OCR/身份/生产就绪不在该阶段验收内。后台审核ABA及并发问题另已复现，下一包修复，不将本阶段通过外推为整个项目安全。
