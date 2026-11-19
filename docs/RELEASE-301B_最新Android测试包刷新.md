# RELEASE-301B 最新Android测试包刷新

2026-11-17。已生成包含最新媒体ZIP下载、本机拍题恢复记录导出和摸底历史的Android profile测试包。未安装到设备、未发布，不代替运行时、手写笔或iPad验收。

## 产物与校验

| 项目 | 实际结果 |
|---|---|
| APK | `var/release301b-20261117/tutor-student-profile.apk` |
| 大小 | 89,806,160字节 |
| SHA-256 | `bec70624ada45789e230e8aebb284306762daf550a25073f8e989b59e9fb5dbd` |
| 应用标识 / 版本 | 原型com.example.tutor_student，0.1.0+1；未更改正式标识或版本方案 |
| SDK / ABI | min24、target/compile36；arm64-v8a、armeabi-v7a、x86_64 |
| 签名 | apksigner退出0，v2校验通过；测试证书SHA-256为`0b000505e1121b9c528badc3e4d0bab95f420f79a156027c31e532538f755c0d` |
| 与旧测试包比较 | 与RELEASE-301A留档测试包证书一致；没有读取设备已安装包证书，不能据此冒称覆盖安装成功 |
| ZIP与资源 | APK ZIP CRC通过；打包中文字体与当前源码SHA-256一致 |
| 编译内容 | arm64 AOT中确认媒体导出API、本机拍题导出范围、摸底历史API三个标记；回环API基地址已核对 |

原生清单仍声明INTERNET、READ_EXTERNAL_STORAGE和自身动态receiver权限，没有WRITE_EXTERNAL_STORAGE。保留既有权限，不把签名或清单验证解释为设备已授权保存/选图。

## 构建与源码对应

使用当前工作区的独立ASCII副本 `D:/tutor-native-refresh-20261117-ffwnkr9u`，没有重试已知会因中文路径失败的AOT构建，也没有覆盖旧产物。

353份Android/Flutter学生端、Dart契约包及公开Gradle启动文件记录于source-manifest.json；此次只刷新Android，不包含审核后台/Web归档。构建前后，工作区与副本的这353份文件均保持一致。HEAD和dirty状态已记录，包含未提交修改，不能仅凭HEAD重建本包，也不是完整供应链复现证明。

从允许的系统/工具链变量构造构建环境，没有继承供应商密钥变量，没有复制.env、本机设置或签名材料；单独生成仅含SDK/Flutter路径的local.properties。沿用现有全局测试签名材料，未创建正式签名。AOT中检查未包含指定供应商密钥变量名或直连端点；这不是对所有可能敏感字符串的完整静态审计。

执行既有工具链：

```text
flutter pub get --offline --enforce-lockfile
flutter build apk --profile --no-pub --dart-define=TUTOR_API_BASE=http://127.0.0.1:8000
apksigner verify --verbose --print-certs <ASCII路径APK>
aapt dump badging <ASCII路径APK>
```

离线锁定依赖、构建、签名和清单检查全部退出0，未升级依赖。检查在ASCII原产物上执行，交付副本摘要一致。完整工具链信息、命令阶段、源码清单、日志、摘要和签名公钥信息在 `var/release301b-20261117/`，主记录为status.json；执行脚本为 `var/release301b-refresh.py`。

file_saver的KGP未来兼容提示和Cupertino图标字体提示仍保留于构建日志，未为消除警告增添/升级依赖；目标设备实际渲染与文件保存仍待验证。已检查中文字体打包一致，不能因此推断所有平台字体运行时验收完成。

功能门禁对应MEDIA-301D：后端2929/141可选跳过、Flutter711、Dart286、后台432、实际浏览器下载34项和相关变异29+5项；这些不是本次重新运行的测试，应用/契约源码与已验证版本对应。契约源摘要和功能证据引用已加入构建记录。

## 设备与后续

构建前后ADB设备列表均为空，最终检查时间保存在status.json及adb-devices-after-build.log。没有执行adb install、清空数据、卸载、启动或读写平板；没有把APK元数据当作KRJ-W09兼容/延迟/压力/手掌误触证明。已知用户没有手写笔，iPad和签名环境也未就绪。

实际连接已授权KRJ-W09后，再核对设备身份与解锁状态、原包签名、保留数据的更新安装及`adb reverse tcp:8000 tcp:8000`，联调最新本地API，实测新功能/离线恢复/文件保存取消。连接与安装条件未满足时继续其他独立工程任务，不删除原草稿或伪报通过。

下一可独立推进的工程项是受控MySQL/Redis与本机S3的只读生命周期接线调查。当前managed配置明确只接FilesystemBlobStore，健康检查只stat媒体root；业务媒体接口仍501、prod仍禁止，扩展演练必须保持这些边界，不因本机构建选择生产供应商或冻结Q-03/Q-07。
