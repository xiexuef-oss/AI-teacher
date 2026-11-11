import 'dart:convert';
import 'dart:io';

import 'package:tutor_contracts/tutor_contracts.dart';

/// 服务端真实返回的样例（tools/export_dart_fixtures.py 导出，Dart 契约包的测试也用同一份）。
class Fixtures {
  Fixtures._(this._dir);

  factory Fixtures.load() =>
      Fixtures._(Directory('../../packages/contracts/dart/test/fixtures'));

  final Directory _dir;
  final Map<String, Map<String, dynamic>> _cache = {};

  Map<String, dynamic> _file(String name) => _cache.putIfAbsent(
    name,
    () =>
        jsonDecode(File('${_dir.path}/$name.json').readAsStringSync())
            as Map<String, dynamic>,
  );

  /// 成功响应里的 data，或错误响应的整个信封。每次返回深拷贝，测试里可以随便改。
  Map<String, dynamic> value(String name) =>
      jsonDecode(jsonEncode(_file(name)['value'])) as Map<String, dynamic>;

  int status(String name) => _file(name)['status'] as int;
}

typedef Seen = ({
  String method,
  Uri uri,
  Map<String, String> headers,
  String? body,
});
typedef Handler = RawResponse Function(Seen request);

RawResponse okResponse(
  Object data, {
  int status = 200,
  Map<String, String> headers = const {},
}) => RawResponse(
  statusCode: status,
  body: jsonEncode({'data': data}),
  headers: headers,
);

RawResponse errorResponse(
  int status,
  String code, {
  String message = '出错了',
  Map<String, dynamic> details = const {},
}) => RawResponse(
  statusCode: status,
  body: jsonEncode({
    'error': {
      'code': code,
      'message': message,
      'details': details,
      'request_id': 'req-test',
    },
  }),
);

/// 一个够用的假后端：按 "方法 + 路径正则" 路由，后注册的优先；
/// 另外带一个会话/作答/草稿/提交/辅导的小型状态机（[installLearningFlow]），
/// 响应内容取自真实样例，所以形状与服务端一致。
class FakeBackend implements ApiTransport {
  FakeBackend() : fixtures = Fixtures.load();

  final Fixtures fixtures;
  final List<Seen> requests = [];
  final List<(String, RegExp, Handler)> _routes = [];

  /// 为 true 时所有请求都像断网一样失败。
  bool offline = false;

  /// 让下一次请求以这个状态码和错误码失败（只生效一次）。
  (int, String)? failNext;

  /// 让下一次路径匹配 [pattern] 的请求失败（只生效一次），其他请求照常。
  (RegExp, int, String)? _failNextMatching;

