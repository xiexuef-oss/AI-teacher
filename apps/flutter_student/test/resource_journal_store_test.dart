import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/solve/draft_store.dart';
import 'package:tutor_student/features/solve/resource_journal_store.dart';

import 'support/fake_backend.dart';

void main() {
  late MemoryStore memory;
  late DraftStore source;
  late ResourceJournalStore resources;
  late Fixtures fixtures;
  late Question question;
  late StudySession session;

  setUp(() async {
    memory = MemoryStore();
    fixtures = Fixtures.load();
    question = Question.fromJson(fixtures.value('question_single_choice'));
    session = StudySession.fromJson({
      ...fixtures.value('session_created'),
      'question_id': question.id,
      'question_version': question.version,
      'origin': 'practice',
    });
    final aid = fixtures.value('attempt_created')['id'] as String;
    source = DraftStore(memory, 'owner').forAttempt(aid);
    await source.claimScope(question.id);
    await source.saveWorkspaceContext(
      question.id,
      DraftWorkspaceContext(
        workspaceId: aid,
        question: question,
        trustedSessionId: session.id,
        sessionBody: SessionCreate(
          questionId: question.id,
          origin: SessionOrigin.practice,
          expectedQuestionVersion: question.version,
        ).toJson(),
      ),
    );
    await source.writeActive(
      question.id,
      ActiveRef(sessionId: session.id, attemptId: aid),
    );
    resources = ResourceJournalStore(memory, 'owner');
  });

  Future<
    ({
      DraftStore source,
      String intentId,
      Attempt first,
      StudySession session,
      ReviewState review,
    })
  >
  reviewEvidence({bool correct = false, String suffix = ''}) async {
    final sid = 'review-session$suffix', aid = 'review-first$suffix';
    const rid = 'review-R';
    final drafts = DraftStore(memory, 'owner').forAttempt(aid);
    await drafts.claimScope(question.id);
    await drafts.saveWorkspaceContext(
      question.id,
      DraftWorkspaceContext(
        workspaceId: aid,
        question: question,
        trustedSessionId: sid,
        sessionBody: SessionCreate(
          questionId: question.id,
          origin: SessionOrigin.review,
          reviewItemId: rid,
          expectedQuestionVersion: question.version,
        ).toJson(),
      ),
    );
    final local = LocalDraft(
      questionId: question.id,
      sessionId: sid,
      attemptId: aid,
      selected: ['A'],
      dirty: true,
      savedAt: DateTime.utc(2026),
    );
    await drafts.writeDraft(local);
    final capture = await drafts.prepareSubmissionCapture(
      question.id,
      sourceSnapshot: local,
      answer: local.asServer().answer!.toJson(),
      elapsedMs: 12,
      body: DraftSync(
        baseRevision: 0,
        answer: local.asServer().answer,
      ).toJson(),
    );
    final sync = await drafts.recordWriteResult(
      question.id,
      lane: 'draft_sync',
      intentId: capture.sync.intentId,
      expectedGeneration: capture.sync.generation,
      result: {...local.asServer().toJson(), 'revision': 1},
    );
    await drafts.ackDraftSync(
      question.id,
      intentId: sync.intentId,
      expectedGeneration: sync.generation,
    );
    final prepared = await drafts.finalizeSubmit(
      question.id,
      intentId: capture.submit.intentId,
      expectedGeneration: capture.submit.generation,
    );
    final raw = fixtures.value(correct ? 'submit_correct' : 'submit_incorrect');
    (raw['attempt'] as Map).addAll(<String, dynamic>{
      'id': aid,
      'session_id': sid,
      'submission_no': 1,
    });
    (raw['session'] as Map).addAll(<String, dynamic>{
      'id': sid,
      'question_id': question.id,
      'question_version': question.version,
      'origin': 'review',
      'review_item_id': rid,
    });
    final known = await drafts.recordWriteResult(
      question.id,
      lane: 'submit',
      intentId: prepared.intentId,
      expectedGeneration: prepared.generation,
      result: raw,
    );
    await drafts.ackSubmit(
      question.id,
      intentId: known.intentId,
      expectedGeneration: known.generation,
    );
    final result = SubmitResult.fromJson(raw);
    final state = ReviewState(
      id: rid,
      questionId: question.id,
      status: ReviewStatus.scheduled,
      stage: 0,
      totalStages: 3,
      dueAt: DateTime.utc(2026),
      updatedAt: DateTime.utc(2026),
    );
    return (
      source: drafts,
      intentId: known.intentId,
      first: result.attempt,
      session: StudySession.fromJson({
        ...result.session.toJson(),
        'first_submitted_attempt_id': aid,
      }),
      review: state,
    );
  }

  test(
    'session target shares one frozen intent across attempts without drafts',
    () async {
      final first = await resources.prepareTutor(
        source: source,
        questionId: question.id,
        sessionId: session.id,
        body: const TutorAction(
          action: TutorActionType.requestHint,
          confirmEndIndependent: false,
        ),
      );
      expect(await source.readDraft(question.id), isNull);
      final copy = source.forAttempt('copy');
      await copy.claimScope(question.id);
      await copy.saveWorkspaceContext(
        question.id,
        DraftWorkspaceContext(
          workspaceId: 'copy',
          question: question,
          trustedSessionId: session.id,
          sessionBody: (await source.readWorkspaceContext(question.id))!
              .sessionBody,
        ),
      );
      await expectLater(
        resources.prepareTutor(
          source: copy,
          questionId: question.id,
          sessionId: session.id,
          body: const TutorAction(
            action: TutorActionType.requestStandard,
            confirmEndIndependent: true,
          ),
        ),
        throwsStateError,
      );
      final restored = (await ResourceJournalStore(
        memory,
        'owner',
      ).read(ResourceTarget.session(session.id)))!;
      expect(restored.intentId, first.intentId);
      expect(restored.idempotencyKey, first.idempotencyKey);
      expect(restored.body['confirm_end_independent'], isFalse);
      expect(restored.source.attemptId, first.source.attemptId);
    },
  );

  test('recorded receipt refreshes without changing active and stale refresh cannot ack', () async {
    final command = await resources.prepareTutor(
      source: source,
      questionId: question.id,
      sessionId: session.id,
      body: const TutorAction(
        action: TutorActionType.requestHint,
        confirmEndIndependent: false,
      ),
    );
    final target = ResourceTarget.session(session.id);
    final known = await resources.recordResult(
      target,
      intentId: command.intentId,
      expectedGeneration: command.generation,
      result: TutorStep(session: session, events: []).toJson(),
    );
    final oldTicket = await resources.beginRefresh(
      target,
      intentId: known.intentId,
      expectedGeneration: known.generation,
    );
    final pending = (await resources.read(target))!;
    final currentTicket = await resources.beginRefresh(
      target,
      intentId: pending.intentId,
      expectedGeneration: pending.generation,
    );
    final events = ResourceEventRefresh(session.id)
      ..addPage(const TutorEventPage(items: [], lastSeq: 0));
    await expectLater(
      resources.ackTutor(oldTicket, latestSession: session, events: events),
      throwsStateError,
    );
    await source
        .forAttempt('C')
        .writeActive(
          question.id,
          const ActiveRef(sessionId: 'session-C', attemptId: 'C'),
        );
    final view = await resources.ackTutor(
      currentTicket,
      latestSession: session,
      events: events,
    );
    expect(view.session!.id, session.id);
    expect((await source.readActive(question.id))!.attemptId, 'C');
    expect((await resources.read(target))!.phase, 'acked');
  });
  test('450 events use actual page cursor and cache history once', () async {
    TutorEvent event(int seq) {
      final raw = (fixtures.value('tutor_hint')['events'] as List).first as Map;
      return TutorEvent.fromJson({
        ...Map<String, dynamic>.from(raw),
        'id': 'event-$seq',
        'session_id': session.id,
        'seq_no': seq,
        'meta': {
          ...Map<String, dynamic>.from(raw['meta'] as Map),
          'question_id': question.id,
          'question_version': question.version,
        },
      });
    }

    final pages = ResourceEventRefresh(session.id);
    pages.addPage(
      TutorEventPage(
        items: List.generate(200, (i) => event(i + 1)),
        lastSeq: 450,
      ),
    );
    expect(pages.nextAfterSeq, 200);
    expect(pages.complete, isFalse);
    pages.addPage(
      TutorEventPage(
        items: List.generate(200, (i) => event(i + 201)),
        lastSeq: 450,
      ),
    );
    pages.addPage(
      TutorEventPage(
        items: List.generate(50, (i) => event(i + 401)),
        lastSeq: 450,
      ),
    );
    pages.addPage(TutorEventPage(items: [event(1)], lastSeq: 450));
    expect(pages.events.length, 450);
    expect(pages.complete, isTrue);
    final target = ResourceTarget.session(session.id);
    final one = await resources.prepareTutor(
      source: source,
      questionId: question.id,
      sessionId: session.id,
      body: const TutorAction(action: TutorActionType.requestHint),
    );
    final old = StudySession.fromJson({
      ...session.toJson(),
      'used_solution': true,
      'assisted': true,
      'hint_level_revealed': 2,
    });
    final known = await resources.recordResult(
      target,
      intentId: one.intentId,
      expectedGeneration: one.generation,
      result: TutorStep(session: old, events: [event(1)]).toJson(),
    );
    final ticket = await resources.beginRefresh(
      target,
      intentId: known.intentId,
      expectedGeneration: known.generation,
    );
    final latest = StudySession.fromJson({
      ...session.toJson(),
      'last_event_seq': 450,
      'state': 'DONE',
      'confused_streak': 0,
    });
    final view = await resources.ackTutor(
      ticket,
      latestSession: latest,
      events: pages,
    );
    expect(view.events.length, 450);
    expect(view.session!.state, SessionState.done);
    expect(view.session!.usedSolution, isTrue);
    expect(view.session!.confusedStreak, 0);
    final two = await resources.prepareTutor(
      source: source,
      questionId: question.id,
      sessionId: session.id,
      body: const TutorAction(action: TutorActionType.requestHint),
    );
    expect(two.idempotencyKey, isNot(one.idempotencyKey));
    final resourceKey = 'u/owner/resource-journal/session/${session.id}';
    final raw = jsonDecode(memory.data[resourceKey]!) as Map;
    expect((raw['view']['events'] as List).length, 450);
    expect(
      (raw['history'][one.intentId]['resultSummary']['eventIds'] as List)
          .length,
      1,
    );
    expect(raw['history'][one.intentId]['result'], isNull);
    final knownTwo = await resources.recordResult(
      target,
      intentId: two.intentId,
      expectedGeneration: two.generation,
      result: TutorStep(session: latest, events: []).toJson(),
    );
    final ticketTwo = await resources.beginRefresh(
      target,
      intentId: knownTwo.intentId,
      expectedGeneration: knownTwo.generation,
    );
    final changed = ResourceEventRefresh(session.id)
      ..addPage(
        TutorEventPage(
          items: [
            TutorEvent.fromJson({
              ...event(1).toJson(),
              'id': 'changed-event-1',
            }),
            ...List.generate(449, (i) => event(i + 2)),
          ],
          lastSeq: 450,
        ),
      );
    await expectLater(
      resources.ackTutor(ticketTwo, latestSession: latest, events: changed),
      throwsStateError,
    );
  });

  test('all persistence windows leave prior state intact and damaged records stay raw', () async {
    final target = ResourceTarget.session(session.id);
    Future<ResourceCommand> prepare() => resources.prepareTutor(
      source: source,
      questionId: question.id,
      sessionId: session.id,
      body: const TutorAction(action: TutorActionType.requestHint),
    );
    memory.failWrites = true;
    await expectLater(prepare(), throwsStateError);
    memory.failWrites = false;
    expect(await resources.read(target), isNull);
    final command = await prepare();
    final result = TutorStep(session: session, events: []).toJson();
    var before = Map<String, String>.of(memory.data);
    memory.failWrites = true;
    await expectLater(
      resources.recordResult(
        target,
        intentId: command.intentId,
        expectedGeneration: command.generation,
        result: result,
      ),
      throwsStateError,
    );
    memory.failWrites = false;
    expect(memory.data, before);
    final known = await resources.recordResult(
      target,
      intentId: command.intentId,
      expectedGeneration: command.generation,
      result: result,
    );
    before = Map<String, String>.of(memory.data);
    await expectLater(prepare(), throwsStateError);
    expect(memory.data, before);
    await expectLater(
      resources.recordRejection(
        target,
        intentId: known.intentId,
        expectedGeneration: known.generation,
        status: 409,
        code: 'independent_attempt_in_progress',
      ),
      throwsStateError,
    );
    expect(memory.data, before);
    expect(
      (await resources.recordResult(
        target,
        intentId: known.intentId,
        expectedGeneration: known.generation,
        result: result,
      )).generation,
      known.generation,
    );
    expect(memory.data, before);
    memory.failWrites = true;
    await expectLater(
      resources.beginRefresh(
        target,
        intentId: known.intentId,
        expectedGeneration: known.generation,
      ),
      throwsStateError,
    );
    memory.failWrites = false;
    expect(memory.data, before);
    final ticket = await resources.beginRefresh(
      target,
      intentId: known.intentId,
      expectedGeneration: known.generation,
    );
    before = Map<String, String>.of(memory.data);
    final pages = ResourceEventRefresh(session.id)
      ..addPage(const TutorEventPage(items: [], lastSeq: 0));
    memory.failWrites = true;
    await expectLater(
      resources.ackTutor(ticket, latestSession: session, events: pages),
      throwsStateError,
    );
    memory.failWrites = false;
    expect(memory.data, before);
    final key = 'u/owner/resource-journal/${target.scope}';
    final original = memory.data[key]!;
    for (final field in ['owner', 'target', 'body', 'generation']) {
      final json = jsonDecode(original) as Map;
      json['history'][command.intentId][field] = field == 'generation'
          ? 99
          : field == 'body'
          ? {'confirm_end_independent': true}
          : 'changed';
      final raw = jsonEncode(json);
      memory.data[key] = raw;
      await expectLater(resources.read(target), throwsFormatException);
      expect(memory.data[key], raw);
    }
    memory.data[key] = original;
    expect(
      await ResourceJournalStore(memory, 'another-owner').read(target),
      isNull,
    );
    final mutable = command.body;
    mutable['action'] = 'request_standard';
    expect((await resources.read(target))!.body['action'], 'request_hint');
  });

  test('review uses acknowledged verified failed first C while provided B may be draft', () async {
    final evidence = await reviewEvidence(correct: false);
    expect(evidence.first.evaluation!.state, EvaluationState.verified);
    expect(evidence.first.evaluation!.isCorrect, isFalse);
    final copy = evidence.source.forAttempt('provided-B');
    await copy.claimScope(question.id);
    await copy.saveWorkspaceContext(
      question.id,
      DraftWorkspaceContext(
        workspaceId: 'provided-B',
        question: question,
        trustedSessionId: evidence.session.id,
        sessionBody: (await evidence.source.readWorkspaceContext(question.id))!
            .sessionBody,
      ),
    );
    final b = Attempt.fromJson({
      ...evidence.first.toJson(),
      'id': 'provided-B',
      'status': 'draft',
      'submission_no': null,
    });
    final command = await resources.prepareReviewCompletion(
      source: copy,
      questionId: question.id,
      reviewId: evidence.review.id,
      providedAttempt: b,
      firstAttemptId: evidence.first.id,
      submitIntentId: evidence.intentId,
      review: evidence.review,
    );
    expect(command.body, {'attempt_id': 'provided-B'});
    expect(command.toJson()['provenance']['firstAttemptId'], evidence.first.id);
    expect(command.toJson()['provenance']['kind'], 'submit_receipt');
    await expectLater(
      resources.prepareReviewCompletion(
        source: evidence.source,
        questionId: question.id,
        reviewId: evidence.review.id,
        providedAttempt: evidence.first,
        firstAttemptId: evidence.first.id,
        submitIntentId: evidence.intentId,
        review: evidence.review,
      ),
      throwsStateError,
    );
    final rejected = await resources.recordRejection(
      ResourceTarget.review(evidence.review.id),
      intentId: command.intentId,
      expectedGeneration: command.generation,
      status: 409,
      code: 'review_already_completed',
    );
    final ticket = await resources.beginRefresh(
      ResourceTarget.review(evidence.review.id),
      intentId: rejected.intentId,
      expectedGeneration: rejected.generation,
    );
    await resources.ackReview(
      ticket,
      latestState: ReviewState.fromJson({
        ...evidence.review.toJson(),
        'stage': 1,
      }),
    );
    expect(
      (await resources.read(ResourceTarget.review(evidence.review.id)))!.phase,
      'rejected',
    );
    expect(
      (await resources.readView(ResourceTarget.review(evidence.review.id)))!
          .review!
          .stage,
      1,
    );
  });

  test('observed provenance requires explicit new action and never recovers unknown submit', () async {
    final evidence = await reviewEvidence();
    Future<ResourceCommand> observed(bool confirmed) =>
        resources.prepareObservedReviewCompletion(
          source: evidence.source,
          questionId: question.id,
          reviewId: evidence.review.id,
          providedAttempt: evidence.first,
          firstAttempt: evidence.first,
          session: evidence.session,
          review: evidence.review,
          explicitConfirmation: confirmed,
        );
    await expectLater(observed(false), throwsStateError);
    await expectLater(
      resources.prepareReviewCompletion(
        source: evidence.source,
        questionId: question.id,
        reviewId: evidence.review.id,
        providedAttempt: evidence.first,
        firstAttemptId: evidence.first.id,
        submitIntentId: 'missing-receipt',
        review: evidence.review,
      ),
      throwsStateError,
    );
    // A fresh local intent on the same real Session remains unknown, even
    // though the readonly server representation says the first C submitted.
    final local = LocalDraft(
      questionId: question.id,
      sessionId: evidence.session.id,
      attemptId: evidence.first.id,
      selected: ['A'],
      dirty: true,
      savedAt: DateTime.utc(2026),
    );
    await evidence.source.writeDraft(local);
    await evidence.source.prepareSubmissionCapture(
      question.id,
      sourceSnapshot: local,
      answer: local.asServer().answer!.toJson(),
      elapsedMs: 12,
      body: DraftSync(
        baseRevision: 1,
        answer: local.asServer().answer,
      ).toJson(),
    );
    await expectLater(observed(true), throwsStateError);
  });

  test('explicit server observed path is separately recorded without a local submit receipt', () async {
    final evidence = await reviewEvidence();
    final bundleKey = 'u/owner/draft-bundle/${question.id}';
    final bundle = jsonDecode(memory.data[bundleKey]!) as Map;
    // Simulate local receipt loss, not a successful recovery of its old key.
    bundle.remove('writeJournal');
    memory.data[bundleKey] = jsonEncode(bundle);
    final missingPointer = StudySession.fromJson({
      ...evidence.session.toJson(),
      'first_submitted_attempt_id': null,
    });
    await expectLater(
      resources.prepareObservedReviewCompletion(
        source: evidence.source,
        questionId: question.id,
        reviewId: evidence.review.id,
        providedAttempt: evidence.first,
        firstAttempt: evidence.first,
        session: missingPointer,
        review: evidence.review,
        explicitConfirmation: true,
      ),
      throwsStateError,
    );
    final wrongFirst = Attempt.fromJson({
      ...evidence.first.toJson(),
      'id': 'not-the-actual-first',
    });
    await expectLater(
      resources.prepareObservedReviewCompletion(
        source: evidence.source,
        questionId: question.id,
        reviewId: evidence.review.id,
        providedAttempt: evidence.first,
        firstAttempt: wrongFirst,
        session: evidence.session,
        review: evidence.review,
        explicitConfirmation: true,
      ),
      throwsStateError,
    );
    final command = await resources.prepareObservedReviewCompletion(
      source: evidence.source,
      questionId: question.id,
      reviewId: evidence.review.id,
      providedAttempt: evidence.first,
      firstAttempt: evidence.first,
      session: evidence.session,
      review: evidence.review,
      explicitConfirmation: true,
    );
    expect(command.toJson()['provenance']['kind'], 'server_observed_explicit');
    expect(command.toJson()['provenance']['submitIntentId'], isNull);
  });
  test(
    'concurrent attempts share one unresolved session resource command',
    () async {
      final copy = source.forAttempt('concurrent-copy');
      await copy.claimScope(question.id);
      await copy.saveWorkspaceContext(
        question.id,
        DraftWorkspaceContext(
          workspaceId: 'concurrent-copy',
          question: question,
          trustedSessionId: session.id,
          sessionBody: (await source.readWorkspaceContext(question.id))!
              .sessionBody,
        ),
      );
      Future<bool> prepare(DraftStore origin) async {
        try {
          await resources.prepareTutor(
            source: origin,
            questionId: question.id,
            sessionId: session.id,
            body: const TutorAction(action: TutorActionType.requestHint),
          );
          return true;
        } on StateError {
          return false;
        }
      }

      final results = await Future.wait([prepare(source), prepare(copy)]);
      expect(results.where((value) => value).length, 1);
      final otherStore = DraftStore(
        MemoryStore(),
        'owner',
      ).forAttempt('unrelated');
      await expectLater(
        resources.prepareTutor(
          source: otherStore,
          questionId: question.id,
          sessionId: session.id,
          body: const TutorAction(action: TutorActionType.requestHint),
        ),
        throwsStateError,
      );
    },
  );

  test('different sessions share review target and success uses latest state not old completion', () async {
    final one = await reviewEvidence();
    final command = await resources.prepareReviewCompletion(
      source: one.source,
      questionId: question.id,
      reviewId: one.review.id,
      providedAttempt: one.first,
      firstAttemptId: one.first.id,
      submitIntentId: one.intentId,
      review: one.review,
    );
    final two = await reviewEvidence(suffix: '-two');
    await expectLater(
      resources.prepareReviewCompletion(
        source: two.source,
        questionId: question.id,
        reviewId: two.review.id,
        providedAttempt: two.first,
        firstAttemptId: two.first.id,
        submitIntentId: two.intentId,
        review: two.review,
      ),
      throwsStateError,
    );
    final target = ResourceTarget.review(one.review.id);
    final raw = fixtures.value('review_completed');
    (raw['review_item'] as Map)['id'] = one.review.id;
    (raw['review_item'] as Map)['question_id'] = question.id;
    raw['result'] = 'failed';
    final known = await resources.recordResult(
      target,
      intentId: command.intentId,
      expectedGeneration: command.generation,
      result: raw,
    );
    final ticket = await resources.beginRefresh(
      target,
      intentId: known.intentId,
      expectedGeneration: known.generation,
    );
    final latest = ReviewState.fromJson({
      ...one.review.toJson(),
      'stage': 0,
      'last_result': 'failed',
    });
    final view = await resources.ackReview(ticket, latestState: latest);
    expect(view.review!.stage, 0);
    expect(view.review!.lastResult, ReviewResult.failed);
    expect((await resources.read(target))!.phase, 'acked');
    final next = await resources.prepareReviewCompletion(
      source: two.source,
      questionId: question.id,
      reviewId: two.review.id,
      providedAttempt: two.first,
      firstAttemptId: two.first.id,
      submitIntentId: two.intentId,
      review: two.review,
    );
    final knownNext = await resources.recordResult(
      target,
      intentId: next.intentId,
      expectedGeneration: next.generation,
      result: raw,
    );
    final ticketNext = await resources.beginRefresh(
      target,
      intentId: knownNext.intentId,
      expectedGeneration: knownNext.generation,
    );
    final before = Map<String, String>.of(memory.data);
    final newer = ReviewState.fromJson({...latest.toJson(), 'stage': 1});
    memory.failWrites = true;
    await expectLater(
      resources.ackReview(ticketNext, latestState: newer),
      throwsStateError,
    );
    memory.failWrites = false;
    expect(memory.data, before);
    expect((await resources.read(target))!.phase, 'result_known');
    expect((await resources.read(target))!.generation, ticketNext.generation);
    expect((await resources.readView(target))!.review!.stage, 0);
    await resources.ackReview(ticketNext, latestState: newer);
    expect((await resources.readView(target))!.review!.stage, 1);
    final saved = Map.of(memory.data);
    final exported = (await resources.exportSnapshot()).single;
    expect(exported['view']['review']['stage'], 1);
    expect(exported['commands'].length, 2);
    expect(exported['commands'][0]['compacted_receipt'], true);
    expect(
      exported['commands'][0]['provenance']['submit_intent_id'],
      one.intentId,
    );
    expect(
      exported['commands'][1]['result_summary']['completion']['review_item']['id'],
      target.id,
    );
    expect(memory.data, saved);
  });
  test('event collector rejects identity conflicts and cannot complete across missing pages', () {
    final raw = Map<String, dynamic>.from(
      (fixtures.value('tutor_hint')['events'] as List).first as Map,
    );
    TutorEvent event(
      int sequence, {
      String? id,
      Map<String, dynamic>? payload,
    }) => TutorEvent.fromJson({
      ...raw,
      'session_id': session.id,
      'id': id ?? 'event-$sequence',
      'seq_no': sequence,
      'payload': ?payload,
      'meta': {
        ...Map<String, dynamic>.from(raw['meta'] as Map),
        'question_id': question.id,
        'question_version': question.version,
      },
    });
    final duplicateId = ResourceEventRefresh(session.id)
      ..addPage(TutorEventPage(items: [event(1)], lastSeq: 3));
    expect(
      () => duplicateId.addPage(
        TutorEventPage(items: [event(2, id: 'event-1')], lastSeq: 3),
      ),
      throwsStateError,
    );
    expect(duplicateId.events.map((e) => e.seqNo), [1]);
    expect(duplicateId.complete, isFalse);
    final alteredPayload = ResourceEventRefresh(session.id)
      ..addPage(TutorEventPage(items: [event(1)], lastSeq: 3));
    expect(
      () => alteredPayload.addPage(
        TutorEventPage(
          items: [
            event(1, payload: {...event(1).payload, 'text': 'changed'}),
          ],
          lastSeq: 3,
        ),
      ),
      throwsStateError,
    );
    expect(alteredPayload.events.single.toJson(), event(1).toJson());
    final missing = ResourceEventRefresh(session.id)
      ..addPage(TutorEventPage(items: [event(1), event(3)], lastSeq: 3));
    expect(missing.nextAfterSeq, 3);
    expect(missing.complete, isFalse);
    missing.addPage(const TutorEventPage(items: [], lastSeq: 3));
    expect(missing.complete, isFalse);
    final empty = ResourceEventRefresh(session.id)
      ..addPage(const TutorEventPage(items: [], lastSeq: 3));
    expect(empty.nextAfterSeq, 0);
    expect(empty.complete, isFalse);
  });

  test('failed shared owner transaction does not block another question or resource', () async {
    memory.failWrites = true;
    await expectLater(
      resources.prepareTutor(
        source: source,
        questionId: question.id,
        sessionId: session.id,
        body: const TutorAction(action: TutorActionType.requestHint),
      ),
      throwsStateError,
    );
    memory.failWrites = false;
    final otherQuestion = Question.fromJson({
      ...question.toJson(),
      'id': 'other-question',
    });
    final other = DraftStore(memory, 'owner').forAttempt('other-attempt');
    await other
        .claimScope(otherQuestion.id)
        .timeout(const Duration(seconds: 3));
    await other
        .saveWorkspaceContext(
          otherQuestion.id,
          DraftWorkspaceContext(
            workspaceId: 'other-attempt',
            question: otherQuestion,
            trustedSessionId: 'other-session',
            sessionBody: SessionCreate(
              questionId: otherQuestion.id,
              origin: SessionOrigin.practice,
              expectedQuestionVersion: otherQuestion.version,
            ).toJson(),
          ),
        )
        .timeout(const Duration(seconds: 3));
    final command = await resources
        .prepareTutor(
          source: other,
          questionId: otherQuestion.id,
          sessionId: 'other-session',
          body: const TutorAction(action: TutorActionType.requestHint),
        )
        .timeout(const Duration(seconds: 3));
    expect(command.source.questionId, otherQuestion.id);
    expect(command.phase, 'prepared');
    expect(
      (await resources.read(ResourceTarget.session('other-session')))!.intentId,
      command.intentId,
    );
    expect(await resources.read(ResourceTarget.session(session.id)), isNull);
    expect(await other.readDraft(otherQuestion.id), isNull);
  });
}
