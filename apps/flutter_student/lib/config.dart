/// 后端地址。构建或运行时用 `--dart-define=TUTOR_API_BASE=http://...` 覆盖。
///
/// 默认指向本机的开发 API（tools/run_dev_api.py）。Android 模拟器访问宿主机要用
/// `http://10.0.2.2:8000`；真机要用电脑的局域网地址——但本地身份 Mock 只接受回环地址的请求，
/// 所以真机联调需要先换掉身份方案（DECISIONS_PENDING Q-03）。
const String apiBaseUrl = String.fromEnvironment(
  'TUTOR_API_BASE',
  defaultValue: 'http://127.0.0.1:8000',
);
