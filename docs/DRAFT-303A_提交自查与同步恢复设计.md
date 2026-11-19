# DRAFT-303A 提交、自查与同步恢复

状态：固定Web/APK的本地工程阶段已验收；全Flutter508、十一浏览器流程407/407、完整206变异及九门禁分次证据均通过，真实infra100另无skip通过。真机验收待设备，后续303B源码单独验证，不冒称固定产物覆盖最新工作区。属于303第一阶段，不代替后续辅导/复测、家长/设置/扫描及审核后台写入口恢复。基础调查见DRAFT-303_其余写命令恢复调查.md。

## 不变式

复用302同bundle、串行队列、scope lease、workspace generation和activeEpoch。每次明确动作生成随机intent/key，完整method/path/body及来源快照先落本机。SHA256只校验完整性，不把相同内容永久当成同一动作。损坏/错账号/错资源记录fail closed，原文保留；晚到结果不得改新workspace。

每个attempt按submit/draft_sync/self_check区分串行lane。命令保存owner、question/version、session/attempt/workspace、持久editGeneration、捕获的activeEpoch、完整答案/证明空步骤与依据/笔迹。阶段通过CAS推进，prepared之后的body/key/资源/epoch不可变；结果先落盘再ack。已确认后下一次动作使用新intent，即使body与更早一次相同。

## 提交快照与版本契约

学生点击时先保存A完整快照和固定elapsed_ms。提交依赖A的草稿同步intent；取得其revision后，形成带expected_draft_revision的完整SubmitRequest，落盘后再发提交。依赖未完成时不得先提交，也不能让之后B笔迹进入A的提交。

若点击时旧同步X尚未确认，先以不可发送的waiting_dependency阶段持久保存A和elapsed，不覆盖X；恢复X后再原子准备A自己的同步依赖。X与A内容不同就不能复用X的回执。已经保存的A不随等待期间的B修改，重启也不能重新捕获成B。未绑定会话/作答时的创建等待窗口同样需要验证，不能把302创建意图等同于提交意图已经保存。

新增可选、非null严格整数expected_draft_revision（>=0）；服务器在既有Session→Attempt→Draft锁内比较，错误409 submission_draft_revision_conflict带expected_draft_revision、server_revision、本人server_draft，不判题/不发事件/不留成功回执。缺省兼容旧客户端，省略新字段保留旧canonical fingerprint；已成功同键重放先于新的revision检查。无需新增SQL迁移，不改变主观题pending或实际提交序号。

## A未确认、当前已改B

网络失败/超时/丢响应/500均视为结果未知。若当前仍A，同键同body恢复；若已是B，先只读查状态，不能自动发旧A或换键提交B。需要重放原提交时明确说明“恢复原提交，当前修改保留”。已提交状态或答案相等均不足以证明是本intent的回执。

提交A结果已知时，先把当前尚在内存的B落本机；同bundle ack保存A结果与快照，只在持久编辑代际/内容均仍为A时清理该稿。否则B移到独立“未提交续稿”槽，与A真实评估分开展示，不能让A反馈解释B。任何落盘失败保留命令和可恢复快照，不报告B已保存。

继续B需学生明确选择在原Session创建新Attempt，复用302持久创建协议并加入显式transferPolicy（空白重试/迁入B），继承Session辅助状态。已有未提交稿时不覆盖它；Session已DONE时保留B，不自动另开Session重置状态。需要明确的续稿查看/继续入口，不能只藏在bundle。

## 同步与自查

同步使用持久随机key与完整DraftSyncRequest，替代String.hashCode键；在途A的请求体不随B改变。A回执只证明曾写成功；ack保留B的dirty状态，不降低已知更高revision，遇409复用双方留档。提交A结果未知时，不能先向同Attempt同步B再读取服务器笔迹来提交A。

自查每次保存是新intent，未确认重试复用原body/key；修复A→B→A第三次重放第一次回执却让服务器仍B的问题。勾选改动先落本机，A晚到只更新已确认快照，不覆盖B。现自查API无revision，第一阶段不冒称跨设备CAS；远端不同先展示双方明确选择，进一步严格跨设备保护另追加契约/迁移，不使用saved_at冒充版本。

## 失败与恢复

明确422可标rejected并留证据，修正是新intent；409草稿冲突保留双方；幂等body冲突阻断不换键；401等待同owner恢复；404/撤销权限保留本机、不自动重建。提交回执恢复后再读最新Session/Attempt/Events，不用过期回执复位辅助、结束状态或重复追加同一事件。

## 实施与验收

1. 契约/后端：expected_draft_revision先红后绿，旧请求/旧SQL回执兼容、严格整数、冲突无副作用及真实MySQL等待后current read。
2. 存储：持久editGeneration、动作journal、专用原子ack与续稿槽；每个写入窗口失败、未知格式、owner/scope/key/body/epoch变更拒绝且原文不变。
3. 控制器：提交elapsed不重算、A未知后B不自动写、A确认后B完整保留/明确续写；自查A→B→A实际服务器最终A；同步在途新增笔迹和旧ACK不降revision；保持302旧稿/路由/迟到回调回归。
4. 真实浏览器：服务器实际成功后丢响应/刷新、原输入与续稿可达、他端更新笔迹的提交409、明确恢复动作；无伪造响应/存储写入。
5. 生成契约包/真实样例/后台类型、相关变异、全门禁；真机验收独立，不把浏览器等同整机重启。

文件所有权：主线程协调contracts与生成产物；后端单一负责人；store及其测试单一负责人；controller/page及其测试单一负责人，Flutter测试需串行。Q-03/04/05/06/07/08/09不自动冻结，不启用真实供应商或自动主观评分。

## 续稿可读语义验收

真实浏览器发现SelectableText虽在画布显示B，但当前SDK生成空disabled textarea，DOM value/defaultValue/textContent及AX均无B。证据var/e2e-303a-dom-probe-output-20261116/student_write_recovery/probe.json；这不是等待时序。SDK engine/semantics/text_field.dart的update仅处理label/enabled，只有焦点策略才接入value，不能用修改DOM或存储读取替代UI断言。

续稿对话框现以显式Semantics提供完整答案文本并排除空子语义，视觉仍SelectableText。widget先因缺label失败、修复后通过；新构建真实DOM为选项B文本、ARIA/AX同样可读，dialog内精确get_by_text断言通过，续稿12/12绿。最终证据var/e2e-303a-semantics-green2-output-20261116/student_write_recovery/probe.json，answer_text_matches=1。Flutter508/analyze/Web/APK均已在修复后重验，十一流程全回归407/407通过；真实TalkBack/VoiceOver依旧属于独立设备待办。
