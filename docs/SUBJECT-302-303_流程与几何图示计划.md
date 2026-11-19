# SUBJECT-302/303：流程与几何图示最小切片计划

状态：2026-11-16 已获实施窗口，工程最小切片已实现，整合验证中。初稿阶段仅设计；后续按主线程授权增量修改契约、注册表、渲染及自编样题。本文不是学科审校通过记录，也不表示两个 backlog 任务全部完成。

## 当前缺口与保护边界

`packages/visual_templates/registry.json` 当前有六个模板。`chemical_flow` 是质量、物质的量、化学计量数的换算，不能当成工业工艺流程；没有三角形或证明几何模板。保留现有 ID、样题与行为，增量加入两个模板。

题目绑定的 `visual` 必须继续通过 SEC304：未提交且 `used_solution=false` 时不下发规格、参数、caption 或 fallback；`request_visual` 携带确认标志也不解锁。提交后或明确选择完整解析并记录 `used_solution` 后才提供图解。复测禁辅助规则优先。白名单只约束执行与参数范围，不证明内容不会泄题。

通用演示页不绑定题目，仍是概念演示工具，不构成防作弊边界。题面实际给定流程图、几何原图使用 SUBJECT301 已审静态附件；必须满足发布、当前版本引用、独立审校声明及媒体可用条件，不能通过新图解绕开。媒体丢失仍提供 alt/不可用提示，不阻止提交或本机草稿。

主观题不增加自动评分：`written`、`experiment`、`proof` 继续 `pending`，参考答案、证明与自查仅按既有提交门控展示；高风险实验仍禁入。Q-05 学科与版权审校、Q-06 主观评分、Q-07 生产媒体留存均不由本切片冻结。

## SUBJECT-302：chemical_process

新增 `chemical_process`，使用代码内固定拓扑：原料 → 处理Ⅰ → 分离 → 处理Ⅱ → 产物；可选支路从“分离”指向“支路”，可选回流从“处理Ⅱ”返回“处理Ⅰ”。渲染器只画此有限图，不接收动态节点、边、标签、物质名称、方程式、URL、HTML、SVG 或脚本。保留旧 `chemical_flow` 的计量换算含义。

| 参数 | 类型及边界 | 默认值 | 交互与含义 |
|---|---|---|---|
| `focus` | 整数 0..4，step=1 | 0 | 可调；0概览、1处理Ⅰ、2分离、3处理Ⅱ、4产物；仅高亮既有位置 |
| `branch` | 整数 0..1，step=1 | 0 | 不可调；审校配置题目明确给出的支路是否存在 |
| `recycle` | 整数 0..1，step=1 | 0 | 不可调；审校配置题目明确给出的回流是否存在 |

默认不画支路/回流，避免替题目补过程。focus 不生成试剂、条件、pH、物质判定、收率、产量或操作建议，不计算答案。图旁固定说明“流程关系示意；具体物质、条件和操作以题目及审核解析为准”。caption 只使用审核文本，不能被渲染器解释为代码。

fallback 与 Semantics 使用相同固定节点顺序，并按 branch/recycle 明说“有/无支路”“有/无回流”，以及当前焦点；不能只靠颜色、箭头或画布传递信息。未知模板仍显示既有静态说明，不白屏。此切片是工艺结构阅读原型，不具备任意工艺图编辑、化学推断求解、危险反应推荐或学科真实性自动验证。

## SUBJECT-303：triangle_schematic

新增 `triangle_schematic`，只绘制 A、B、C 三顶点及三边，不画辅助线、垂足、平行/垂直/等长/等角符号，不计算或显示角度、长度、面积、相似比例或证明结论。关键构造仍只在题目审核的解析中出现；分层提示继续不给式子。不存在“三角形模板天然安全”的例外。

| 参数 | 类型及边界 | 默认值 | 交互与含义 |
|---|---|---|---|
| `apex_x` | 有限数 0.2..0.8，step=0.05 | 0.35 | 不可调；C点在AB基线上的相对绘图位置，不是数学已知量 |
| `height` | 有限数 0.3..0.9，step=0.05 | 0.65 | 不可调；相对绘图高度，不是长度条件 |
| `focus` | 整数 0..3，step=1 | 0 | 可调；0整体、1顶点A、2顶点B、3顶点C；不构造新点或线 |

