import 'dart:convert';
import 'dart:io';

import 'package:test/test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import 'runtime_test.dart' show FakeTransport, Seen, jsonResponse;

Map<String, dynamic> fixture(String name) =>
    jsonDecode(File('test/fixtures/$name.json').readAsStringSync())
        as Map<String, dynamic>;

void main() {
  late FakeTransport transport;
  late TutorApiClient client;

  /// 让下一次请求返回某个样例里的真实响应。
  void serve(String name) {
    final sample = fixture(name);
    transport.onRequest =
        (_) => jsonResponse(sample['status'] as int, sample['body'] as Object);
  }

  setUp(() {
    transport = FakeTransport();
    client = TutorApiClient(
      ApiCore(
          baseUrl: 'http://127.0.0.1:8000',
          transport: transport,
          tokenProvider: () => 'tok'),
    );
  });

  test('getProfile 解析出带类型的资料', () async {
    serve('profile_saved');
    final profile = await client.getProfile();
    expect(profile.regionCode, RegionCode.cn51);
    expect(profile.grade, Grade.g12);
    expect(
        profile.subjects, [Subject.math, Subject.physics, Subject.chemistry]);
    expect(profile.examYear, 2027);
    expect(profile.examYearSource, ExamYearSource.estimated);
    expect(profile.curriculumVersion, isNull);
    expect(profile.onboardingCompleted, isTrue);
    expect(profile.notices.map((n) => n.code),
        containsAll(['curriculum_unknown', 'exam_year_estimated']));
    expect(transport.seen.single.method, 'GET');
    expect(transport.seen.single.uri.path, '/api/v1/profile');
  });

  test('updateProfile 只发送设置过的可选字段', () async {
    serve('profile_saved');
    await client.updateProfile(
      body: const ProfileUpdate(
          regionCode: RegionCode.cn50, subjects: [Subject.math]),
    );
    final request = transport.seen.single;
    expect(request.method, 'PUT');
    expect(jsonDecode(request.body!), {
      'region_code': 'CN-50',
      'subjects': ['math']
    });
  });

  test('需要幂等键的操作把键放进请求头，并且路径参数会编码', () async {
    serve('submit_correct');
    final result = await client.submitAttempt(
      attemptId: 'a/b c',
      body: const SubmitRequest(answer: AnswerPayload(selectedOptions: ['B'])),
      idempotencyKey: 'submit-0001-abcd',
    );
    final Seen request = transport.seen.single;
    expect(request.method, 'POST');
    expect(request.uri.path, '/api/v1/attempts/a%2Fb%20c/submit');
    expect(request.headers['Idempotency-Key'], 'submit-0001-abcd');
    expect(jsonDecode(request.body!), {
      'answer': {
        'selected_options': ['B']
      },
    });
    expect(result.evaluation.state, EvaluationState.verified);
    expect(result.evaluation.isCorrect, isTrue);
    expect(result.evaluation.independent, isTrue);
    expect(result.session.state, SessionState.diagnosed);
    expect(result.events.single.type, TutorEventType.diagnosis);
    // 事件 payload 里的内联枚举在生成的类里是字符串
    expect(result.events.single.diagnosis.outcome, 'correct');
  });

  test('判不出来的作答：is_correct 为空，事件是 uncertainty', () async {
    serve('submit_uncertain');
    final result = await client.submitAttempt(
      attemptId: 'x',
      body: const SubmitRequest(
          answer: AnswerPayload(
              blanks: [AnswerBlank(key: 'b1', value: '500 cm/s²')])),
      idempotencyKey: 'submit-0002-abcd',
    );
    expect(result.evaluation.state, EvaluationState.uncertain);
    expect(result.evaluation.isCorrect, isNull);
    expect(result.evaluation.reviewRequired, isTrue);
    expect(result.events.single.uncertainty.reviewRequired, isTrue);
    expect(result.reviewItem, isNull);
  });

  test('解答题：按小问提交，不自动评分，事件说明"请自查"', () async {
    serve('submit_written');
    final result = await client.submitAttempt(
      attemptId: 'x',
      body: const SubmitRequest(
        answer: AnswerPayload(parts: [
          AnswerPart(key: '1', text: '对称轴 x=a'),
          AnswerPart(key: '2', text: '最小值 -1'),
        ]),
      ),
      idempotencyKey: 'submit-0003-abcd',
    );
    expect(jsonDecode(transport.seen.single.body!), {
      'answer': {
        'parts': [
          {'key': '1', 'text': '对称轴 x=a'},
          {'key': '2', 'text': '最小值 -1'},
        ]
      },
    });
    expect(result.evaluation.state, EvaluationState.pending);
    expect(result.evaluation.outcome, EvaluationOutcome.undetermined);
    expect(result.evaluation.isCorrect, isNull);
    expect(result.reviewItem, isNull);
    expect(result.events.single.type, TutorEventType.uncertainty);
    expect(
        result.events.single.uncertainty.reasonCode, 'subjective_self_check');
    // 存下来的作答里有按小问分开的文字
    expect(result.attempt.answer!.parts!.map((p) => p.key), ['1', '2']);
  });

  test('解答题题面带小问，不带任何作答区之外的东西', () async {
    serve('question_written');
    final question = await client.getQuestion(questionId: 'q');
    expect(question.answerMode, AnswerMode.written);
    expect(question.content.subquestions.map((s) => s.key), ['1', '2']);
    expect(question.content.subquestions.map((s) => s.answerMode),
        everyElement(AnswerMode.written));
    expect(question.judgingNote, contains('不自动评分'));
    final text = jsonEncode(question.toJson());
    for (final forbidden in ['"rubric"', '"points"', '"final_answer"']) {
      expect(text.contains(forbidden), isFalse, reason: forbidden);
    }
  });

  test('对照自查：提交前是 409；提交后拿到要点；保存后只有计数，没有分数', () async {
    serve('self_check_before_submit');
    await expectLater(
      client.getSelfCheck(attemptId: 'x'),
      throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'statusCode', 409)
          .having((e) => e.code, 'code', 'attempt_not_submitted')),
    );

    serve('self_check_pending');
    final pending = await client.getSelfCheck(attemptId: 'x');
    expect(pending.points, isNotEmpty);
    expect(pending.marks, isEmpty);
    expect(pending.savedAt, isNull);
    expect(pending.summary.total, pending.points.length);
    expect(
        pending.summary.done + pending.summary.partial + pending.summary.missed,
        0);

    serve('self_check_saved');
    final saved = await client.saveSelfCheck(
      attemptId: 'x',
      body: SelfCheckSave(marks: [
        for (final point in pending.points)
          SelfCheckMark(pointKey: point.key, level: SelfCheckLevel.done),
      ]),
      idempotencyKey: 'self-check-0001',
    );
    final request = transport.seen.last;
    expect(request.method, 'PUT');
    expect(request.uri.path, '/api/v1/attempts/x/self-check');
    expect(request.headers['Idempotency-Key'], 'self-check-0001');
    expect(saved.marks, hasLength(saved.points.length));
    expect(saved.savedAt, isNotNull);
    expect(saved.summary.done + saved.summary.partial + saved.summary.missed,
        saved.summary.total);
    expect(saved.disclaimer, contains('官方'));
    expect(jsonEncode(saved.toJson()).contains('score'), isFalse);
  });

  test('学情里解答题只有计数，没有正确率', () async {
    serve('progress_summary');
    final progress = await client.getProgressSummary();
    expect(progress.subjective.attempts, 1);
    expect(progress.subjective.selfChecked, 1);
    expect(
        progress.subjective.pointsDone +
            progress.subjective.pointsPartial +
            progress.subjective.pointsMissed,
        greaterThan(0));
    expect(progress.uncertainAttempts, isA<int>());
  });

  test('listQuestions 把筛选条件编成查询参数', () async {
    serve('questions_page');
    final page = await client.listQuestions(
      subject: Subject.math,
      answerMode: AnswerMode.fill,
      scope: QuestionScope.region,
      limit: 5,
      cursor: 'abc',
    );
    expect(transport.seen.single.uri.queryParameters, {
      'subject': 'math',
      'answer_mode': 'fill',
      'scope': 'region',
      'limit': '5',
      'cursor': 'abc',
    });
    expect(page.items, hasLength(5));
    expect(page.nextCursor, isNotNull);
  });

  test('题目里没有答案相关的字段', () async {
    serve('question_single_choice');
    final question = await client.getQuestion(questionId: 'q');
    expect(question.content.options.map((o) => o.key), ['A', 'B', 'C', 'D']);
    expect(question.source.isEngineeringSample, isTrue);
    expect(question.assists.hintLevels, 3);
    final text = jsonEncode(question.toJson());
    for (final forbidden in [
      '"answer"',
      '"hints"',
      '"solutions"',
      '"option_analysis"',
      '"final_answer"'
    ]) {
      expect(text.contains(forbidden), isFalse, reason: forbidden);
    }
  });

  test('草稿版本冲突：异常里带着服务端的草稿', () async {
    serve('draft_conflict');
    await expectLater(
      client.syncDraft(
        attemptId: 'x',
        body: const DraftSync(
            baseRevision: 0, answer: AnswerPayload(selectedOptions: ['D'])),
        idempotencyKey: 'draft-0001-abcdef',
      ),
      throwsA(isA<ApiException>()
          .having((e) => e.code, 'code', 'draft_revision_conflict')
          .having(
              (e) => Draft.fromJson(Map<String, dynamic>.from(
                      e.details['server_draft'] as Map))
                  .revision,
              'server revision',
              1)),
    );
  });

  test('公开接口不带 token', () async {
    serve('launch_config');
    final config = await client.getLaunchConfig();
    expect(transport.seen.single.headers.containsKey('Authorization'), isFalse);
    expect(
        config.regions.map((r) => r.code), [RegionCode.cn51, RegionCode.cn50]);
    expect(config.grades.map((g) => g.estimatedExamYear), [2029, 2028, 2027]);
  });

  test('教学事件按类型取 payload', () async {
    serve('tutor_visual');
    final step = await client.tutorNext(
      sessionId: 's',
      body: const TutorAction(action: TutorActionType.requestVisual),
      idempotencyKey: 'tutor-0001-abcdef',
    );
    final event = step.events.single;
    expect(event.type, TutorEventType.visual);
    expect(event.visual.templateId, 'quadratic_graph');
    expect(event.visual.params, {'a': 1.0, 'b': -2.0, 'c': -3.0});
    expect(event.visual.staticFallback, isNotEmpty);
    expect(event.meta.source, TutorEventSource.reviewedContent);
    expect(step.session.state, SessionState.visual);
  });

  test('planned 接口得到 501 not_implemented', () async {
    serve('error_not_implemented');
    await expectLater(
      client.createScan(
          body: const ScanCreate(mediaId: 'm'),
          idempotencyKey: 'scan-0001-abcdef'),
      throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'statusCode', 501)
          .having((e) => e.code, 'code', 'not_implemented')),
    );
  });

  group('家长周报与授权', () {
    test('学生生成邀请码：十位、带幂等键；授权列表里不会再出现码', () async {
      serve('parent_invite');
      final invite = await client.createParentInvite(
        idempotencyKey: 'invite-0001-abcd',
      );
      final request = transport.seen.single;
      expect(request.method, 'POST');
      expect(request.uri.path, '/api/v1/me/parent-invites');
      expect(request.headers['Idempotency-Key'], 'invite-0001-abcd');
      expect(invite.code, hasLength(10));
      expect(invite.expiresAt.isAfter(invite.createdAt), isTrue);

      serve('parent_links_pending');
      final links = await client.listParentLinks();
      expect(links.links, isEmpty);
      expect(links.pendingInvite, isNotNull);
      expect(jsonEncode(links.toJson()).contains('"code"'), isFalse);
      expect(jsonEncode(links.toJson()).contains(invite.code), isFalse);
    });

    test('家长输入邀请码：请求体只有 code；不对的码是 404 invite_invalid', () async {
      serve('parent_link_created');
      final linked = await client.redeemParentInvite(
        body: const ParentInviteRedeem(code: 'abcde-23456'),
        idempotencyKey: 'redeem-0001-abcd',
      );
      final request = transport.seen.single;
      expect(request.uri.path, '/api/v1/parents/links');
      expect(jsonDecode(request.body!), {'code': 'abcde-23456'});
      expect(request.headers['Idempotency-Key'], 'redeem-0001-abcd');
      expect(linked.studentId, isNotEmpty);

      serve('error_invite_invalid');
      await expectLater(
        client.redeemParentInvite(
          body: const ParentInviteRedeem(code: 'ZZZZZZZZZZ'),
          idempotencyKey: 'redeem-0002-abcd',
        ),
        throwsA(
          isA<ApiException>()
              .having((e) => e.statusCode, 'statusCode', 404)
              .having((e) => e.code, 'code', 'invite_invalid'),
        ),
      );
    });

    test('家长看学生列表和某一周的汇总：week_start 编成查询参数', () async {
      serve('parent_students');
      final students = await client.listParentStudents();
      expect(students.items, hasLength(1));
      final studentId = students.items.single.studentId;

      serve('parent_weekly');
      final weekly = await client.getParentWeekly(
        studentId: studentId,
        weekStart: '2026-11-09',
      );
      final request = transport.seen.last;
      expect(request.uri.path, '/api/v1/parents/students/$studentId/weekly');
      expect(request.uri.queryParameters, {'week_start': '2026-11-09'});
      expect(weekly.studentId, studentId);
      expect(weekly.attemptsCount, greaterThan(0));
      expect(weekly.bySubject, hasLength(3));
      expect(weekly.independentTrend, isA<WeeklyTrend>());
      expect(weekly.disclaimer, contains('不是官方成绩'));
      // 只有汇总：没有题目、作答、草稿
      final text = jsonEncode(weekly.toJson());
      for (final forbidden in ['question', 'strokes', 'answer', 'hints']) {
        expect(text.contains('"$forbidden'), isFalse, reason: forbidden);
      }
    });

    test('没授权、授权撤销后是 404；日期不是周一是 422', () async {
      serve('error_weekly_not_linked');
      await expectLater(
        client.getParentWeekly(studentId: 'x'),
        throwsA(
          isA<ApiException>()
              .having((e) => e.statusCode, 'statusCode', 404)
              .having((e) => e.code, 'code', 'not_found'),
        ),
      );
      serve('error_weekly_revoked');
      await expectLater(
        client.getParentWeekly(studentId: 'x'),
        throwsA(
          isA<ApiException>().having((e) => e.statusCode, 'statusCode', 404),
        ),
      );
      serve('error_weekly_not_a_monday');
      await expectLater(
        client.getParentWeekly(studentId: 'x', weekStart: '2026-11-10'),
        throwsA(
          isA<ApiException>().having((e) => e.statusCode, 'statusCode', 422),
        ),
      );
    });

    test('学生撤销授权：路径带授权 ID，带幂等键，返回撤销时间', () async {
      serve('parent_link_revoked');
      final link = await client.revokeParentLink(
        linkId: 'a/b',
        idempotencyKey: 'revoke-0001-abcd',
      );
      final request = transport.seen.single;
      expect(request.uri.path, '/api/v1/me/parent-links/a%2Fb/revoke');
      expect(request.headers['Idempotency-Key'], 'revoke-0001-abcd');
      expect(link.revokedAt, isNotNull);
    });

    test('本地身份 Mock 可以领家长角色', () async {
      serve('local_identity');
      await client.createLocalIdentity(role: LocalRole.parent);
      expect(transport.seen.single.uri.queryParameters, {'role': 'parent'});
    });
  });
}
