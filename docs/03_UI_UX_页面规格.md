# 03 Flutter UI / UX 交互规格

## 1. 统一布局与设计系统
宽度 ≥ 900dp：横屏双栏题目 42%/演算区 58%，拖动调整 35–60%；600–899dp：自适应上下或双栏（按可用区域）；<600dp：单栏与底部切换“题目/草稿”。不得以物理像素或设备品牌硬编码。触控目标 ≥ 44×44dp；文字缩放 1.0–1.5 后不截断。支持系统深浅色、无障碍语义标签和键盘焦点。

## 2. 页面清单与路由
| ID | 路由 | 功能 | 关键状态 |
|---|---|---|---|
| P01 | `/home` | 今日任务、拍题、练习、我的 | empty/loading/ready/offline/error |
| P02 | `/scan` | 拍照/选图/裁切/OCR 确认 | camera-denied/low-confidence/edit/retry |
| P03 | `/questions/:id/solve` | 客观题、主观题、实验题统一作答 | unsaved/saving/saved/conflict/submitted |
| P04 | `/tutor/:sessionId` | AI 提示、双解法、图示推荐 | thinking/hint/explanation/fallback |
| P05 | `/visual/:templateId` | 可调参数图解/静态后备 | available/invalid-template/static |
| P06 | `/practice` | 高考题型/专题/限时选择 | empty/ready/loading |
| P07 | `/review` | 错题、间隔复测 | due/empty/paused |
| P08 | `/progress` | 独立与辅助正确率等趋势 | insufficient-data/ready |
| P09 | `/profile` | 年级/教材/隐私/导出删除 | saved/error |
| P10 | `/parent/weekly` | 授权绑定的周报 | unauthorized/empty/ready |
| P11 | `/admin/review` | 内容审核后台 Web | draft/rejected/published |

## 3. P03 统一作答页（最关键）
- 顶栏：返回、学科/题型/题序、手写保存状态；主内容左侧题干、图/表/公式；右侧草稿画布（多页可追加）。
- 根据 `answer_mode` 自动渲染 `single_choice`, `multiple_choice`, `fill`, `written`, `experiment`；综合题支持 `subquestions`。
- 右侧工具：笔、颜色（默认黑/蓝）、粗细、橡皮、撤销、重做、清空（须二次确认）；笔迹带时间戳和压力信息（可得时）。
- 固定底栏：提交、给点提示、看图理解；“常规解法/快速解法”默认在提交后或学生明确选择结束独立作答后出现；打开解析标记 `used_solution=true`。
- AI 步骤高亮引用 OCR 识别的 `span_id`，若源无法对齐展示普通点评，不得假装精确定位。
- 切小问、返回、转后台、断网均不清理草稿。提交后展示校验提示，不能直接将 AI 置信判断等同于官方得分。

## 4. P02 拍题流程
打开相机 → 授权失败可从相册选图 → 裁切 → 上传原图 → 服务端 OCR → 客户端显示“可编辑题干”与关键数学表达式 → 用户确认 → 关联已有题或新建未审核题草案 → P03。置信度低需提示可能不完整；图像可能包含姓名，上传前提供裁剪/遮盖提示。

## 5. P04 教学会话
用户动作：`request_hint`、`request_standard`、`request_fast`、`request_visual`、`submit_attempt`、`mark_understood`、`mark_confused`。同一课题 AI 每轮只讲一个主要概念。连续两次 confused 推荐前置知识与图解。不存在可靠快速解法时按钮隐藏或显示不适用说明。支持“我还是不懂/换种讲法”。

## 6. 图解 UI
输入服务端已验证的 `visual_event`：`template_id`（白名单）、`params`（有限数值）、`caption`；界面含滑块、重置、辅助说明，参数改变实时渲染且不请求 LLM。模板不可用展示静态图或文字；不应出现白屏。

## 7. 重要异常与可用性
- 断网：保存草稿、阅读离线内容；云端提示灰化且说明原因。
- 登录失效：维持未同步草稿在本地，重登后同步；避免不同账号混合，需隔离本地资料。
- 409 冲突：提示保留本地稿/查看云端稿/创建副本。
- OCR 失败：手动录入题目或重拍；草稿保存不受影响。
- 模型超时：显示可取消、重试/查看审核解析；不重复扣减学习次数。

## 8. 页面级验收（示例）
P03：在 iPad/Android 10–13 英寸真机完成 10 分钟连续书写，手掌误触与书写延时可接受；应用终止重开草稿完整；大字体下按钮可操作。P02：低置信度明确呈现并允许编辑。P04：未完成独立答题前不自动泄露完整答案。
