# DeepSeek 本地配置与鉴权检查

本地选用 DeepSeek Flash，非秘密默认值放在 `config/deepseek.local.example.env`：端点 `https://api.deepseek.com`、模型 `deepseek-flash`。可用同名进程环境变量 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL_FLASH` 覆盖。所有任务的候选顺序为 DeepSeek、Mock；这只是配置准备，不表示 OCR、教学质量或视觉能力已经验证。

密钥只读取精确名称 `DeepSeek_ANTHROPIC_AUTH_TOKEN`，先查进程环境，Windows 下缺失时只查当前用户 `HKCU\Environment` 的同名值。其他平台须设置同名环境变量。不读取任何密钥文件，不复制密钥到路由或默认值文件。

在仓库根目录执行：

```powershell
uv run python tools/setup_deepseek.py
uv run python tools/setup_deepseek.py --check
uv run python tools/setup_deepseek.py --run-api
```

首次创建已忽略的 `config/model_routes.yaml`；已有文件原样保留，明确传 `--force` 才覆盖。执行前可自行备份已有配置。`--check` 只发一次 `GET /models`，超时 10 秒，不重试、不跟随重定向，仅输出状态和安全格式的模型 ID，不输出密钥、错误正文或原始异常。缺少密钥时失败关闭；这不是生成质量验收。

`--run-api` 在当前进程加载上述默认值与用户密钥，设置 `TUTOR_MODEL_ROUTES_PATH` 后启动既有本地 API。直接运行 `tools/run_dev_api.py` **不会**自动加载此默认值文件或 Windows 用户级新环境变量。已有本地路由会保留，因此其行为取决于已有文件，工具不会擅自关闭或启用其中的供应商。

新示例保留 `enabled: false`、`compliance_approved: false` 和空报价；即使鉴权成功，正式学生流程仍使用 Mock/规则降级。正式外部调用仍需环境开关、供应商启用、Q-07 合规审批、已核验报价及正确环境配置共同满足，工具不会伪造审批或价格。密钥存在不代表正式学生数据处理已经开启。

2026-11-16 已由主任务使用既有网关 adapter 完成一次无学生数据的自编方程 JSON 探针：Flash 返回 `linear_equation`，输入 253、输出 61 token，约 1078 ms。此证据仅说明当时鉴权与现有 adapter 的小型 JSON 调用成功，不代表网关正式流、视觉识别、教学质量或合规验收完成；本工具不额外重复计费探针。

2026-11-18 使用现有 OpenAI 兼容适配器对 DeepSeek Flash 发起一次自编 PNG 图片转写测试。正确读出图片中的方程 9x + 14 = 77，548 输入 token、152 输出 token，约 1328 ms。图片仅含自编题，未使用学生材料。此次验证覆盖供应商图片请求和 JSON 回包，项目的学校材料外调开关仍按 Q-04/Q-07 门控。

### 2026-11-18 图片小样回归

自编四张 PNG 覆盖方程、单位、多行文字、双栏和倾斜。从仓库根目录在 PowerShell 运行，下方命令只运行首批四个样例，每个样例调用一次 DeepSeek。

```powershell
$env:PYTHONPATH = 'services/ai_gateway'
uv run python tools/evaluate_deepseek_ocr_probe.py --case equation --case units --case two_columns --case tilted
```

按 Unicode NFKC 归一化并忽略空白后，四张图的转写文字均与参考文字一致。共使用 2272 输入 token、1218 输出 token，单张约 1.99 至 3.92 秒。样本均为自编英文印刷文字和公式，手写、完整密集试卷与学校材料正式业务仍待评测。

随后加入两张自编中文图片。倾斜物理题保留了数字、单位、标点与阅读顺序，568 输入 token、607 输出 token，约 4.05 秒。六行密集版面的函数和质量题在 800 输出 token 上限下返回不可用回包，调整小样上限至 1600 后逐字匹配，568 输入 token、1342 输出 token，约 6.55 秒。此调整仅用于评测脚本。运行中文小样可附加 `--case zh_physics --case zh_dense`。
