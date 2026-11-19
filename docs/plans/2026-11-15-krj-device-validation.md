# KRJ-W09 首轮真机验证记录

日期：2026-11-15。状态：debug/profile 均已安装运行；短草稿离线新增、重启恢复、同步与横竖屏/大字体检查通过。长时间书写与手写笔体验尚未验收。

## 设备与连接

- 荣耀 KRJ-W09，系统构建 `KRJ-W09 2.0.0.275(C00E165R1P165)`（用户提供 HarmonyOS 2.0.0）。
- ADB 报告 Android 10 / API 29，支持 arm64-v8a，屏幕 1200×2000、密度 320。
- USB 调试已授权；使用 `adb reverse tcp:8000 tcp:8000` 连接电脑的本地 API。
- 用户确认没有手写笔；笔延迟、压力与手掌误触待配笔后验证。本轮先检查手指输入和功能恢复。

## 已完成的环境准备

- 本次命令使用 Windows 已配置的本地代理，恢复 Dart/Flutter 依赖；代理仅通过进程环境变量传递，不写入仓库配置。
- 安装 Android Command-line Tools 20、SDK Platform 36 revision 2、NDK 28.2.13676358。
  下载文件来自 Android 官方仓库，按官方清单校验大小及 SHA-1；Gradle 9.3.1 按官方 SHA-256 校验。
- Android Gradle 插件拒绝中文路径，项目增加 `android.overridePathCheck=true` 后继续实际构建验证。
- Kotlin 增量缓存无法处理仓库 D 盘与 Pub 缓存 C 盘的相对路径，设置 `kotlin.incremental=false` 后 debug 构建通过。
- profile 的 AOT 编译器仍无法读取中文路径；英文路径 Junction 会被还原为原路径，未解决该问题，已移除。
  将应用和契约源码复制到 `D:/tutor-device-stage-20261115` 后 profile 构建通过。
  回拷 APK 前比对了 49 份源码/资源文件，以及 pubspec、锁文件、Gradle 配置和主 Manifest，内容一致。
- CMake 3.22.1 由构建器安装完成。构建提示 CupertinoIcons 字体未包含，相关界面显示待实机检查。
- Flutter 学生端 372 项测试通过（含本轮新增回归），Dart 契约包 155 项测试通过，学生端 `dart analyze` 无问题。
- `flutter doctor` 已识别平板及 Android 工具链，仍提示部分 Android 许可证未接受；本记录不代表所有可选 SDK 组件均可用。

## 实机验收清单

| 项目 | 状态 | 说明 |
|---|---|---|
| ARM64 APK 构建 | 通过 | 修正提示后的 debug 97,032,121 字节；profile 45,282,669 字节 |
| USB 安装、启动 | 通过（debug） | 用户解锁后安装成功，应用正常启动；未清除应用数据 |
| profile 安装、启动 | 通过 | 同一签名覆盖安装，保留原有身份与数据；AOT 应用正常启动并加载本地 API |
| 引导与真实本地 API 联通 | 通过 | 完成引导、加载今日任务和题目，观察到提交后反馈；本地身份 Mock，非正式账号 |
| 选项作答与切后台保存 | 通过 | 物理样题选 B，按 Home 后本机 SharedPreferences 中保留该答案 |
| 强制终止后重开恢复 | 通过（短草稿） | force-stop 后重开，临时移除 API 端口转接，再进入物理题；B 与两条手指笔迹均恢复，未清除数据 |
| 笔迹保存与恢复 | 通过（两条真实手指笔迹） | 用户实际画线；本机草稿约 1260 字节，重启和更新 APK 后逐字段比较 answer、strokes 完全一致 |
| 断网与恢复同步 | 通过（已有短草稿） | 离线显示缓存题与未同步提示；恢复端口转接、重试后 dirty=false、baseRevision=4，界面已同步；后续 profile 离线新增测试见下一行 |
| profile 离线新增答案和笔迹 | 通过（短草稿） | 断开 API 转接后输入数学填空 4，用户再画两条线；本机 dirty=true，序列化草稿约 4.7 KB；旋转与强退后 answer/strokes 逐字段一致，联网后 dirty=false、baseRevision=1 |
| 10 分钟连续手写 | 待测 | 需实际手写笔，记录草稿体积与恢复情况 |
| 延迟、压力、手掌误触 | 待测 | 性能验收使用 profile 构建，debug 表现不作为最终结论 |
| 横竖屏与系统大字体 | 通过（当前样题） | profile 数学填空页在竖屏 1200×2000、横屏 2000×1200 和 1.5 倍字体下，题干、公式、按钮可显示；长内容可滚动；两条笔迹坐标数据不变，未发现溢出或崩溃；不是所有页面的全面验收 |

## 本地复现

从仓库根目录启动 `uv run python tools/run_dev_api.py`，API 保持只监听 127.0.0.1。
USB 连接并授权后，在电脑执行 Android SDK 的 `platform-tools/adb.exe reverse tcp:8000 tcp:8000`。
在 `apps/flutter_student` 下运行 `C:\src\flutter\bin\flutter.bat build apk --debug --no-pub --target-platform android-arm64`。
首次构建需网络可达；如使用代理，HTTP_PROXY、HTTPS_PROXY 和 Gradle 的代理参数需按本机实际配置传入。
代理地址和端口不作为项目固定配置。断开 USB 后需重新确认设备授权与端口转接。

profile 包在上述英文临时目录执行 `flutter pub get` 后，用
`C:\src\flutter\bin\flutter.bat build apk --profile --no-pub --target-platform android-arm64` 构建。
临时目录保留本轮源码快照，不会自动跟随仓库更新；再次构建前须重新同步并校验源码。
两个包均位于仓库 `apps/flutter_student/build/app/outputs/flutter-apk/`，未提交到 Git。

- debug SHA-256：`36392074a94e68d61cadc35c97e6660e2757e5dbd8c109ede66ab1e2173bcc56`。
- profile SHA-256：`6a4c69c7c4bc4ea7dd34a1a7c947177bd79ed900347a10f807111f7648c2f3dd`。

## 联调发现并修复

离线使用缓存题后，即使草稿已经同步，原来的“没有网络”缓存提示仍留在页面，与顶栏“已同步”矛盾。
现在仅在缓存题且同步状态为 offline 时显示该提示。新增 widget 测试先复现失败，再修改页面条件；
372 项测试、静态检查及 debug/profile 构建通过。更新安装后再次移除/恢复端口转接，实机确认离线提示消失，
答案与两条笔迹未变化。未调整同步协议、幂等、归属或判题规则。

截图保存在被 Git 忽略的 `var/tutor-before.png`、`var/tutor-after.png`、`var/tutor-offline-fixed.png`、
`var/tutor-final.png`（第一轮 debug）。后续 profile 验证截图：`var/tutor-portrait-large.png`、
`var/tutor-profile-ink-landscape.png`、`var/tutor-profile-ink-restart.png`、`var/tutor-profile-final.png`。
当前平板运行 profile 包，停留在未提交的数学填空样题，测试答案 4 与两条手指笔迹保留，USB API 转接已恢复。
旋转自动开关、方向值、font_scale 均逐项恢复并核对为本轮开始前的值。

本轮 profile 检查没有新增业务代码，沿用此前 372 项 Flutter 测试通过的构建。
未将短线条测试或普通页面操作计为 10 分钟连续书写，也没有测量端到端笔延迟、压力或手掌误触。
