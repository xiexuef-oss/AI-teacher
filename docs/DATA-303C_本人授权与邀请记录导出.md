# DATA-303C 本人授权与邀请记录导出

2026-11-17。实现、主门禁和全部295个变异目标的有效证据已核对；不关闭完整个人数据导出或全项目目标。

## 范围

沿用学生专属 `GET /profile/learning-export`，新增可选契约字段 `parent_access_records`。
新服务始终返回该字段；旧文件缺失表示未包含这一范围，不能解释为从未授权。
生成的 Dart 类型保留这个区别，没有用空数组代替缺失字段。

只包含当前学生的现存记录，按保存的创建时间及 ID 排序：

- links：授权记录 ID、版本、现存同意时间、撤销时间及创建时间。
- invites：邀请记录 ID、有效期、兑换时间、撤销时间及创建时间，包括已过期、已兑换和已作废记录。
- history_complete 固定为 false。重新授权会覆盖绑定行的旧时间，不补造已经不存在的历史。

不导出邀请码、code_hash、兑换者或家长 ID、标签或其他家长资料，不读取或导出其他学生的记录。
这不是法定监护核验，也不提供导入或恢复授权。读取不兑换、续期、撤销或清理记录。
家长即使已经获授权也不能调用此导出接口；角色检查先于筛选参数处理。

复用现有读取快照、10000条源记录及32MiB限制，新增授权/邀请行计入总量；超限整次413。
没有新迁移、存储、队列或模型调用。旧 excluded 枚举保留兼容，但新文件不再声称排除已纳入的授权记录。
其他排除范围、本机草稿和摸底命令单独导出的行为保持原状。

## 验证证据

- 契约先改，修正测试中对既有绑定响应字段的误用后，`var/data303c-api-feature-red.log` 四项因缺少新范围/限额而失败；实现后通过。
- 契约使用3.1的nullable类型联合；初次实现后的两项契约失败已修复。API/家长授权/联调工具147项通过：`var/data303c-api-tooling.log`。
- SQLite在导出期间由另一连接实际撤销并新增邀请，导出仍保持原快照；真实隔离MySQL RR下同样验证，另检查归属和敏感字段，1项通过：`var/data303c-mysql.log`。
- 147份真实响应样例重新导出；Dart/TS类型由契约生成。Dart284项通过，含旧文件范围缺失为null与新字段往返：`var/data303c-dart.log`。
- Flutter682项、导出组件专项14项、analyze通过：`var/data303c-full-flutter.log`、`var/data303c-flutter-export.log`、`var/data303c-analyze.log`。
- 后台432项、typecheck、check:api通过，见`var/data303c-admin*.log`。全仓Ruff、相关格式及Dart生成新鲜度通过。
- 后端全量2849项通过、135项可选基础设施未配置而跳过，进程退出0：`var/data303c-full-backend.log`。这次也覆盖此前PROD-303的供应商类型补强，不将skip算作真实基础设施通过。
- 实际新Web构建与浏览器下载18/18：`var/data303c-browser.log`。自编授权/邀请通过真实HTTP准备，导出通过实际页面下载；校验已撤销授权、兑换/待兑换邀请、另一学生排除及邀请码/家长信息排除，同时保留离线本机导出检查。
- 已查看`var/e2e-data303c-20261117/local_draft_export/screenshots/server-export-downloaded.png`，范围说明与下载提示显示正常。
- 新增归属、两类记录限额和错误历史声明的五项变异均捕获：`var/data303c-parent-mutations/mutation-evidence-lq9lvdix/summary.json`。
- 完整295目标首轮293捕获、2项缺Linux配置未运行，其他异常计数均0，进程退出0（显式使用allow-not-run，不将退出0等同于295项通过）：`var/data303c-all-mutations/mutation-evidence-peep5k1w/summary.json`。
- 复用此前显式配置的Ubuntu/bwrap/LibreOffice运行时，把package改为当前隔离快照；实际网络/宿主访问隔离两个基线通过，再补跑LinuxDoc三项全部捕获、无跳过，含首轮缺配置两项：`var/data303c-linux-baseline.log`、`var/data303c-linux-mutations/mutation-evidence-teo5reep/summary.json`。
- 按目标名去重，295/295均有通过的原始基线及有效失败JUnit，存活/破损/基线失败/执行错误/剩余未运行均0；逐条重读原始JUnit核对，汇总为`var/data303c-mutation-coverage.json`。这是首轮加补证的合并结果，不冒称单次全量295项零跳过。
- 905份隔离文件已完整还原；主程序、契约、样例与冻结快照逐字节一致，之后的说明文档更新单列在`var/data303c-source-verification.json`，不把文档差异当作源码已改变或悄悄覆盖主工作区。

## 尚未完成

本轮所有进程已终态，状态见`var/data303c-status.json`。
后续DATA-303D已补现存拍题文字，见对应专篇；完整个人数据导出还缺媒体、完整扫描历史、本机未同步记录与模型用量等范围；不存在的完整授权历史、真实身份注销与留存/备份处理仍待Q-03/Q-07。
本轮没有原卷导入、真实模型调用、真实平板/iPad安装或发布部署。
