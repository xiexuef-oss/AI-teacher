import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/solve/draft_store.dart';
import 'package:tutor_student/features/solve/solve_controller.dart';

import 'support/fake_backend.dart';

const _user = 'user-1';

/// 控制器用真实的短定时器（几十毫秒），测试里轮询等待条件成立。
Future<void> until(
  bool Function() condition, {
  String reason = '条件没有在 3 秒内成立',
}) async {
  final deadline = DateTime.now().add(const Duration(seconds: 3));
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) fail(reason);
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
}

class Harness {
  Harness({
    String? questionId,
    this.origin = 'practice',
    this.reviewItemId,
    MemoryStore? store,
    FakeBackend? backend,
  }) : store = store ?? MemoryStore(),
       backend = backend ?? FakeBackend(),
       questionId =
           questionId ??
           Fixtures.load().value('question_single_choice')['id'] as String {
    if (backend == null) this.backend.installLearningFlow();
    core = ApiCore(
      baseUrl: 'http://127.0.0.1:8000',
      transport: this.backend,
      tokenProvider: () => 'tok',
    );
  }

  final MemoryStore store;
  final FakeBackend backend;
  final String questionId;
  final String origin;
  final String? reviewItemId;
  late final ApiCore core;
  int unauthenticated = 0;
  final List<SolveController> created = [];

  SolveController controller() {
    final c = SolveController(
      api: TutorApiClient(core),
      store: store,
      userId: _user,
      args: SolveArgs(
        questionId: questionId,
        origin: origin,
        reviewItemId: reviewItemId,
      ),
      onUnauthenticated: () => unauthenticated += 1,
      autosaveDelay: const Duration(milliseconds: 15),
      syncDelay: const Duration(milliseconds: 40),
      retryDelay: const Duration(milliseconds: 80),
    );
    created.add(c);
    return c;
  }

  void dispose() {
    for (final c in created) {
      c.dispose();
    }
  }
}

Future<SolveController> started(Harness h) async {
  final c = h.controller();
  await c.start();
  return c;
}

