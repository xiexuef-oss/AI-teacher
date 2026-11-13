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
    // 和真服务端一样：幂等键只能是 8~128 位的字母、数字和 . _ : -。
    // 浏览器联调里发现过客户端把用户输入（带空格的邀请码）拼进了键，服务端 400；假后端不检查就看不出来
    final idempotencyKey = headers['Idempotency-Key'];
    if (idempotencyKey != null &&
        !RegExp(r'^[A-Za-z0-9._:-]{8,128}$').hasMatch(idempotencyKey)) {
      return errorResponse(
        400,
        'invalid_idempotency_key',
        message: 'Idempotency-Key 应为 8~128 位的字母、数字或 . _ : -',
      );
    }
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

  /// 本地身份 Mock 被调用了几次（每次都是领一个新身份）。
  int identitiesCreated = 0;

  /// 测试里本地身份 Mock 发给家长的用户 ID。
  static const parentUserId = '99999999-9999-4999-8999-999999999999';

  /// 身份、资料、启动配置、今日任务、题目列表、复测、学情。
  void installAppBasics() {
    on('POST', '/dev/local-identities', (request) {
      identitiesCreated += 1;
      if (request.uri.queryParameters['role'] == 'parent') {
        return okResponse({
          ...fixtures.value('local_identity'),
          'user_id': parentUserId,
          'role': 'parent',
          'access_token': 'parent-token-for-tests-0000000000000000',
        }, status: 201);
      }
      return okResponse(fixtures.value('local_identity'), status: 201);
    });
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

  // ---------------------------------------------------------------- 家长周报与授权

  /// 家长是否已经绑定了学生（决定 GET /parents/students 返回什么）。
  bool parentLinked = true;

  /// 家长周报用哪个样例；[weeklyTweak] 可以在返回之前改动它（造样本够了、趋势不同等情形）。
  String weeklyFixture = 'parent_weekly';
  Map<String, dynamic> Function(Map<String, dynamic> weekly)? weeklyTweak;

  /// 让周报返回某个错误（状态码, 错误码）。
  (int, String)? weeklyError;

  /// 每次请求周报时带的 week_start（没带是 null）。
  final List<String?> weeklyWeeks = [];

  /// 学生一侧：现在有效的授权、还没被使用的邀请码，以及各个动作被调用了几次。
  List<Map<String, dynamic>> parentLinks = [];
  Map<String, dynamic>? pendingInvite;
  int invitesCreated = 0;
  int revokes = 0;
  int redeems = 0;

  /// 家长与学生两侧的接口。响应取自真实样例。邀请码 ZZZZZZZZZZ 永远是错的。
  void installParentFlow() {
    on(
      'GET',
      '/parents/students',
      (_) => okResponse(
        fixtures.value(
          parentLinked ? 'parent_students' : 'parent_students_none',
        ),
      ),
    );
    on('POST', '/parents/links', (request) {
      redeems += 1;
      final code = (bodyOf(request)!['code'] as String)
          .replaceAll(RegExp(r'[\s-]'), '')
          .toUpperCase();
      if (code == 'ZZZZZZZZZZ' || code.length != 10) {
        return errorResponse(404, 'invite_invalid', message: '邀请码不对');
      }
      if (parentLinked) return errorResponse(409, 'already_linked');
      parentLinked = true;
      return okResponse(fixtures.value('parent_link_created'), status: 201);
    });
    on('GET', '/parents/students/[^/]+/weekly', (request) {
      weeklyWeeks.add(request.uri.queryParameters['week_start']);
      final error = weeklyError;
      if (error != null) return errorResponse(error.$1, error.$2);
      final value = fixtures.value(weeklyFixture);
      return okResponse(weeklyTweak == null ? value : weeklyTweak!(value));
    });
    on(
      'GET',
      '/me/parent-links',
      (_) =>
          okResponse({'links': parentLinks, 'pending_invite': pendingInvite}),
    );
    on('POST', '/me/parent-invites', (_) {
      invitesCreated += 1;
      final invite = fixtures.value('parent_invite');
      pendingInvite = {
        'id': invite['id'],
        'created_at': invite['created_at'],
        'expires_at': invite['expires_at'],
      };
      return okResponse(invite, status: 201);
    });
    on('POST', '/me/parent-links/[^/]+/revoke', (request) {
      revokes += 1;
      final segments = request.uri.pathSegments;
      final id = segments[segments.length - 2];
      final link = parentLinks.firstWhere((l) => l['id'] == id);
      parentLinks = parentLinks.where((l) => l['id'] != id).toList();
      return okResponse({...link, 'revoked_at': '2026-11-10T08:00:00Z'});
    });
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

  /// 解答题提交后的自评：服务端按要点清单的顺序存下来的那一份。
  List<Map<String, dynamic>> selfCheckMarks = [];

  /// 解答题的自查：要点来自真实样例，自评与计数按已保存的内容算（与服务端的算法一致）。
  Map<String, dynamic> selfCheck() {
    final base = fixtures.value('self_check_pending');
    final points = base['points'] as List<dynamic>;
    final counts = {'done': 0, 'partial': 0, 'missed': 0};
    for (final mark in selfCheckMarks) {
      final level = mark['level'] as String;
      counts[level] = counts[level]! + 1;
    }
    return {
      ...base,
      'marks': selfCheckMarks,
      'summary': {...counts, 'total': points.length},
      'saved_at': selfCheckMarks.isEmpty ? null : '2026-11-10T08:10:00Z',
    };
  }

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
      selfCheckMarks = [];
      return okResponse(attempt, status: 201);
    });
    on(
      'GET',
      '/attempts/[^/]+/self-check',
      (_) => submitted
          ? okResponse(selfCheck())
          : errorResponse(409, 'attempt_not_submitted'),
    );
    on('PUT', '/attempts/[^/]+/self-check', (request) {
      if (!submitted) return errorResponse(409, 'attempt_not_submitted');
      final marks = (bodyOf(request)!['marks'] as List<dynamic>)
          .cast<Map<String, dynamic>>();
      final keys = (fixtures.value('self_check_pending')['points'] as List)
          .map((p) => (p as Map<String, dynamic>)['key'])
          .toSet();
      // 与服务端一样：每个要点恰好评一次
      if (marks.length != keys.length ||
          !marks.every((m) => keys.contains(m['point_key']))) {
        return errorResponse(422, 'validation_error');
      }
      selfCheckMarks = marks;
      return okResponse(selfCheck());
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
