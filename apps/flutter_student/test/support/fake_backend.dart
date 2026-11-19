import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';

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
  final _writeReceipts = <String, ({String? body, RawResponse response})>{};

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
      if (m == method && pattern.hasMatch(uri.path)) {
        final durable =
            idempotencyKey != null &&
            RegExp(
              r'/(attempts/[^/]+/(draft|submit|self-check)|tutor/sessions/[^/]+/next|reviews/[^/]+/complete)$',
            ).hasMatch(uri.path) &&
            method != 'GET';
        final receiptKey = '$method:${uri.path}:$idempotencyKey';
        final receipt = durable ? _writeReceipts[receiptKey] : null;
        if (receipt != null) {
          if (receipt.body != body) {
            return errorResponse(409, 'idempotency_conflict');
          }
          return receipt.response;
        }
        final response = handler(seen);
        if (durable &&
            response.statusCode >= 200 &&
            response.statusCode < 300) {
          _writeReceipts[receiptKey] = (body: body, response: response);
        }
        return response;
      }
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
  final _studentOwners = <String, String>{};
  void bindStudentIdentity(String token, String owner) {
    _studentOwners['Bearer $token'] = owner;
  }

  final _profiles = <String, Map<String, dynamic>>{};
  final _profileReceipts = <String, ({String? body, RawResponse response})>{};

  Map<String, dynamic> _profileFor(Seen request) {
    final token = request.headers['Authorization'] ?? '';
    return _profiles.putIfAbsent(token, () {
      final value = fixtures.value(profileFixture);
      if (_studentOwners.containsKey(token)) {
        value['user_id'] = _studentOwners[token];
      }
      value['revision'] ??= profileFixture == 'profile_empty' ? 0 : 1;
      return value;
    });
  }

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
    on('GET', '/profile', (request) => okResponse(_profileFor(request)));
    on('PUT', '/profile', (request) {
      final key = request.headers['Idempotency-Key'];
      if (key == null) return errorResponse(400, 'missing_idempotency_key');
      final receiptKey = '${request.headers['Authorization']}/$key';
      final receipt = _profileReceipts[receiptKey];
      if (receipt != null) {
        return receipt.body == request.body
            ? receipt.response
            : errorResponse(409, 'idempotency_key_reused');
      }
      lastProfileUpdate = bodyOf(request);
      final current = _profileFor(request);
      if (lastProfileUpdate!['expected_revision'] != current['revision']) {
        return errorResponse(
          409,
          'profile_revision_conflict',
          details: {'server_profile': current},
        );
      }
      final updated = {
        ...fixtures.value('profile_saved'),
        ...lastProfileUpdate!,
        'user_id': current['user_id'],
        'revision': (current['revision'] as int) + 1,
      }..remove('expected_revision');
      final response = okResponse(updated);
      _profiles[request.headers['Authorization'] ?? ''] = updated;
      _profileReceipts[receiptKey] = (body: request.body, response: response);
      profileFixture = 'profile_saved';
      return response;
    });
    onFixture('GET', '/tasks/today', 'tasks_today');
    onFixture('GET', '/questions', 'questions_page');
    onFixture('GET', '/questions/topics', 'question_topics');
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
  int parentInviteRevision = 0;
  final _parentReceipts = <String, ({String? body, RawResponse response})>{};
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
    Map<String, dynamic> currentLinks() => {
      'links': parentLinks,
      'pending_invite': pendingInvite,
      'parent_invite_revision': parentInviteRevision,
    };
    on('GET', '/me/parent-links', (_) => okResponse(currentLinks()));
    RawResponse? replay(Seen request) {
      final key =
          '${request.headers['Authorization']}/${request.uri.path}/${request.headers['Idempotency-Key']}';
      final old = _parentReceipts[key];
      return old == null
          ? null
          : old.body == request.body
          ? old.response
          : errorResponse(409, 'idempotency_key_reused');
    }

    RawResponse remember(Seen request, RawResponse response) {
      final key =
          '${request.headers['Authorization']}/${request.uri.path}/${request.headers['Idempotency-Key']}';
      _parentReceipts[key] = (body: request.body, response: response);
      return response;
    }

    on('POST', '/me/parent-invites', (request) {
      final old = replay(request);
      if (old != null) return old;
      if (bodyOf(request)!['expected_parent_invite_revision'] !=
          parentInviteRevision) {
        return errorResponse(
          409,
          'parent_invite_revision_conflict',
          details: {'server_parent_links': currentLinks()},
        );
      }
      invitesCreated++;
      parentInviteRevision++;
      final invite = fixtures.value('parent_invite')
        ..['parent_invite_revision'] = parentInviteRevision;
      pendingInvite = {
        'id': invite['id'],
        'created_at': invite['created_at'],
        'expires_at': invite['expires_at'],
      };
      return remember(request, okResponse(invite, status: 201));
    });
    on('POST', '/me/parent-links/[^/]+/revoke', (request) {
      final old = replay(request);
      if (old != null) return old;
      final segments = request.uri.pathSegments;
      final id = segments[segments.length - 2];
      final link = parentLinks.firstWhere((l) => l['id'] == id);
      if (bodyOf(request)!['expected_authorization_revision'] !=
          link['authorization_revision']) {
        return errorResponse(
          409,
          'authorization_revision_conflict',
          details: {'server_link': link},
        );
      }
      revokes++;
      parentLinks = parentLinks.where((l) => l['id'] != id).toList();
      return remember(
        request,
        okResponse({
          ...link,
          'authorization_revision': (link['authorization_revision'] as int) + 1,
          'revoked_at': '2026-11-10T08:00:00Z',
        }),
      );
    });
  }

  // ---------------------------------------------------------------- 学习流程

  int serverRevision = 0;
  Map<String, dynamic>? serverAnswer;
  Map<String, dynamic>? serverStrokes;
  String? _learningAttemptId;
  bool submitted = false;
  Map<String, dynamic>? submittedAnswer;
  Map<String, dynamic>? submittedAttempt;
  final submittedAttempts = <String, Map<String, dynamic>>{};
  final submittedDrafts = <String, Map<String, dynamic>>{};
  final savedSelfChecks = <String, Map<String, dynamic>>{};
  bool usedSolution = false;
  bool sessionAssisted = false;
  int hintsRevealed = 0;
  String? learningState;
  final sessionEvents = <String, List<Map<String, dynamic>>>{};
  final sessionResources = <String, Map<String, dynamic>>{};
  final reviewStates = <String, Map<String, dynamic>>{};
  final reviewHistory = <String, Map<String, dynamic>>{};
  final reviewReady = <String, bool>{};
  Map<String, dynamic> reviewState(String id) => reviewStates.putIfAbsent(
    id,
    () => {
      ...fixtures.value('review_current_state'),
      'id': id,
      'question_id': fixtures.value('question_single_choice')['id'],
      'stage': 0,
      'status': 'scheduled',
      'last_result': null,
      'last_attempt_id': null,
      'due_at': '2026-11-01T08:00:00Z',
    },
  );

  /// 提交时返回哪个样例（submit_correct / submit_incorrect / submit_uncertain）。
  String submitFixture = 'submit_incorrect';
  int sessionsCreated = 0;
  int attemptsCreated = 0;

  /// 最近一次开会话时请求里的类型，会话查询时原样回显。
  String sessionOrigin = 'task';
  String? sessionReviewItem;

  /// 解答题提交后的自评：服务端按要点清单的顺序存下来的那一份。
  List<Map<String, dynamic>> selfCheckMarks = [];

  /// 自查用哪个样例：解答题是 self_check_pending，实验题是 self_check_experiment_pending（带参考数据）。
  String selfCheckFixture = 'self_check_pending';

  /// 解答题、实验题的自查：要点来自真实样例，自评与计数按已保存的内容算（与服务端的算法一致）。
  Map<String, dynamic> selfCheck() {
    final base = fixtures.value(selfCheckFixture);
    final points = base['points'] as List<dynamic>;
    final counts = {'done': 0, 'partial': 0, 'missed': 0};
    for (final mark in selfCheckMarks) {
      final level = mark['level'] as String;
      counts[level] = counts[level]! + 1;
    }
    return {
      ...base,
      'attempt_id': _learningAttemptId ?? base['attempt_id'],
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
    session['question_id'] = fixtures.value(questionFixture)['id'];
    final attempt = fixtures.value('attempt_created');
    final sessionId = session['id'] as String;
    var attemptId = attempt['id'] as String;
    _learningAttemptId = attemptId;

    Map<String, dynamic> currentSession({String? state, bool open = true}) => {
      ...session,
      'origin': sessionOrigin,
      'assisted': sessionAssisted,
      'used_solution': usedSolution,
      'independent_ended': usedSolution,
      'last_event_seq': sessionEvents[sessionId]?.length ?? 0,
      'first_submitted_attempt_id': submittedAttempts.values
          .where((a) => a['session_id'] == sessionId && a['submission_no'] == 1)
          .map((a) => a['id'])
          .firstOrNull,
      'submitted_attempts': submittedAttempts.values
          .where((a) => a['session_id'] == sessionId)
          .length,
      'hint_level_revealed': hintsRevealed,
      'review_item_id': sessionReviewItem,
      'state':
          state ??
          learningState ??
          (submitted ? 'DIAGNOSED' : 'INDEPENDENT_ATTEMPT'),
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
    onFixture('GET', '/questions/topics', 'question_topics');
    onFixture('GET', '/sessions/[^/]+/question', questionFixture);
    on('POST', '/sessions', (request) {
      sessionsCreated += 1;
      final body = bodyOf(request)!;
      sessionOrigin = body['origin'] as String;
      sessionReviewItem = body['review_item_id'] as String?;
      return okResponse({
        ...currentSession(state: 'READY', open: false),
      }, status: 201);
    });
    on('GET', '/sessions/[^/]+', (request) {
      final value =
          sessionResources[request.uri.pathSegments.last] ?? currentSession();
      return okResponse(
        submitted && value['state'] == 'INDEPENDENT_ATTEMPT'
            ? {...value, 'state': 'DIAGNOSED', 'active_attempt_id': null}
            : value,
      );
    });
    on('POST', '/attempts', (_) {
      attemptsCreated += 1;
      if (attemptsCreated > 1) {
        attemptId = 'test-attempt-$attemptsCreated';
        attempt['id'] = attemptId;
        attempt['attempt_no'] = attemptsCreated;
      }
      _learningAttemptId = attemptId;
      submitted = false;
      submittedAnswer = null;
      submittedAttempt = null;
      serverRevision = 0;
      serverAnswer = null;
      serverStrokes = null;
      selfCheckMarks = [];
      learningState = 'INDEPENDENT_ATTEMPT';
      sessionResources[sessionId] = currentSession();
      return okResponse(attempt, status: 201);
    });
    on(
      'GET',
      '/attempts/[^/]+/self-check',
      (request) =>
          request.uri.pathSegments[3] != attemptId &&
              savedSelfChecks.containsKey(request.uri.pathSegments[3])
          ? okResponse(savedSelfChecks[request.uri.pathSegments[3]]!)
          : submitted
          ? okResponse(selfCheck())
          : errorResponse(409, 'attempt_not_submitted'),
    );
    on('PUT', '/attempts/[^/]+/self-check', (request) {
      if (!submitted) return errorResponse(409, 'attempt_not_submitted');
      final marks = (bodyOf(request)!['marks'] as List<dynamic>)
          .cast<Map<String, dynamic>>();
      final keys = (fixtures.value(selfCheckFixture)['points'] as List)
          .map((p) => (p as Map<String, dynamic>)['key'])
          .toSet();
      // 与服务端一样：每个要点恰好评一次
      if (marks.length != keys.length ||
          !marks.every((m) => keys.contains(m['point_key']))) {
        return errorResponse(422, 'validation_error');
      }
      selfCheckMarks = marks;
      savedSelfChecks[attemptId] =
          jsonDecode(jsonEncode(selfCheck())) as Map<String, dynamic>;
      return okResponse(selfCheck());
    });
    on(
      'GET',
      '/attempts/[^/]+',
      (request) =>
          request.uri.pathSegments.last != attemptId &&
              submittedAttempts.containsKey(request.uri.pathSegments.last)
          ? okResponse(submittedAttempts[request.uri.pathSegments.last]!)
          : okResponse({
              ...attempt,
              ...?submittedAttempt,
              'draft_revision': serverRevision,
              'status': submitted ? 'submitted' : 'draft',
            }),
    );
    on(
      'GET',
      '/attempts/[^/]+/draft',
      (request) =>
          okResponse(submittedDrafts[request.uri.pathSegments[3]] ?? draft()),
    );
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
    on('POST', '/attempts/[^/]+/submit', (request) {
      if (submitted) return errorResponse(409, 'attempt_already_submitted');
      final body = bodyOf(request)!;
      if (body.containsKey('expected_draft_revision') &&
          body['expected_draft_revision'] != serverRevision) {
        return errorResponse(
          409,
          'submission_draft_revision_conflict',
          details: {
            'server_revision': serverRevision,
            'expected_draft_revision': body['expected_draft_revision'],
            'server_draft': draft(),
          },
        );
      }
      submitted = true;
      submittedAnswer = body['answer'] as Map<String, dynamic>;
      final result = fixtures.value(submitFixture);
      (result['attempt'] as Map<String, dynamic>)['id'] = attemptId;
      (result['attempt'] as Map<String, dynamic>)['session_id'] = sessionId;
      (result['attempt'] as Map<String, dynamic>)['answer'] = submittedAnswer;
      (result['attempt'] as Map<String, dynamic>)['submission_no'] =
          submittedAttempts.values
              .where((a) => a['session_id'] == sessionId)
              .length +
          1;
      (result['attempt'] as Map<String, dynamic>)['attempt_no'] =
          attemptsCreated;
      submittedAttempt = Map<String, dynamic>.from(result['attempt'] as Map);
      submittedAttempts[attemptId] =
          jsonDecode(jsonEncode(submittedAttempt)) as Map<String, dynamic>;
      submittedDrafts[attemptId] =
          jsonDecode(jsonEncode(draft())) as Map<String, dynamic>;
      learningState = (result['session'] as Map)['state'] as String;
      result['session'] = {
        ...result['session'] as Map<String, dynamic>,
        'id': sessionId,
        'question_id': session['question_id'],
        'question_version': session['question_version'],
        'origin': sessionOrigin,
        'review_item_id': sessionReviewItem,
      };
      final timeline = sessionEvents.putIfAbsent(sessionId, () => []);
      final generated = <Map<String, dynamic>>[];
      for (final raw in result['events'] as List) {
        generated.add({
          ...raw as Map<String, dynamic>,
          'meta': {
            ...raw['meta'] as Map<String, dynamic>,
            'question_id': session['question_id'],
            'question_version': session['question_version'],
          },
          'id': '$sessionId-event-${timeline.length + generated.length + 1}',
          'session_id': sessionId,
          'seq_no': timeline.length + generated.length + 1,
        });
      }
      timeline.addAll(generated);
      result['events'] = generated;
      sessionResources[sessionId] = {...currentSession()};
      return okResponse(result);
    });
    on('GET', '/sessions/[^/]+/events', (request) {
      final id = request.uri.pathSegments[3];
      final events = sessionEvents[id] ?? <Map<String, dynamic>>[];
      final after = int.parse(request.uri.queryParameters['after_seq'] ?? '0');
      final limit = int.parse(request.uri.queryParameters['limit'] ?? '200');
      return okResponse({
        'items': events
            .where((e) => (e['seq_no'] as int) > after)
            .take(limit)
            .toList(),
        'last_seq': events.isEmpty ? 0 : events.last['seq_no'],
      });
    });
    on('POST', '/tutor/sessions/[^/]+/next', (request) {
      final target = request.uri.pathSegments[4];
      if (target != sessionId && !sessionResources.containsKey(target)) {
        return errorResponse(404, 'session_not_found');
      }
      final resource = {...(sessionResources[target] ?? currentSession())};
      final action = bodyOf(request)!['action'] as String;
      final confirmed = bodyOf(request)!['confirm_end_independent'] == true;
      final name = switch (action) {
        'request_hint' => 'tutor_hint',
        'request_visual' =>
          !submitted && !usedSolution ? 'tutor_visual_blocked' : 'tutor_visual',
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
      if (action == 'request_hint') {
        resource['assisted'] = true;
        resource['hint_level_revealed'] =
            (resource['hint_level_revealed'] as int) + 1;
      }
      if (action == 'request_standard' || action == 'request_fast') {
        resource['used_solution'] = true;
        resource['assisted'] = true;
        resource['independent_ended'] = true;
      }
      final result = fixtures.value(name);
      final latest = {...resource, 'id': target};
      latest['state'] = (result['session'] as Map)['state'];
      if (target == sessionId) {
        learningState = latest['state'] as String;
        usedSolution = latest['used_solution'] as bool;
        sessionAssisted = latest['assisted'] as bool;
        hintsRevealed = latest['hint_level_revealed'] as int;
      }
      final timeline = sessionEvents.putIfAbsent(target, () => []);
      final events = <Map<String, dynamic>>[];
      for (final raw in result['events'] as List) {
        events.add({
          ...raw as Map<String, dynamic>,
          'meta': {
            ...raw['meta'] as Map<String, dynamic>,
            'question_id': session['question_id'],
            'question_version': session['question_version'],
          },
          'id': '$target-event-${timeline.length + events.length + 1}',
          'session_id': target,
          'seq_no': timeline.length + events.length + 1,
        });
      }
      for (final event in events) {
        timeline.add(event);
      }
      latest['last_event_seq'] = timeline.length;
      sessionResources[target] = latest;
      result['session'] = latest;
      result['events'] = events;
      return okResponse(result);
    });
    on(
      'GET',
      '/reviews/[^/]+/state',
      (request) => okResponse(reviewState(request.uri.pathSegments[3])),
    );
    on('POST', '/reviews/[^/]+/complete', (request) {
      final id = request.uri.pathSegments[3];
      final provided = bodyOf(request)!['attempt_id'] as String;
      final first =
          submittedAttempts.values
              .where(
                (a) =>
                    a['session_id'] ==
                    (submittedAttempts[provided]?['session_id'] ?? sessionId),
              )
              .toList()
            ..sort(
              (a, b) => (a['submission_no'] as int).compareTo(
                b['submission_no'] as int,
              ),
            );
      if (first.isEmpty ||
          (first.first['evaluation'] as Map?)?['state'] != 'verified') {
        return errorResponse(409, 'attempt_not_verified');
      }
      final state = reviewState(id);
      final receipt = '$id:${first.first['id']}';
      if (reviewHistory.containsKey(receipt)) {
        return errorResponse(409, 'review_already_completed');
      }
      if (state['status'] != 'scheduled') {
        return errorResponse(409, 'review_not_scheduled');
      }
      if (reviewReady[id] == false) return errorResponse(409, 'review_not_due');
      final passed =
          (first.first['evaluation'] as Map)['is_correct'] == true &&
          first.first['independent'] == true;
      final result = fixtures.value('review_completed');
      final item = result['review_item'] as Map<String, dynamic>;
      item['id'] = id;
      item['question_id'] = session['question_id'];
      item['stage'] = passed ? (state['stage'] as int) + 1 : 0;
      item['status'] = item['stage'] == item['total_stages']
          ? 'mastered'
          : 'scheduled';
      item['last_result'] = passed ? 'passed' : 'failed';
      result['result'] = item['last_result'];
      reviewStates[id] = {
        ...state,
        ...item,
        'last_attempt_id': first.first['id'],
      };
      reviewReady[id] = false;
      reviewHistory[receipt] =
          jsonDecode(jsonEncode(result)) as Map<String, dynamic>;
      return okResponse(result);
    });
  }
}

extension ScanFakeFlow on FakeBackend {
  void installScanFlow({String? questionId}) {
    var scanMime = 'image/png';
    Map<String, dynamic> scan() => {
      'id': 'scan-test',
      'status': 'needs_confirmation',
      'confidence': null,
      'low_confidence': true,
      'stem_text': '',
      'expressions': [],
      'matched_question_id': null,
      'error_code': null,
      'mock_notice': '未实际识别图片',
    };
    on('GET', '/scans/scan-test', (_) => okResponse(scan()));
    on('POST', '/scans', (_) => okResponse(scan(), status: 202));
    on(
      'POST',
      '/scans/scan-test/confirm',
      (_) => okResponse({
        'scan': scan(),
        'question_id': questionId,
        'draft_question_id': null,
      }),
    );
    on('POST', '/scans/uploads', (request) {
      scanMime = bodyOf(request)!['mime'] as String;
      return okResponse({
        'media_id': 'scan-media',
        'upload_url': '/api/v1/scans/uploads/scan-media/content',
        'upload_method': 'PUT',
        'expires_at': '2026-12-01T00:00:00Z',
        'max_bytes': 5242880,
      }, status: 201);
    });
    on(
      'PUT',
      '/scans/uploads/scan-media/content',
      (request) => okResponse({
        'media_id': 'scan-media',
        'mime': scanMime,
        'size_bytes': base64Decode(
          (bodyOf(request)!['content_base64']) as String,
        ).length,
        'sha256': sha256
            .convert(
              base64Decode((bodyOf(request)!['content_base64']) as String),
            )
            .toString(),
        'expires_at': '2026-12-01T00:00:00Z',
      }),
    );
  }
}
