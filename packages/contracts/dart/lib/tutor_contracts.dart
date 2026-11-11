/// AI 理科私教的 API 契约（Dart）。
///
/// 模型、客户端、教学事件 payload 和图解模板表都由 `tools/gen_dart_contracts.py`
/// 根据仓库根目录的 `contracts/` 生成；`runtime.dart` 是手写的传输层。
library;

export 'src/client.g.dart';
export 'src/event_payloads.g.dart';
export 'src/models.g.dart';
export 'src/runtime.dart';
export 'src/visual_templates.g.dart';