A/B 固定在相对基线两端，C始终在上方且非退化，默认避免等腰/直角的视觉暗示。图旁及无障碍说明固定包含“示意图，非按比例；不能凭外观推断长度、角度或关系”。焦点只辅助定位顶点，不宣称该点承担待证角色。题目并非已给三角形、命名不一致或原图关系不能忠实表示时，不绑定该模板，使用已审原图附件或不提供动态图解。此切片不覆盖复杂几何构图、圆锥曲线、空间几何和自动证明。

## 精确实现清单与文件边界

1. **契约先行**：先在 `contracts/tutor_event.schema.json` 的 `$defs.VisualPayload.properties.template_id.enum` 增加两个 ID，并在 `packages/visual_templates/registry.json` 声明上表数值参数、固定标题/summary/fallback。保持 `params` 数值对象、最多12项、禁止额外 payload 属性；不引入标签或任意图结构字段。`contracts/openapi.yaml` 的 `AdminVisual.template_id` 目前是 string，原则上无需改其形状；若补描述须同批生成并校验，不能手写新请求类型。
2. **先红测试**：新增两个 ID 与参数验证、SEC304门控及证明 pending 测试，确认因模板缺失而失败，再实现。更新 `docs/06_AI教学引擎.md` §6 的模板清单和 `tests/contract/test_contract_files.py` 的 `DOC06_TEMPLATES`，三份清单保持一致。
3. **后端与网关**：`services/ai_gateway/ai_gateway/visual_templates.py` 的既有 `VisualRegistry.normalize` 复用有限数、整数、边界、未知参数拒绝，不增加脚本解释器。`services/api/tutor_api/visuals.py` 复用 normalized_visual；`services/api/tutor_api/services/orchestrator.py` 原则上无需分支，保留现有门控，若确需修改先协调整文件所有权。`services/api/tutor_api/services/content_seed.py` 仅在确有新内容约束需要时改，不能用数字/词表假称 caption 安全。
4. **工程样题**：在 `services/api/seed/questions/chemistry.yaml`、`proof.yaml` 各追加一题自编低风险样题，使用既有知识点；确需新节点再追加 `services/api/seed/knowledge.yaml`。流程题仅考给定结构阅读；证明题沿用 steps/reason、以 conclusion 收尾及阶段自查语义，题面明确给定 ABC，不补暗含关系。没有审校人确认前只称工程样题，不能称真题、地区高考风格或正式学科审校题。
5. **生成产物**：运行 `tools/gen_dart_contracts.py`，更新 `packages/contracts/dart/lib/src/visual_templates.g.dart` 及受教学事件枚举影响的生成文件；不手改 `*.g.dart`。运行 `tools/export_dart_fixtures.py`，新增提交前 blocked、提交后/完整解析后两模板真实响应样例及必要 question/subjective fixture；生成器输出的 fixtures 与公式片段一同核验。审核后台执行 `npm run gen:api` 和 `check:api`，没有OpenAPI变化时类型应无差异。
6. **Flutter渲染**：`apps/flutter_student/lib/features/visual/painters.dart` 添加两个固定 painter、`painterFor` 分派和 `describeVisual`；`visual_math.dart` 仅放纯布局/拓扑数据，不加入化学求解、几何推导。`visual_view.dart` 原则上复用注册表交互，必要时改焦点可访问控件与固定说明；不引入网络、外部URL或模型调用。不要修改 solve/draft 文件；若页面整合确需变动先协调当前所有者。
7. **字体及可访问性**：新中文固定标签进入注册表/画布/Semantics；检查 `tools/build_cjk_font.py` 扫描源与 `tests/app/test_cjk_font.py`。需要时运行字体生成，更新 `apps/flutter_student/assets/fonts/NotoSansSC-Subset.otf`（固定源校验与OFL保持）；不可把缺字告警当作验证通过。窄屏、大字体、深浅色均有可读文本替代。
8. **后台范围**：现有 QuestionEditor 的 teaching JSON 可以编辑新模板数值配置；暂不增加任意拓扑编辑器。`apps/admin_web` 若仅因生成类型/样例更新受影响，仍跑现有门禁。媒体编辑与独立审校声明不受本模板开关替代。

## 精确测试与验收顺序

