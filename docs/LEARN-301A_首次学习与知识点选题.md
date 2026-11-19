# LEARN-301A 首次学习与知识点选题

2026-11-17。首页首次学习引导增加“先练一道基础题”和“按知识点选题”。练习页可按正在学的知识点筛选，显示当前可练题量；切换科目、题型或地区范围时清除旧知识点条件，加载更多沿用当前知识点。

## 实现与边界

- 契约新增 `GET /questions/topics`，复用已发布题目、地区/年份/题型筛选；目录只来自当前学生可练题目的知识点，不暴露仅被私有题引用的知识点。家长及审核角色403。
- `GET /questions` 增加可选UUID参数 `knowledge_id`，与已有筛选叠加；未知知识点返回空列表，格式错误422。客户端请求只使用生成的方法和类型。
- `TodayTasks` 增加可选 `cold_start`。只有本人尚未提交作答且未主动结束独立阶段查看解析时为true；只打开题目不清除此标记，其他学生的记录不参与。旧客户端可忽略新增字段，旧缓存缺字段时新客户端不推断首次状态。
- 这是练习起点选择，不是完整诊断测验、能力档案或已验证的教学效果。知识点不冒充教材章节；Q-08/Q-09没有因此冻结，也不新增省份与教材的硬编码映射。没有新建学生偏好表或诊断任务队列。
- 选题目录需要联网；已有缓存任务/题面/本机草稿继续走原恢复路径，不把未加载的目录承诺为离线可用。样题仍是未经学科审校的工程样题。

## 已执行证据

- 后端功能缺失7项红：`var/learn301-topic-red.log`；页面入口/筛选缺失2项红：`var/learn301-ui-red.log`。
- 题目、任务与契约378项：`var/learn301-backend-contract.log`；后补私有题独有知识点回归后API8项：`var/learn301-api-final.log`。不将两组重叠测试相加。
- Flutter全量638项：`var/learn301-full-flutter.log`；后补手机1.5倍字体后专题5项：`var/learn301-ui-final.log`；analyze无问题：`var/learn301-analyze-final.log`。专题覆盖目录失败重试、真实生成参数、科目重置与首次状态展示。
- Dart契约包274项：`var/learn301-dart.log`；后台429项、typecheck/check:api通过，见 `var/learn301-admin-*.log`。Dart/TS已重新生成，138份真实响应样例含question_topics，见 `var/learn301-fixtures.log`。未手改g.dart。
- 浏览器新Web构建通过：`var/learn301-web.log`；实际新学生入口→数学知识点→实际请求/题量/渲染→切换物理重置→真实API完成本人练习后入口消失，10/10：`var/learn301-browser-final.log`。完成记录由测试API产生，不将其声称为通过UI提交。首屏和筛选页截图已查看，保存在 `var/e2e-learn301-final-20261117/`。
- 浏览器工具/变异执行器138项：`var/learn301-tooling.log`；Ruff通过：`var/learn301-ruff-final.log`。
- 可见性、选中筛选、首次状态3/3变异捕获：`var/learn301-mutations/mutation-evidence-5idj4viu/summary.json`；363文件快照全部恢复且主区7份源码一致：`var/learn301-source-verification.json`。

当前后端全量终态2669通过/120可选环境跳过，见 `var/learn301-full-backend.log`；前一轮2658通过/120可选环境跳过不包含本增量。完整简短诊断、教材章节进度、变式迁移/延迟复测有效性与授权试点仍属于LEARN-301未完成范围；本轮无真实供应商调用、上线发布或真机验收。
