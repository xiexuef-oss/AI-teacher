# flutter_student

AI 理科私教的学生端（Flutter）。平板横屏优先（≥900dp 题目 42% / 草稿 58%，分隔条可拖，范围 35%–60%），兼容手机（<600dp 单栏，底部切换"题目/草稿"）。

仓库整体说明、运行方式见根目录的 [README.md](../../README.md)；技术取舍、与文档的偏差、没有验证过的东西见 [ADR-007](../../docs/ADR-007_切片技术锁定.md) 的"Flutter 学生端"一节。

## 常用命令

Flutter 没有加入系统 PATH，用绝对路径。**不要用 `flutter analyze`**：项目路径含中文时它会崩溃，用 `dart analyze`。

```powershell
C:\src\flutter\bin\flutter.bat test
C:\src\flutter\bin\dart.bat analyze
C:\src\flutter\bin\flutter.bat run -d chrome --web-port 8080     # 需要先启动后端：uv run python tools/run_dev_api.py
```

## 目录

```
lib/
  core/        主题、响应式分栏、公式文本、本地存储、登录与数据提供者、公共组件
  features/
    solve/     作答页（P03）：作答控制器、本地草稿、手写画布（ink/）、答题输入、辅导时间线
    visual/    六个图解模板的计算（visual_math）、绘制（painters）与带滑块的视图
    home/ onboarding/ practice/ review/ progress/ profile/ misc/ startup/
  router.dart  页面路由（docs/03 §2）
test/
  support/     假后端（响应取自真实样例）、整页测试工具
  fixtures/    公式片段（由 tools/export_dart_fixtures.py 导出）
```

## 约定

- 请求与响应对象只用 `tutor_contracts` 里生成的类型，不手写。
- 学生的输入先落本机、再同步云端；同步带版本号，冲突时不覆盖任何一方。
- 每个会改变服务端状态的动作带幂等键，失败后重试复用同一个键。
- 图解只认 `visualTemplates` 里注册过的模板，参数一律经注册表补齐并收进边界；拖动滑块不请求网络。
- 客户端不持有任何模型供应商的密钥，也不直连模型。