| 层级/文件 | 必须验证 |
|---|---|
| `tests/contract/test_contract_files.py` | registry/schema/docs清单一致；两ID事件可过Schema；参数数目与数值形状不扩宽 |
| `tests/gateway/test_validation.py` | 默认/上下界通过；未知ID/参数、字符串标签、bool、NaN/Infinity、越界、focus/branch/recycle小数被拒绝；旧六模板不回归 |
| `tests/content/test_seed_content.py` | 扩为八模板覆盖；新样题来源自编、低风险；caption和fallback有内容但不据此假称无泄题 |
| `tests/content/test_proof_content.py` | 新证明steps每步依据、conclusion收尾、阶段rubric完整；题面不含参考步骤/关键构造 |
| `tests/api/test_visual_security.py` | 两新模板独立阶段无规格/caption/fallback，confirm标志无效；已提交或明确完整解析后可发；used_solution只由完整解析动作记录；复测优先 |
| `tests/api/test_tutor_flow.py` 及既有主观题API测试 | 新证明提交仍pending且不进正确率；不重算既有评估；参考证明、自查仍提交后出现 |
| `packages/contracts/dart/test/visual_templates_test.dart` | 新参数顺序、默认、界限、离线规范化及未知模板行为 |
| `packages/contracts/dart/test/fixtures_test.dart`、`tests/contract/test_dart_fixtures.py`、`test_dart_codegen.py` | 真实响应与Schema一致、Dart可解码/往返、生成文件不过期 |
| `apps/flutter_student/test/visual_math_test.dart` | chemical_process只有固定节点/已配置支路回流；三角形所有合法参数非退化、有限、画布内；不产生答案或构造 |
| `apps/flutter_student/test/visual_view_test.dart` | 八模板深浅色/320px/大字体不溢出；焦点滑块与重置；分支/回流只读；Semantics/fallback拓扑一致；未知模板不崩溃；无脚本/网络行为 |
| `tests/app/test_cjk_font.py` | 新标签、说明与画布文字全部有字形 |
| `tools/e2e/flows/` 新增专项或复用学生流程，及 `tests/unit/test_e2e_tooling.py` | 期望从自编payload取得；独立阶段无规格→显式解析/提交→对应图解；证明pending与自查；实际题面原图继续受控媒体门控；截图留档 |
| `tools/mutation_check.py` | 两ID同样受SEC304门控；新参数整数/边界规则不可绕过；现有主观题pending守卫继续捕获；只在协调独占窗口变异，skip/error不算抓到 |

实施包顺序为：契约/注册表 → 红测试证据 → 后端样题与验证 → 生成/真实样例 → renderer/fallback/字体 → 专项绿 → 全部门禁及浏览器/目标变异。变异、真实服务与其他线程核心改动不得重叠。公开接口不增加新路由或权限，幂等、本机草稿、审核发布规则沿用原实现。

完成时分别报告实现证据与内容审校状态。工程门禁全部通过只能说明该原型符合已测技术边界；学科审校与更完整的化学推断/几何原文适配仍须另行验收，不将本计划直接标为 SUBJECT-302/303 全部完成。

## 本次实施记录

首轮内容测试因两题缺失出现2项失败，Flutter渲染测试因布局函数缺失编译失败；随后补齐实现。新增 `chem-process-reading` 完整写出主线、支路和回流；`math-triangle-coordinate-proof` 给出 A(0,0)、B(1,0)、C(0.35,0.65)，画布x/y使用同一尺度，没有用“非按比例”文字代替题设一致性。参考证明的三边平方值用独立Decimal计算复核；证明继续pending。

新流程题难度1依既有规则成为化学入门任务；没有改推荐算法，任务测试及Flutter首页标题断言改为与真实响应一致。两模板仍只在解析阶段提供，题面必要条件不依赖这些图解。

已取得：Flutter全量397项、渲染专项64项、Dart契约195项、API/契约生成相关176项、字体及registry/网关/内容293项通过，Flutter静态分析无问题。导出108份真实响应（新增两模板各question/blocked/submit/visual），中文字体覆盖通过。浏览器专项 `subject_diagrams` 已准备，等待协调的最新构建与服务窗口；未执行前不声称该浏览器覆盖通过。最终后端全量与变异证据由主线程整合记录，不能将各专项相加冒充独立测试总数。
