# admin_web：内容审核后台

docs/03 的 P11 `/admin/review`，PRD P0 第 9 条"管理后台最小审核流"。审校员在这里审题目、答案和解法：
`draft → reviewed → published`，发现问题可以撤回（`withdrawn`，终态）。设计取舍见 `docs/ADR-008_内容审核最小流.md`。

Vue 3 + Vite + TypeScript，路由用哈希模式，公式用 KaTeX。**接口类型不手写**：`src/api/schema.d.ts` 由
`contracts/openapi.yaml` 生成，契约改了而没有重新生成时 `npm run check:api` 会失败。

## 运行

需要 Node 22（开发机是 22.18）。先在仓库根目录启动 API（它会显式开启本地身份 Mock，并带 3 道待审样题）：

```
uv run python tools/run_dev_api.py
```

再启动后台：

```
cd apps/admin_web
npm install
npm run dev          # http://127.0.0.1:5174
```

登录页只有"本地开发登录"：每点一次，就在本机创建一个新的审核员（或管理员）身份。真实登录方式还没有定（Q-03），
所以这个后台目前只能在本机开发环境里进入，后端没有开启本地身份 Mock 时登录页会说明原因。
后端地址默认 `http://127.0.0.1:8000/api/v1`，用环境变量 `VITE_API_BASE` 覆盖。

演示流程：用审核员身份进入 → "待审"页签里有 3 道样题 → 打开一道 → 二审通过 → 上线；回到队列，
"已上线"的数字加一，学生端的练习列表里也有了这道题。再去"下线"它，必须写原因。

修改：打开一道待审（或已下线）的题，点"编辑题目"，改完"保存为新版本"——旧版本留着，新版本回到待审，你成为它的提交者，
所以要换另一个身份（退出后以管理员进入）才能二审。已上线的题要先下线才能改。

解答题：审核页里能看到小问、按小问列出的参考答案、按小问分组的自查要点；编辑器里小问与参考答案是同一批行，
自查要点是另一批行（"所属小问"用下拉选，"整份解答"针对全部作答）。自查要点是一张清单，不带分值，不是评分标准（ADR-011）。

对比：保存之后点"查看这次改了什么"，或者在题目页的"版本与审核历史"里点"对比最近两个版本"、点某个版本徽章回看那一版的完整内容。
对比页左右并排，删掉的片段红底划线、新加的绿底；默认只显示有改动的部分，勾选"显示没有改动的部分"看全部。

## 命令

```
npm test             # vitest：API 客户端、决策规则、公式渲染、队列页、审核页、编辑器、版本对比
npm run typecheck    # vue-tsc；测试数据按契约类型写，契约改了这里先红
npm run check:api    # schema.d.ts 是否由当前契约生成
npm run gen:api      # 重新生成 schema.d.ts
npm run build        # 类型检查 + 打包到 dist/
```

## 目录

```
src/api/        client.ts（请求与错误信封）、admin.ts（接口函数）、guard.ts（401 与幂等键）、schema.d.ts（生成）
src/views/      LoginView、QueueView（审核队列）、QuestionView（题目全貌 + 决策）、QuestionCompareView（版本对比）
src/components/ DecisionPanel（决策与错误提示）、QuestionEditor（编辑题目）、StringList、MathText（KaTeX）、StatusBadge
src/editing.ts  编辑表单 ↔ 修改请求的转换（纯函数，有来回测试）
src/diff.ts、src/compare.ts  文本与列表的差异、两个版本快照的对比（纯函数）
src/decisions.ts  各状态可做的决策、说明文字、错误码翻译（只是提前提示，授权在服务端）
tests/          vitest；fixtures.ts 里的数据按契约类型写
```

## 已知限制

- 版本对比只能两两对比，不能导出；文本对比是字/词级的，挪动整段会显示成删一段、加一段（ADR-010）。
- 编辑：附件原样带过去、不能改；图解模板与参数、判定规则要手写 JSON；选择题和填空题的评分细则也是手写 JSON；每次保存都是一个新版本。
- 解答题的小问、参考答案、自查要点可以改；小问的键被改名后，指向它的要点要手动改（程序校验会指出来）。
- 地区适用标记只能查看，不能在这里审核。
- 队列分页是 offset 游标，题量大了要改成数据库侧的键集分页。
- 只在 Chrome 里看过；无障碍只做了语义标签和键盘可达，没有用读屏软件走过。
- 安装时 npm 会对 `nopt`、`abbrev` 报"要求 Node ≥ 22.22"的警告：它们是 `@vue/test-utils → js-beautify` 的命令行解析依赖，
  测试和构建不会用到，开发机 Node 22.18 上一切正常。jsdom 固定在 29（31 要求 Node ≥ 22.22）。
