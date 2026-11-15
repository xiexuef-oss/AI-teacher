# tools/e2e：浏览器联调

用真实的后端、Flutter Web 发布版和审核后台，让无头 Chromium 像用户一样走完整的流程。
Widget 测试和 API 测试都用假数据或测试客户端，抓不到"页面和真实服务端对不上"的问题；这一层抓得到
（前几个功能的联调里发现过：从用户输入拼出的非法幂等键、旧页面用另一个身份的 token 重新请求、
成功提示被并进了输入框的读屏标签……）。设计取舍见 `docs/ADR-014_联调脚本进仓库.md`。

## 运行

第一次：

```
uv sync --group e2e                                  # 装 playwright（可选依赖组，默认的 uv sync 不装）
uv run --group e2e playwright install chromium       # 装浏览器；机器上已有对应版本的 Chromium 就不用
cd apps/admin_web && npm install                     # 审核后台的依赖（流程要用到审核后台时）
```

之后：

```
uv run --group e2e python tools/e2e/run.py                       # 全部流程
uv run --group e2e python tools/e2e/run.py --list                # 列出流程
uv run --group e2e python tools/e2e/run.py --only parent_weekly  # 只跑某几条（可以写多个）
uv run --group e2e python tools/e2e/run.py --headed              # 显示浏览器窗口，排查用
uv run --group e2e python tools/e2e/run.py --no-build            # 不检查、不重新构建 Web 版
```

全部流程约 8 分钟（Web 版过期时再加 2~3 分钟构建）。退出码：0 全部通过，1 有检查没通过，
2 环境问题（缺依赖、端口被占、构建失败）。

**端口是固定的**：后端 8000（Web 版里写死了这个地址）、学生端静态服务 8081、审核后台 5174。
开始前这几个端口得是空的，本机的开发服务要先停掉；否则会直接报"端口被占用"。

**Web 版过期会自动重新构建**：`apps/flutter_student/build/web` 比 `lib/`、`assets/`、`web/`、
`pubspec.*`、契约包 `lib/` 里任何文件旧，就先 `flutter build web --release`。过期的构建会让联调测到旧代码、
给出"通过"的假象，所以默认不跳过；`--no-build` 是你明确知道它没过期时才用。找不到 flutter 时用
`--flutter C:/src/flutter/bin/flutter.bat`，或设置环境变量 `FLUTTER_BIN`。

## 它做了什么

- 每条流程用**全新的 SQLite 数据库**和一个新起的后端（`var/e2e/<流程名>/`），互不影响，也不碰本机的演示库
  `var/tutor_dev.sqlite3`。
- 学生端和家长用不同的浏览器上下文（本机存储互相隔离）。
- 输出在 `var/e2e/`（已被 .gitignore 忽略）：每条流程的后端日志 `api.log`、数据库、`screenshots/`；
  流程中途出错时会给所有打开的页面各截一张图作为现场。

| 流程 | 覆盖 |
|---|---|
| `student_experiment` | 引导 → 练习页 → 实验题：安全提示、数据表、填格子、本机草稿落地与云端同步、重新打开后恢复、提交（不评分）、对照参考数据、自查、学情 |
| `admin_experiment` | 审核后台：队列、审核页（安全提示、数据表、参考值、要点）、下线、改安全提示存成新版本、版本对比、改成高风险时程序校验拦住 |
| `parent_weekly` | 学生生成邀请码授权 → 家长输入邀请码、看周报与翻周 → 学生撤销 → 家长什么都看不到 → 再授权 → 来回切换身份 |

## 数据从哪来

题目的标题、数据表、参考值、要点数量、答案都从样题（`services/api/seed/`）和测试里的答案表
（`tests/support/flows.py`）取，脚本里不重抄一遍。样题改了，联调跟着变；改得让联调对不上
（少了一道题、某个答案不再判对、周报的最小样本数变了），`tests/unit/test_e2e_tooling.py` 会先红。
这个测试不需要浏览器，随 `uv run pytest -q` 一起跑。

## 写新流程

在 `tools/e2e/flows/` 里加一个模块，定义 `run(ctx)` 和 `FLOW = Flow(name=..., title=..., needs=..., run=run)`，
再登记到 `flows/__init__.py`。几条约定：

- 期望值从样题里取（`e2e.data`），别写死标题和数字；
- 造数据用后端接口（`e2e.api_client`），比在界面上点快、也稳；界面上只走要测的那一段；
- Flutter Web 的元素靠语义树找：`page.get_by_role("button", name=...)`，短名字加 `exact=True`；
  文字读 `all_text(page)`；输入框的值读不到（Web 上的语义输入框不回显没聚焦字段的值），
  要验证"恢复了什么"就看提交请求体（`page.submit_bodies`）和截图；
- 往 Flutter 的输入框里输入用 `type_into(page, 输入框, 文字)`，不要自己 `click()` 之后马上 `keyboard.type()`：
  点完马上输入会丢掉第一个字符（联调里出现过）；
- 检查用 `ctx.check(名字, 条件, 出错时的细节)`，不要用 assert——一项不过不该拦住后面的检查。

## 没有覆盖的

- 只有 Chromium（无头、软件渲染）：没有 Safari/WebKit，没有真机，没有 TalkBack/VoiceOver；
- 鼠标滚轮和触摸滚动（视口开得很高，一屏放得下整页）、字体放大和手机宽度（这些由 Widget 测试覆盖）；
- 解答题（`written`）的浏览器流程：它和实验题共用自查那一段，但没有单独的脚本；
- 手写笔迹单独提交。
