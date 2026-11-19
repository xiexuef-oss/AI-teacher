# RELEASE-301A 本地测试构建产物

后续RELEASE-301B已单独刷新最新Android profile测试包并校验证书/源码/编译标记，见对应专篇；本页保留原Android和Web归档记录，不将旧Web归档冒称最新源码产物。

2026-11-17，已生成当前学生端/审核后台本地测试构建，包含学习记录导出、首次学习入口和知识点选题。没有上传、部署、生成正式签名或安装到设备。

| 产物 | 路径 | 实际校验 |
|---|---|---|
| Android profile APK | `var/release301-20261117/tutor-student-profile.apk` | 89,216,188字节；apksigner退出0、v2签名校验通过；aapt读取清单 |
| 学生Web归档 | `var/release301-20261117/student-web.zip` | 15,672,836字节、60文件；成员清单/SHA-256及ZIP CRC通过 |
| 审核后台Web归档 | `var/release301-20261117/admin-web.zip` | 1,072,317字节、63文件；成员清单/SHA-256及ZIP CRC通过 |

APK SHA-256：`63639a16f5b27ffb388ec4e5e3b8f846803018fba8e689d1c45e769d87315bc3`。

完整摘要及签名证书公钥指纹见 `artifacts.json`，Web每个成员的摘要见 `web-artifacts.json`。这些文件与工具链/构建日志均在同一产物目录。签名验证表示文件签名有效，不代表正式发布身份或渠道审核通过。

## 构建与源码对应

执行命令：学生端 `flutter build apk --profile --dart-define=TUTOR_API_BASE=http://127.0.0.1:8000`、`flutter build web --release`，后台 `npm run build`。Flutter 3.47.9、Dart 3.13.7（完整引擎修订见flutter-toolchain.json）；Node v22.18.0、npm10.9.3；Gradle wrapper声明9.3.1，APK清单compile/target SDK36，检查工具为build-tools36.0.0。未升级依赖或替换SDK。

`source-manifest.json`记录420份项目源文件的SHA-256、当前HEAD和worktree_dirty=true；此次源码包含未提交改动，不能仅以HEAD重建本产物。它不包含Git忽略的缓存、本机配置或签名材料，不能作为完整可复现构建/供应链证明。构建完成后，原目录与ASCII副本的这420份文件全部仍与构建前记录一致，结果见artifacts.json。

原目录Android profile构建在AOT读取中文路径时失败，保留android-profile-build.log。改用ASCII路径同源码副本后成功，见android-profile-ascii-build.log与native-build-stage.json。副本为 `D:/tutor-native-build-20261117-ba4f19b0`，没有覆盖原仓库或复制私钥。aapt也不接受本机中文路径，因此在ASCII原产物上检查；交付副本与原产物SHA-256一致。

## 原生清单与待验收

- applicationId仍是原型 `com.example.tutor_student`，版本0.1.0+1，profile测试签名；正式标识/签名由负责人提供。
- 最低SDK24；native-code包含arm64-v8a、armeabi-v7a、x86_64。当前没有连接的USB设备，未由这些元数据推断KRJ-W09安装或性能验收通过。
- APK声明INTERNET、READ_EXTERNAL_STORAGE和自身动态receiver权限；WRITE_EXTERNAL_STORAGE不存在。读取存储权限来自现有依赖/合并清单，不能声称本包完全没有存储权限。图库选择、JSON保存/取消/分享仍待目标Android/iOS实机复验。
- API基地址是回环 `http://127.0.0.1:8000`。Android本地联调使用 `adb reverse tcp:8000 tcp:8000`；实际API连接、冷启动、旋转、后台、离线新增笔迹及新功能须在本包安装后验证。不会因此启用真实身份或外部模型。
- 既有file_saver KGP未来兼容、图标字体及后台chunk大小构建警告保留于日志，本轮没有为消除警告升级依赖。构建成功不代替运行时、真机、远端CI或正式渠道验收。

当前功能证据见LEARN-301A与DATA-303B专篇；后端最新全量2669通过/120可选环境跳过。各条专项与设备证据继续按实际范围记录，不把本产物视为项目全部完成。
