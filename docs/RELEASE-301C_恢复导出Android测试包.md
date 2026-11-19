# RELEASE-301C 恢复导出Android测试包

2026-11-17，本地profile测试包已构建并核验，包含DATA-303F/G/H/I资料/授权/辅导复测、练习命令与分支、模型用量响应和独立题面缓存导出增量。功能测试证据见各增量专篇，包内标记核对不能代替真机验收。

- 文件：var/release301c-20261117/tutor-student-profile.apk，90,101,072字节。
- SHA-256：20fb5bbf709430e1ea9cbb0b7db9cc939a0d00778a4c59c3af694a823ea65de5。
- com.example.tutor_student，0.1.0+1；minSDK24、targetSDK36；arm64-v8a、armeabi-v7a、x86_64。
- API地址http://127.0.0.1:8000；后续USB连接仍需本地API及设备反向端口配置。本轮没有启动服务或安装应用。

复用前一轮构建脚本，在独立英文路径复制358份客户端源码及公开Gradle引导文件，离线安装锁定依赖，profile构建完成。构建子进程使用环境白名单，不继承供应商凭据；没有读取、打包或上传题库原卷及签名材料。358份源码在主目录及隔离目录构建前后相同，构建结果复制后摘要相同。

签名工具验证v2签名，测试证书与留档RELEASE-301A/B相同；没有比对设备现有签名，也不是正式发布签名验收。aapt包信息、ZIP CRC校验、API地址编译标记、供应商端点与密钥变量未进入AOT、三个ABI及中文字体字节一致性通过。另核对local_student_recovery_records、question_cache、model_usage、creation_commands、write_commands与学习记录导出路径确实进入arm64 AOT。证据在同目录status.json、source-manifest.json、additional-verification.json及原始构建/签名/aapt日志。

构建保留既有Kotlin插件迁移与CupertinoIcons字体警告；未趁机升级依赖或宣称警告全部消除。

构建前后adb devices -l均为空。未安装、卸载、清空设备数据或配置反向端口；未完成本包设备验收、长时书写、手写笔压力/防掌误触或iPad验收。此前KRJ-W09首轮测试仅作为旧版本历史证据。
