/// 后端地址。构建或运行时用 `--dart-define=TUTOR_API_BASE=http://...` 覆盖。
///
/// 默认指向本机的开发 API（tools/run_dev_api.py）。Android 模拟器访问宿主机要用
/// `http://10.0.2.2:8000`。Android 真机可先执行 `adb reverse tcp:8000 tcp:8000`，
/// 再以默认回环地址联调本地身份 Mock；真实身份方案仍按 DECISIONS_PENDING Q-03 冻结。
const String apiBaseUrl = String.fromEnvironment(
  'TUTOR_API_BASE',
  defaultValue: 'http://127.0.0.1:8000',
);