  void failNextOn(String pattern, int status, String code) =>
      _failNextMatching = (RegExp(pattern), status, code);

  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    if (offline) throw const SocketException('模拟断网');
    final seen = (method: method, uri: uri, headers: headers, body: body);
    requests.add(seen);
    final fail = failNext;
    if (fail != null) {
      failNext = null;
      return errorResponse(fail.$1, fail.$2);
    }
    final matching = _failNextMatching;
    if (matching != null && matching.$1.hasMatch(uri.path)) {
      _failNextMatching = null;
      return errorResponse(matching.$2, matching.$3);
    }
    for (final (m, pattern, handler) in _routes.reversed) {
      if (m == method && pattern.hasMatch(uri.path)) return handler(seen);
    }
    return errorResponse(404, 'not_found', message: '资源不存在');
  }

  void on(String method, String path, Handler handler) =>
      _routes.add((method, RegExp('^/api/v1$path\$'), handler));

  /// 返回某个样例的响应。
  void onFixture(String method, String path, String name) =>
      on(method, path, (_) {
        final status = fixtures.status(name);
        return status >= 200 && status < 300
            ? okResponse(fixtures.value(name), status: status)
            : RawResponse(
                statusCode: status,
                body: jsonEncode(fixtures.value(name)),
              );
      });

  Iterable<Seen> requestsTo(String method, String pathPattern) =>
      requests.where(
        (r) => r.method == method && RegExp(pathPattern).hasMatch(r.uri.path),
      );

  Map<String, dynamic>? bodyOf(Seen request) => request.body == null
      ? null
      : jsonDecode(request.body!) as Map<String, dynamic>;

  // ---------------------------------------------------------------- 应用级接口

  /// 资料用哪个样例：profile_saved（已完成引导）或 profile_empty（首次使用）。
  String profileFixture = 'profile_saved';

  /// 在 [installAppBasics] 之后，PUT /profile 收到的最后一份请求体。
  Map<String, dynamic>? lastProfileUpdate;

  /// 身份、资料、启动配置、今日任务、题目列表、复测、学情。
  void installAppBasics() {
    on(
      'POST',
      '/dev/local-identities',
      (_) => okResponse(fixtures.value('local_identity'), status: 201),
    );
    on(
      'GET',
      '/meta/launch-config',
      (_) => okResponse(fixtures.value('launch_config')),
    );
    on('GET', '/profile', (_) => okResponse(fixtures.value(profileFixture)));
    on('PUT', '/profile', (request) {
      lastProfileUpdate = bodyOf(request);
      profileFixture = 'profile_saved';
      return okResponse(fixtures.value('profile_saved'));
    });
    onFixture('GET', '/tasks/today', 'tasks_today');
    onFixture('GET', '/questions', 'questions_page');
    onFixture('GET', '/reviews/due', 'reviews_all');
    onFixture('GET', '/progress/summary', 'progress_summary');
  }

  // ---------------------------------------------------------------- 学习流程

  int serverRevision = 0;
  Map<String, dynamic>? serverAnswer;
  Map<String, dynamic>? serverStrokes;
  bool submitted = false;

  /// 提交时返回哪个样例（submit_correct / submit_incorrect / submit_uncertain）。
  String submitFixture = 'submit_incorrect';
  int sessionsCreated = 0;
  int attemptsCreated = 0;

  /// 最近一次开会话时请求里的类型，会话查询时原样回显。
  String sessionOrigin = 'task';
  String? sessionReviewItem;

  /// 把会话 → 作答 → 草稿 → 提交 → 辅导这一整套接口装上。
  void installLearningFlow({
    String questionFixture = 'question_single_choice',
  }) {
    final session = fixtures.value('session_created');
    final attempt = fixtures.value('attempt_created');
    final sessionId = session['id'] as String;
    final attemptId = attempt['id'] as String;

    Map<String, dynamic> currentSession({String? state, bool open = true}) => {
      ...session,
      'origin': sessionOrigin,
      'review_item_id': sessionReviewItem,
      'state': state ?? (submitted ? 'DIAGNOSED' : 'INDEPENDENT_ATTEMPT'),
      'active_attempt_id': open && !submitted ? attemptId : null,
    };

    Map<String, dynamic> draft() => {
      'attempt_id': attemptId,
      'revision': serverRevision,
      'answer': serverAnswer,
      'strokes': serverStrokes,
      'updated_at': '2026-11-10T08:00:00Z',
    };

    onFixture('GET', '/questions/[^/]+', questionFixture);
    on('POST', '/sessions', (request) {
      sessionsCreated += 1;
      final body = bodyOf(request)!;
      sessionOrigin = body['origin'] as String;
      sessionReviewItem = body['review_item_id'] as String?;
      return okResponse({
        ...currentSession(state: 'READY', open: false),
      }, status: 201);
    });
    on('GET', '/sessions/[^/]+', (_) => okResponse(currentSession()));
    on('POST', '/attempts', (_) {
      attemptsCreated += 1;
      submitted = false;
      serverRevision = 0;
      serverAnswer = null;
      serverStrokes = null;
      return okResponse(attempt, status: 201);
    });
    on(
      'GET',
      '/attempts/[^/]+',
      (_) => okResponse({...attempt, 'draft_revision': serverRevision}),
    );
    on('GET', '/attempts/[^/]+/draft', (_) => okResponse(draft()));
    on('PUT', '/attempts/[^/]+/draft', (request) {
      final body = bodyOf(request)!;
      if (submitted) return errorResponse(409, 'attempt_already_submitted');
      if (body['base_revision'] != serverRevision) {
        return errorResponse(
          409,
          'draft_revision_conflict',
          details: {'server_revision': serverRevision, 'server_draft': draft()},
        );
      }
      serverRevision += 1;
      serverAnswer = body['answer'] as Map<String, dynamic>?;
      serverStrokes = body['strokes'] as Map<String, dynamic>?;
      return okResponse(draft());
    });
    on('POST', '/attempts/[^/]+/submit', (_) {
      submitted = true;
      final result = fixtures.value(submitFixture);
      (result['attempt'] as Map<String, dynamic>)['id'] = attemptId;
      (result['session'] as Map<String, dynamic>)['id'] = sessionId;
      return okResponse(result);
    });
    on(
      'GET',
      '/sessions/[^/]+/events',
      (_) => okResponse({'items': <Object>[], 'last_seq': 0}),
    );
    on('POST', '/tutor/sessions/[^/]+/next', (request) {
      final action = bodyOf(request)!['action'] as String;
      final confirmed = bodyOf(request)!['confirm_end_independent'] == true;
      final name = switch (action) {
        'request_hint' => 'tutor_hint',
        'request_visual' => 'tutor_visual',
        'request_standard' => 'tutor_standard',
        'request_fast' => 'tutor_fast',
        'mark_confused' => 'tutor_rephrase_model',
        _ => 'tutor_understood',
      };
      if ((action == 'request_standard' || action == 'request_fast') &&
          !submitted &&
          !confirmed) {
        return RawResponse(
          statusCode: 409,
          body: jsonEncode(fixtures.value('tutor_standard_needs_confirmation')),
        );
      }
      return okResponse(fixtures.value(name));
    });
    on(
      'POST',
      '/reviews/[^/]+/complete',
      (_) => okResponse(fixtures.value('review_completed')),
    );
  }
}
