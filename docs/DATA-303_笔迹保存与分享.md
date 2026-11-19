# DATA-303 笔迹PNG保存与分享

状态：工程实现和平台构建已完成，原生保存/分享真机验收仍待设备；完整学生数据导出不是本工作包。

草稿导出仍先在本机生成PNG预览，用户再明确选择“保存文件”或“系统分享”。生成及系统交接期间禁止重复点击和关闭；取消、失败有独立反馈，失败不清空当前草稿，不假称已经落盘。Web仅反馈已发起下载，浏览器下载完成与最终保存位置由用户确认。

Android/iOS走系统文档选择器及分享面板，不申请广泛存储/相册权限，不自动向联系人发送；原始草稿不上传云端。iPad分享传递有效origin。包锁为share_plus13.3.1与file_saver0.4.0：较新file_saver版本的meta依赖与本机Flutter SDK固定版本不兼容，使用已核对接口和实现的可解析版本；不声称升级过本机Flutter。

图片逐页竖向拼接，最多20页全部保留；长稿自适应缩小宽度，限制总像素24MP及高度16000，异常尺寸拒绝。Picture/Image在finally释放；对话框关闭清除本模块内存预览与字节引用。share_plus仍可能在应用缓存生成临时PNG，系统或接收端的缓存生命周期不由本模块保证，不承诺离页即删除或对方已保存。生产留存和全副本清理仍待Q-07。

## 已执行证据

先因缺少导出dialog红测，再实现。相关ink/controller/solve页面112项通过；导出专项5项通过，包含真实20页PNG解码（571×15988）、取消、错误、busy防重复以及多页拼接。预览旧测试按新生成生命周期增加pump后通过；初始失败和修复结果均保留，不通过改产品同步行为迁就测试。

相关日志由原临时目录复制保留到var/data303-ink-tests.log、data303-ink-export-tests.log、data303-ink-adaptive-red.log、data303-ink-apk-build.log和data303-ink-web-build.log。

初轮Android debug/Web release构建通过，后续20页自适应及PHOTO301修补整合后再次构建通过（var/photo301-web-fix-build.log、photo301-web-fix-apk-build.log）。最新完整学生端413项及统一九门禁全部通过。没有运行iOS构建，也没有设备上的文件保存、分享取消或接收端验收；Widget/mock与成功编译不能代替这些实测。