void main() {
  late Harness h;

  setUp(() => h = Harness());
  tearDown(() => h.dispose());

  group('开始作答', () {
    test('取题、开会话、建作答，进入作答状态', () async {
      final c = await started(h);

      expect(c.phase, SolvePhase.answering);
      expect(c.question!.content.options, hasLength(4));
      expect(c.questionFromCache, isFalse);
      expect(c.session, isNotNull);
      expect(c.attempt!.attemptNo, 1);
      expect(c.sync, SaveStatus.saved);
      expect(h.backend.sessionsCreated, 1);
      expect(h.backend.attemptsCreated, 1);
      final created = h.backend.bodyOf(
        h.backend.requestsTo('POST', '/sessions').single,
      )!;
      expect(created['origin'], 'practice');
      expect(created.containsKey('review_item_id'), isFalse);
    });

    test('每个创建动作都带幂等键', () async {
      await started(h);
      for (final request in [
        ...h.backend.requestsTo('POST', '/sessions'),
        ...h.backend.requestsTo('POST', '/attempts'),
      ]) {
        expect(request.headers['Idempotency-Key'], isNotNull);
        expect(
          request.headers['Idempotency-Key']!.length,
          greaterThanOrEqualTo(8),
        );
      }
    });

    test('题目不存在时进入失败状态，并给出能看的原因', () async {
      final backend = FakeBackend();
      backend.on(
        'GET',
        '/questions/[^/]+',
        (_) => errorResponse(404, 'not_found'),
      );
      final c = await started(Harness(backend: backend));

      expect(c.phase, SolvePhase.failed);
      expect(c.failure, isNotNull);
    });
  });

  group('答案与提交条件', () {
    test('单选：选一个才能提交，再点另一个是换选', () async {
      final c = await started(h);
      expect(c.canSubmit, isFalse);

      c.selectOption('A');
      expect(c.canSubmit, isTrue);
      c.selectOption('B');
      expect(c.selected, {'B'});
    });

    test('多选：可以选多个，取消到一个都没有就不能提交', () async {
      final backend = FakeBackend()
        ..installLearningFlow(questionFixture: 'question_multiple_choice');
      final c = await started(
        Harness(
          backend: backend,
          questionId:
              Fixtures.load().value('question_multiple_choice')['id'] as String,
        ),
      );

      c.selectOption('A');
      c.selectOption('C');
      expect(c.selected, {'A', 'C'});
      expect(c.canSubmit, isTrue);
      c.selectOption('A');
      c.selectOption('C');
      expect(c.selected, isEmpty);
      expect(c.canSubmit, isFalse);
    });

    test('填空：每个空都填了才能提交，空白不算', () async {
      final backend = FakeBackend()
        ..installLearningFlow(questionFixture: 'question_fill');
      final c = await started(
        Harness(
          backend: backend,
          questionId: Fixtures.load().value('question_fill')['id'] as String,
        ),
      );

      expect(c.canSubmit, isFalse);
      c.setBlank('b1', '   ');
      expect(c.canSubmit, isFalse);
      c.setBlank('b1', '5 m/s²');
      expect(c.canSubmit, isTrue);
    });
  });

  group('草稿：本地保存与云端同步', () {
    test('改动后先落本地、再同步到云端，状态依次变化', () async {
      final c = await started(h);

      c.selectOption('A');
      expect(c.sync, SaveStatus.dirty);
      await until(
        () => h.store.data.keys.any((k) => k.startsWith('u/$_user/draft/')),
        reason: '没有写入本地草稿',
      );
      await until(() => c.sync == SaveStatus.saved);

      expect(h.backend.serverRevision, 1);
      expect(h.backend.serverAnswer, {
        'selected_options': ['A'],
      });
      final saved = jsonDecode(
        h.store.data.entries.firstWhere((e) => e.key.contains('/draft/')).value,
      ) as Map<String, dynamic>;
      expect(saved['dirty'], isFalse);
      expect(saved['baseRevision'], 1);
    });

    test('笔迹和答案一起同步', () async {
      final c = await started(h);

      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);

      final strokes = h.backend.serverStrokes!;
      expect(strokes['version'], 1);
      expect(
        ((strokes['pages'] as List).single as Map)['strokes'],
        hasLength(1),
      );
    });

    test('每次同步都带当前的基准版本号，且幂等键随内容变化', () async {
      final c = await started(h);
      c.selectOption('A');
      await until(() => c.sync == SaveStatus.saved);
      c.selectOption('B');
      await until(() => h.backend.serverRevision == 2);

      final puts = h.backend.requestsTo('PUT', '/attempts/.+/draft').toList();
      expect(puts.map((r) => h.backend.bodyOf(r)!['base_revision']), [0, 1]);
      expect(
        puts[0].headers['Idempotency-Key'],
        isNot(puts[1].headers['Idempotency-Key']),
      );
    });

    test('重开页面能从本机恢复答案和笔迹，并接着用原来的会话与作答', () async {
      final first = await started(h);
      first.selectOption('C');
      first.ink.beginStroke(0, 20, 30);
      first.ink.extendStroke(90, 90, t: 10);
      first.ink.endStroke();
      await until(() => first.sync == SaveStatus.saved);
      first.dispose();

      final second = await started(h);

      expect(second.selected, {'C'});
      expect(second.ink.hasInk, isTrue);
      expect(h.backend.sessionsCreated, 1, reason: '不能重复开会话');
      expect(h.backend.attemptsCreated, 1);
      expect(second.sync, SaveStatus.saved);
    });

    test('应用被切到后台时立刻保存，不等定时器', () async {
      final c = await started(h);
      c.selectOption('D');
      await c.flushNow();

      final saved = jsonDecode(
        h.store.data.entries.firstWhere((e) => e.key.contains('/draft/')).value,
      ) as Map<String, dynamic>;
      expect((saved['answer'] as Map)['selected'], ['D']);
      expect(saved['dirty'], isTrue);
    });

    test('本机存储写失败时明确告诉学生，而不是装作保存成功', () async {
      final c = await started(h);
      h.store.failWrites = true;

      c.selectOption('A');
      await until(() => c.localSaveFailed);

      expect(c.localSaveFailed, isTrue);
      h.store.failWrites = false;
      c.selectOption('B');
      await until(() => !c.localSaveFailed, reason: '存储恢复后应该清除提示');
    });
  });

  group('断网', () {
    test('断网时草稿照常保存在本机，状态是"未同步"；网络恢复后自动补上', () async {
      final c = await started(h);
      h.backend.offline = true;

      c.selectOption('A');
      await until(() => c.sync == SaveStatus.offline);
      expect(h.store.data.keys.any((k) => k.contains('/draft/')), isTrue);
      expect(h.backend.serverRevision, 0);

      h.backend.offline = false;
      await until(() => c.sync == SaveStatus.saved, reason: '恢复网络后应该自动同步');
      expect(h.backend.serverRevision, 1);
    });

    test('开始时就没网：用缓存的题目离线作答，恢复后才创建会话并把草稿同步上去', () async {
      // 先在线打开一次，让题目被缓存
      final warm = await started(h);
      warm.dispose();
      final fresh = FakeBackend()..installLearningFlow();
      final harness = Harness(store: h.store, backend: fresh);
      fresh.offline = true;

      final c = await started(harness);

      expect(c.phase, SolvePhase.answering);
      expect(c.questionFromCache, isTrue);
      c.selectOption('B');
      await until(() => c.sync == SaveStatus.offline);
      expect(fresh.sessionsCreated, 0);

      fresh.offline = false;
      await until(() => c.sync == SaveStatus.saved);
      expect(fresh.sessionsCreated, 1);
      expect(fresh.serverAnswer, {
        'selected_options': ['B'],
      });
      harness.dispose();
    });

    test('开始时没网、也没有缓存的题目：说明原因，不白屏', () async {
      final backend = FakeBackend()..offline = true;
      final c = await started(Harness(backend: backend));

      expect(c.phase, SolvePhase.failed);
      expect((c.failure as ApiException).isNetwork, isTrue);
    });

    test('断网时不能提交，草稿保留，并说明原因', () async {
      final c = await started(h);
      c.selectOption('B');
      h.backend.offline = true;

      await c.submit();

      expect(c.phase, SolvePhase.answering);
      expect(c.actionError, isNotNull);
      expect((c.actionError as ApiException).isNetwork, isTrue);
      expect(c.selected, {'B'});
    });
  });

  group('版本冲突（409）', () {
    Future<SolveController> conflicted(Harness h) async {
      final c = await started(h);
      c.selectOption('A');
      await until(() => c.sync == SaveStatus.saved);
      // 别处把云端草稿改成了另一份
      h.backend.serverRevision = 5;
      h.backend.serverAnswer = {
        'selected_options': ['D'],
      };
      c.selectOption('B');
      await until(() => c.sync == SaveStatus.conflict);
      return c;
    }

    test('不静默覆盖：进入冲突状态，同时保留本地稿和云端稿', () async {
      final c = await conflicted(h);

      expect(c.conflictServerDraft!.revision, 5);
      expect(c.selected, {'B'}, reason: '本地稿原样保留');
      expect(h.backend.serverAnswer, {
        'selected_options': ['D'],
      }, reason: '云端稿没有被覆盖');
      expect(c.canSubmit, isFalse, reason: '有冲突时先解决再提交');
    });

    test('保留本地稿：以云端版本为基准重新同步，覆盖云端', () async {
      final c = await conflicted(h);

      await c.resolveConflictKeepLocal();
      await until(() => c.sync == SaveStatus.saved);

      expect(h.backend.serverAnswer, {
        'selected_options': ['B'],
      });
      expect(h.backend.serverRevision, 6);
      expect(c.conflictServerDraft, isNull);
    });

    test('使用云端稿：本地内容换成云端的', () async {
      final c = await conflicted(h);

      await c.resolveConflictUseServer();

      expect(c.selected, {'D'});
      expect(c.sync, SaveStatus.saved);
      expect(c.conflictServerDraft, isNull);
      expect(h.backend.serverAnswer, {
        'selected_options': ['D'],
      });
    });

    test('云端内容与本地一致（例如响应丢了、重启后重复同步）时静默接受，不打扰学生', () async {
      final c = await started(h);
      h.backend.serverRevision = 3;
      h.backend.serverAnswer = {
        'selected_options': ['C'],
      };

      c.selectOption('C');
      await until(() => c.sync == SaveStatus.saved);

      expect(c.conflictServerDraft, isNull);
    });
  });

  group('提交', () {
    test('答对：记录评估，进入已提交状态，本地草稿清掉', () async {
      h.backend.submitFixture = 'submit_correct';
      final c = await started(h);
      c.selectOption('B');

      await c.submit();

      expect(c.phase, SolvePhase.submitted);
      expect(c.evaluation!.state, EvaluationState.verified);
      expect(c.evaluation!.isCorrect, isTrue);
      expect(c.events.map((e) => e.type), contains(TutorEventType.diagnosis));
      expect(c.session!.state, SessionState.diagnosed);
      expect(h.store.data.keys.where((k) => k.contains('/draft/')), isEmpty);
      final body = h.backend.bodyOf(
        h.backend.requestsTo('POST', '/attempts/.+/submit').single,
      )!;
      expect(body['answer'], {
        'selected_options': ['B'],
      });
    });

    test('提交前会把最新的笔迹同步一遍', () async {
      h.backend.submitFixture = 'submit_correct';
      final c = await started(h);
      c.selectOption('B');
      c.ink.beginStroke(0, 5, 5);
      c.ink.extendStroke(50, 50, t: 9);
      c.ink.endStroke();

      await c.submit();

      expect(h.backend.serverStrokes, isNotNull);
    });

    test('判不出来：原样展示"待确认"，没有对错', () async {
      h.backend.submitFixture = 'submit_uncertain';
      final c = await started(h);
      c.selectOption('A');

      await c.submit();

      expect(c.evaluation!.state, EvaluationState.uncertain);
      expect(c.evaluation!.isCorrect, isNull);
      expect(c.events.first.type, TutorEventType.uncertainty);
    });

    test('网络失败后重试，用的是同一个幂等键（服务端不会当成新的提交）', () async {
      h.backend.submitFixture = 'submit_correct';
      final c = await started(h);
      c.selectOption('B');
      await c.flushNow();
      h.backend.failNextOn(r'/submit$', 503, 'internal_error');
      await c.submit();
      expect(c.phase, SolvePhase.answering);

      await c.submit();

      final keys = h.backend
          .requestsTo('POST', '/attempts/.+/submit')
          .map((r) => r.headers['Idempotency-Key'])
          .toList();
      expect(keys, hasLength(2));
      expect(keys[0], keys[1]);
      expect(c.phase, SolvePhase.submitted);
    });

    test('在不能提交时调用 submit 什么也不发生', () async {
      final c = await started(h);
      await c.submit();
      expect(h.backend.requestsTo('POST', '/attempts/.+/submit'), isEmpty);
    });

    test('答错后可以再试一次：新建作答，清掉答案和笔迹', () async {
      final c = await started(h);
      c.selectOption('A');
      c.ink.beginStroke(0, 5, 5);
      c.ink.endStroke();
      await c.submit();
      expect(c.phase, SolvePhase.submitted);

      await c.retry();

      expect(c.phase, SolvePhase.answering);
      expect(c.selected, isEmpty);
      expect(c.ink.hasInk, isFalse);
      expect(c.evaluation, isNull);
      expect(h.backend.attemptsCreated, 2);
    });
  });

  group('辅导动作', () {
    test('给点提示：事件追加到时间线，会话更新', () async {
      final c = await started(h);

      final outcome = await c.tutor(TutorActionType.requestHint);

      expect(outcome, TutorOutcome.ok);
      expect(c.events.single.type, TutorEventType.hint);
      expect(c.events.single.hint.level, 1);
      expect(c.session!.assisted, isTrue);
    });

    test('提交前查看解析：先要求确认，没确认就不会有任何内容', () async {
      final c = await started(h);

      final outcome = await c.tutor(TutorActionType.requestStandard);

      expect(outcome, TutorOutcome.needsConfirmation);
      expect(c.events, isEmpty);
      expect(c.session!.usedSolution, isFalse);
    });

    test('确认结束独立作答之后才给解析', () async {
      final c = await started(h);

      final outcome = await c.tutor(
        TutorActionType.requestStandard,
        confirmEndIndependent: true,
      );

      expect(outcome, TutorOutcome.ok);
      expect(c.events.single.type, TutorEventType.standard);
      final body = h.backend.bodyOf(
        h.backend.requestsTo('POST', '/tutor/sessions/.+/next').last,
      )!;
      expect(body['confirm_end_independent'], isTrue);
    });

    test('提交之后看解析不需要确认', () async {
      final c = await started(h);
      c.selectOption('A');
      await c.submit();

      expect(await c.tutor(TutorActionType.requestStandard), TutorOutcome.ok);
    });

    test('一次点击一个动作：处理中重复点击被忽略', () async {
      final c = await started(h);

      final first = c.tutor(TutorActionType.requestHint);
      final second = await c.tutor(TutorActionType.requestHint);
      await first;

      expect(second, TutorOutcome.busy);
      expect(
        h.backend.requestsTo('POST', '/tutor/sessions/.+/next'),
        hasLength(1),
      );
    });

    test('服务端报错时返回失败并保留错误，时间线不变', () async {
      final c = await started(h);
      h.backend.failNext = (503, 'model_unavailable');

      final outcome = await c.tutor(TutorActionType.requestHint);

      expect(outcome, TutorOutcome.failed);
      expect(c.actionError, isNotNull);
      expect(c.events, isEmpty);
    });

    test('时间线里的事件顺序就是服务端给的顺序', () async {
      final c = await started(h);
      await c.tutor(TutorActionType.requestHint);
      await c.tutor(TutorActionType.requestVisual);

      expect(c.events.map((e) => e.type), [
        TutorEventType.hint,
        TutorEventType.visual,
      ]);
    });
  });

  group('复测会话', () {
    late Harness retest;
    setUp(
      () => retest = Harness(origin: 'review', reviewItemId: 'review-item-1'),
    );
    tearDown(() => retest.dispose());

    test('提交前不提供任何辅助，界面据此隐藏按钮', () async {
      final c = await started(retest);
      expect(c.assistanceAllowed, isFalse);
      expect(
        await c.tutor(TutorActionType.requestHint),
        TutorOutcome.notAllowed,
      );
      expect(
        retest.backend.requestsTo('POST', '/tutor/sessions/.+/next'),
        isEmpty,
      );
    });

    test('开会话时带上复测项；提交后自动记录复测结果', () async {
      retest.backend.submitFixture = 'submit_correct';
      final c = await started(retest);
      c.selectOption('B');

      await c.submit();

      final created = retest.backend.bodyOf(
        retest.backend.requestsTo('POST', '/sessions').single,
      )!;
      expect(created['origin'], 'review');
      expect(created['review_item_id'], 'review-item-1');
      expect(c.assistanceAllowed, isTrue);
      expect(c.reviewCompletion, isNotNull);
      expect(c.reviewCompletion!.result, ReviewResult.passed);
      final completed = retest.backend
          .requestsTo('POST', '/reviews/.+/complete')
          .single;
      expect(completed.uri.path, endsWith('/review-item-1/complete'));
    });
  });

  group('解答题', () {
    late Harness w;
    setUp(() {
      final backend = FakeBackend()
        ..submitFixture = 'submit_written'
        ..installLearningFlow(questionFixture: 'question_written');
      w = Harness(
        backend: backend,
        questionId: Fixtures.load().value('question_written')['id'] as String,
      );
    });
    tearDown(() => w.dispose());

    Future<SolveController> submitted([String text = '对称轴是 x=a']) async {
      final c = await started(w);
      c.setPart('1', text);
      await c.submit();
      return c;
    }

    test('有文字或有笔迹才能提交；只有空白不算', () async {
      final c = await started(w);
      expect(c.canSubmit, isFalse);

      c.setPart('1', '   ');
      expect(c.canSubmit, isFalse);
      c.setPart('1', '对称轴是 x=a');
      expect(c.canSubmit, isTrue);
      c.setPart('1', '');
      expect(c.canSubmit, isFalse);

      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      expect(c.canSubmit, isTrue, reason: '只有笔迹也可以提交');
    });

    test('只能写题目里有的小问；写得太长会被截到上限', () async {
      final c = await started(w);

      c.setPart('9', '没有这个小问');
      expect(c.parts, isEmpty);
      c.setPart('1', 'x' * 5000);
      expect(c.parts['1']!.length, 4000);
    });

    test('分小问的文字按小问顺序同步到云端草稿，没写的小问不发', () async {
      final c = await started(w);

      c.setPart('2', '最小值 -1');
      c.setPart('1', '对称轴 x=a');
      await until(() => w.backend.serverAnswer != null, reason: '草稿没有同步到云端');
      await until(() => c.sync == SaveStatus.saved);

      expect(w.backend.serverAnswer, {
        'parts': [
          {'key': '1', 'text': '对称轴 x=a'},
          {'key': '2', 'text': '最小值 -1'},
        ],
      });
    });

    test('分小问的文字先存在本机，重新打开时恢复', () async {
      final first = await started(w);
      first.setPart('2', '最小值 -1');
      await first.flushNow();

      final saved = await first.drafts.readDraft(w.questionId);
      expect(saved!.parts, {'2': '最小值 -1'});
      first.dispose();

      final second = await started(w);
      expect(second.parts, {'2': '最小值 -1'});
      expect(w.backend.sessionsCreated, 1, reason: '不能重复开会话');
    });

    test('提交：文字去掉首尾空白；结果是待自评，不是对也不是错', () async {
      final c = await submitted('  对称轴是 x=a  ');

      final body = w.backend.bodyOf(
        w.backend.requestsTo('POST', '/submit').single,
      )!;
      expect(body['answer'], {
        'parts': [
          {'key': '1', 'text': '对称轴是 x=a'},
        ],
      });
      expect(c.phase, SolvePhase.submitted);
      expect(c.evaluation!.state, EvaluationState.pending);
      expect(c.evaluation!.isCorrect, isNull);
      expect(c.events.single.uncertainty.reasonCode, 'subjective_self_check');
      expect(c.reviewItem, isNull);
    });

    test('只有笔迹也能提交；笔迹没同步上去时先拦住，不让服务端拒绝一个看似空白的答案', () async {
      final c = await started(w);
      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);
      await c.submit();
      expect(c.phase, SolvePhase.submitted);
      expect(
        w.backend.bodyOf(
          w.backend.requestsTo('POST', '/submit').single,
        )!['answer'],
        {'parts': <Object>[]},
      );
    });

    test('笔迹还在本机、没同步到云端时，只有笔迹的作答不能提交', () async {
      final c = await started(w);
      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);
      c.ink.beginStroke(0, 20, 20);
      c.ink.extendStroke(80, 80, t: 12);
      c.ink.endStroke();
      w.backend.offline = true;

      await c.submit();

      expect(c.phase, SolvePhase.answering);
      expect(c.actionError, isNotNull);
      expect(w.backend.requestsTo('POST', '/submit'), isEmpty);
      w.backend.offline = false;
    });

    test('提交之前不会去要自查要点', () async {
      final c = await started(w);
      c.setPart('1', '写了');
      await until(() => c.sync == SaveStatus.saved);

      expect(w.backend.requestsTo('GET', '/self-check'), isEmpty);
      expect(c.selfCheck, isNull);
    });

    test('提交之后自动取来自查要点；一条都还没标', () async {
      final c = await submitted();

      expect(c.selfCheck, isNotNull);
      expect(c.selfCheck!.points, isNotEmpty);
      expect(c.selfCheck!.marks, isEmpty);
      expect(c.marks, isEmpty);
      expect(c.selfCheckComplete, isFalse);
      expect(c.selfCheckDirty, isFalse);
    });

    test('逐条标出做到没有；全部标完才能保存；按要点清单的顺序、带幂等键', () async {
      final c = await submitted();
      final points = c.selfCheck!.points;

      await c.saveSelfCheck();
      expect(
        w.backend.requestsTo('PUT', '/self-check'),
        isEmpty,
        reason: '没标完不发',
      );

      for (final point in points.skip(1)) {
        c.markPoint(point.key, SelfCheckLevel.done);
      }
      expect(c.selfCheckComplete, isFalse, reason: '还差一条');
      c.markPoint(points.first.key, SelfCheckLevel.missed);
      expect(c.selfCheckComplete, isTrue);
      expect(c.selfCheckDirty, isTrue);

      await c.saveSelfCheck();

      final request = w.backend.requestsTo('PUT', '/self-check').single;
      expect(request.headers['Idempotency-Key'], isNotNull);
      final sent = (w.backend.bodyOf(request)!['marks'] as List<dynamic>)
          .cast<Map<String, dynamic>>();
      expect(sent.map((m) => m['point_key']), points.map((p) => p.key));
      expect(sent.first['level'], 'missed');
      expect(c.selfCheck!.savedAt, isNotNull);
      expect(c.selfCheck!.summary.missed, 1);
      expect(c.selfCheck!.summary.done, points.length - 1);
      expect(c.selfCheckDirty, isFalse);
      expect(c.phase, SolvePhase.submitted, reason: '自查不改变作答的状态');
      expect(c.evaluation!.state, EvaluationState.pending);
      expect(c.evaluation!.isCorrect, isNull);
    });

    test('改了自评再保存：换新的幂等键；没改就不是待保存的', () async {
      final c = await submitted();
      final points = c.selfCheck!.points;
      for (final point in points) {
        c.markPoint(point.key, SelfCheckLevel.done);
      }
      await c.saveSelfCheck();
      expect(c.selfCheckDirty, isFalse);

      c.markPoint(points.first.key, SelfCheckLevel.partial);
      expect(c.selfCheckDirty, isTrue);
      await c.saveSelfCheck();

      final keys = w.backend
          .requestsTo('PUT', '/self-check')
          .map((r) => r.headers['Idempotency-Key'])
          .toList();
      expect(keys, hasLength(2));
      expect(keys[0], isNot(keys[1]));
      expect(c.selfCheck!.summary.partial, 1);
    });

    test('保存失败：已标的内容还在，可以再点保存', () async {
      final c = await submitted();
      for (final point in c.selfCheck!.points) {
        c.markPoint(point.key, SelfCheckLevel.done);
      }
      w.backend.failNextOn('/self-check', 503, 'service_unavailable');

      await c.saveSelfCheck();
      expect(c.selfCheckError, isNotNull);
      expect(c.selfCheck!.savedAt, isNull);
      expect(c.selfCheckComplete, isTrue, reason: '标好的没有丢');

      await c.saveSelfCheck();
      expect(c.selfCheckError, isNull);
      expect(c.selfCheck!.savedAt, isNotNull);
    });

    test('取要点失败：作答仍是已提交的，之后可以重试', () async {
      final c = await started(w);
      c.setPart('1', '写了');
      w.backend.failNextOn('/self-check', 503, 'service_unavailable');

      await c.submit();

      expect(c.phase, SolvePhase.submitted);
      expect(c.selfCheck, isNull);
      expect(c.selfCheckError, isNotNull);

      await c.loadSelfCheck();
      expect(c.selfCheck, isNotNull);
      expect(c.selfCheckError, isNull);
    });

    test('再试一次：分小问的文字、自评和要点都清掉', () async {
      final c = await submitted();
      c.markPoint(c.selfCheck!.points.first.key, SelfCheckLevel.done);

      await c.retry();

      expect(c.phase, SolvePhase.answering);
      expect(c.parts, isEmpty);
      expect(c.selfCheck, isNull);
      expect(c.marks, isEmpty);
      expect(c.selfCheckError, isNull);
    });

    test('不是解答题就不去要自查要点', () async {
      final c = await started(h);
      c.selectOption('A');
      await c.submit();

      expect(c.phase, SolvePhase.submitted);
      expect(h.backend.requestsTo('GET', '/self-check'), isEmpty);
      expect(c.selfCheck, isNull);
    });
  });

  group('实验题', () {
    late Harness e;
    late Map<String, dynamic> question;
    setUp(() {
      final backend = FakeBackend()
        ..submitFixture = 'submit_experiment'
        ..selfCheckFixture = 'self_check_experiment_pending'
        ..installLearningFlow(questionFixture: 'question_experiment');
      question = Fixtures.load().value('question_experiment');
      e = Harness(backend: backend, questionId: question['id'] as String);
    });
    tearDown(() => e.dispose());

    /// 第一张表里留空的格子 v 的四行，加上表 2 的加速度
    void fillTables(SolveController c) {
      c.setCell('t1', 'r1', 'v', '0.400');
      c.setCell('t1', 'r2', 'v', '0.600');
      c.setCell('t1', 'r3', 'v', '0.800');
      c.setCell('t1', 'r4', 'v', '1.00');
      c.setCell('t2', 'r1', 'val', '2.00');
    }

    test('有填写的格子、小问文字或笔迹才能提交；只有空白不算', () async {
      final c = await started(e);
      expect(c.canSubmit, isFalse);

      c.setCell('t1', 'r1', 'v', '   ');
      c.setPart('1', '\n');
      expect(c.canSubmit, isFalse);
      c.setCell('t1', 'r1', 'v', '0.400');
      expect(c.canSubmit, isTrue);
      c.setCell('t1', 'r1', 'v', '');
      expect(c.canSubmit, isFalse);
      c.setPart('2', '用逐差法');
      expect(c.canSubmit, isTrue, reason: '只写文字也可以');
      c.setPart('2', '');

      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      expect(c.canSubmit, isTrue, reason: '只有笔迹也可以提交');
    });

    test('只能填题目里留空的格子；格子的值截到 40 字', () async {
      final c = await started(e);

      c.setCell('t1', 'r1', 'x', '9.99'); // 题目给定的格子
      c.setCell('t1', 'r1', 'seg', 'ZZ');
      c.setCell('t9', 'r1', 'v', '1'); // 不存在的表
      c.setCell('t1', 'r9', 'v', '1');
      c.setCell('t1', 'r1', 'zz', '1');
      expect(c.cells, isEmpty);

      c.setCell('t1', 'r1', 'v', '9' * 60);
      expect(c.cells['t1.r1.v']!.length, 40);
    });

    test('格子和小问按题目里的顺序同步到云端草稿，没填的不发', () async {
      final c = await started(e);

      c.setPart('2', '用逐差法');
      c.setCell('t2', 'r1', 'val', '2.00');
      c.setCell('t1', 'r2', 'v', '0.600');
      c.setCell('t1', 'r1', 'v', '0.400');
      await until(() => e.backend.serverAnswer != null, reason: '草稿没有同步到云端');
      await until(() => c.sync == SaveStatus.saved);

      expect(e.backend.serverAnswer, {
        'cells': [
          {'table': 't1', 'row': 'r1', 'col': 'v', 'value': '0.400'},
          {'table': 't1', 'row': 'r2', 'col': 'v', 'value': '0.600'},
          {'table': 't2', 'row': 'r1', 'col': 'val', 'value': '2.00'},
        ],
        'parts': [
          {'key': '2', 'text': '用逐差法'},
        ],
      });
    });

    test('格子先存在本机，重新打开时恢复；不重复开会话', () async {
      final first = await started(e);
      first.setCell('t1', 'r3', 'v', '0.800');
      await first.flushNow();

      final saved = await first.drafts.readDraft(e.questionId);
      expect(saved!.cells, {'t1.r3.v': '0.800'});
      first.dispose();

      final second = await started(e);
      expect(second.cells, {'t1.r3.v': '0.800'});
      expect(e.backend.sessionsCreated, 1);
    });

    test('提交：格子和文字去掉首尾空白；结果是待自评，不是对也不是错', () async {
      final c = await started(e);
      fillTables(c);
      c.setCell('t1', 'r1', 'v', '  0.400 ');
      c.setPart('1', '  T 等于 0.10 秒  ');
      await c.submit();

      final body = e.backend.bodyOf(
        e.backend.requestsTo('POST', '/submit').single,
      )!;
      expect(body['answer'], {
        'cells': [
          {'table': 't1', 'row': 'r1', 'col': 'v', 'value': '0.400'},
          {'table': 't1', 'row': 'r2', 'col': 'v', 'value': '0.600'},
          {'table': 't1', 'row': 'r3', 'col': 'v', 'value': '0.800'},
          {'table': 't1', 'row': 'r4', 'col': 'v', 'value': '1.00'},
          {'table': 't2', 'row': 'r1', 'col': 'val', 'value': '2.00'},
        ],
        'parts': [
          {'key': '1', 'text': 'T 等于 0.10 秒'},
        ],
      });
      expect(c.phase, SolvePhase.submitted);
      expect(c.evaluation!.state, EvaluationState.pending);
      expect(c.evaluation!.isCorrect, isNull);
      expect(c.events.single.uncertainty.reasonCode, 'subjective_self_check');
      expect(c.reviewItem, isNull);
    });

    test('只有笔迹也能提交（笔迹同步上去之后）', () async {
      final c = await started(e);
      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);

      await c.submit();

      expect(c.phase, SolvePhase.submitted);
      expect(
        e.backend.bodyOf(
          e.backend.requestsTo('POST', '/submit').single,
        )!['answer'],
        {'cells': <Object>[], 'parts': <Object>[]},
      );
    });

    test('提交之前不会去要自查要点和参考数据；提交之后取到，参考数据只在这时才有', () async {
      final c = await started(e);
      fillTables(c);
      expect(e.backend.requestsTo('GET', '/self-check'), isEmpty);
      expect(c.selfCheck, isNull);

      await c.submit();
      await until(() => c.selfCheck != null, reason: '自查要点没有取到');

      expect(c.selfCheck!.points, isNotEmpty);
      expect(c.selfCheck!.referenceCells, isNotEmpty);
      expect(
        c.selfCheck!.referenceCells.map((cell) => cell.value),
        containsAll(['0.400', '2.00']),
      );
    });

    test('再试一次：格子、文字、笔迹都清空，新建一份作答', () async {
      final c = await started(e);
      fillTables(c);
      c.setPart('1', '写过');
      await c.submit();

      await c.retry();

      expect(c.cells, isEmpty);
      expect(c.parts, isEmpty);
      expect(c.phase, SolvePhase.answering);
      expect(c.selfCheck, isNull);
    });

    test('版本冲突：使用云端稿之后，云端草稿里的格子也回来', () async {
      final c = await started(e);
      c.setCell('t1', 'r1', 'v', '0.4');
      await until(() => c.sync == SaveStatus.saved);
      // 别处把云端草稿改成了另一份
      e.backend.serverRevision = 5;
      e.backend.serverAnswer = {
        'cells': [
          {'table': 't1', 'row': 'r2', 'col': 'v', 'value': '别处写的'},
        ],
      };

      c.setCell('t1', 'r1', 'v', '0.41');
      await until(() => c.sync == SaveStatus.conflict, reason: '没有发现冲突');
      expect(c.cells, {'t1.r1.v': '0.41'}, reason: '本地稿原样保留');
      await c.resolveConflictUseServer();

      expect(c.cells, {'t1.r2.v': '别处写的'});
    });
  });

  group('登录失效', () {
    test('401：通知外层重新登录，未同步的草稿仍在本机', () async {
      final c = await started(h);
      h.backend.failNext = (401, 'unauthenticated');

      c.selectOption('A');
      await c.flushNow();
      await until(() => h.unauthenticated > 0);

      expect(c.authExpired, isTrue);
      expect(
        h.store.data.keys.any((k) => k.startsWith('u/$_user/draft/')),
        isTrue,
      );
    });
  });

  group('本地数据按用户隔离', () {
    test('另一个用户看不到这个用户的草稿', () async {
      final c = await started(h);
      c.selectOption('A');
      await c.flushNow();

      final other = DraftStore(h.store, 'user-2');
      expect(await other.readDraft(h.questionId), isNull);
      expect(
        await DraftStore(h.store, _user).readDraft(h.questionId),
        isNotNull,
      );
    });
  });
}
