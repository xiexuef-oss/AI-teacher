part of 'draft_store.dart';

Future<List<Map<String, dynamic>>> _exportQuestionCache(
  DraftStore store,
  int limit,
) async {
  if (store.userId.isEmpty || store.userId.contains('/') || limit < 1) {
    throw const FormatException('Invalid question cache scope');
  }
  final prefix = 'u/${store.userId}/question/';
  final keys = await store._store.keys(prefix);
  if (keys.length > limit) throw StateError('Recovery export too large');
  final result = <Map<String, dynamic>>[];
  for (final key in keys..sort()) {
    if (!key.startsWith(prefix)) {
      throw const FormatException('Wrong question cache namespace');
    }
    final match = RegExp(
      r'^([A-Za-z0-9._:-]+)(?:/((?:attempt|local)/[A-Za-z0-9._:-]+))?$',
    ).firstMatch(key.substring(prefix.length));
    if (match == null) {
      throw const FormatException('Invalid question cache key');
    }
    final raw = await store._store.read(key);
    if (raw == null) {
      throw const FormatException('Question cache changed during export');
    }
    try {
      final value = jsonDecode(raw) as Map<String, dynamic>;
      final version = value['version'];
      if (value['id'] != match[1] || version is! int || version < 1) {
        throw const FormatException(
          'Question cache identity or version mismatch',
        );
      }
      result.add({
        'question_id': match[1],
        'workspace': match[2],
        'question': Question.fromJson(value).toJson(),
      });
    } catch (_) {
      throw const FormatException('Unreadable question cache preserved');
    }
  }
  return result;
}

LocalDraft _checkedExportDraft(Map value, String questionId) {
  final raw = Map<String, dynamic>.from(value);
  if (raw['v'] != LocalDraft.formatVersion) {
    throw const FormatException('Unsupported export draft');
  }
  final draft = LocalDraft.fromJson(raw);
  if (draft.questionId != questionId) {
    throw const FormatException('Export question mismatch');
  }
  return draft;
}

Future<List<Map<String, dynamic>>> _exportPracticeJournals(
  DraftStore store,
  int limit,
) async {
  final owner = store.userId;
  if (owner.isEmpty || owner.contains('/') || limit < 1) {
    throw const FormatException('Invalid practice export scope');
  }
  if ((await store._store.keys('u/$owner/draft-corrupt/')).isNotEmpty) {
    throw const FormatException('Unreadable practice record preserved');
  }
  final prefix = 'u/$owner/draft-bundle/';
  final keys = await store._store.keys(prefix);
  if (keys.length > limit) throw StateError('Recovery export too large');
  var count = 0;
  void consume() {
    if (++count > limit) throw StateError('Recovery export too large');
  }

  Map<String, dynamic> request(Map value, Map<String, dynamic> parsed) {
    if (journalCanonical(value) != journalCanonical(parsed)) {
      throw const FormatException('Unsupported practice request preserved');
    }
    return parsed;
  }

  final result = <Map<String, dynamic>>[];
  for (final key in keys..sort()) {
    if (!key.startsWith(prefix)) {
      throw const FormatException('Wrong practice namespace');
    }
    final questionId = key.substring(prefix.length);
    if (!RegExp(r'^[A-Za-z0-9._:-]+$').hasMatch(questionId)) {
      throw const FormatException('Invalid practice key');
    }
    final before = count;
    final bundle = await store._bundle(questionId, requireExisting: true);
    List<Map<String, dynamic>> entries(
      String name,
      Map<String, dynamic> Function(String, Map<String, dynamic>) convert,
    ) {
      final values = <Map<String, dynamic>>[];
      for (final e in (bundle[name] as Map? ?? {}).entries) {
        consume();
        values.add(convert(e.key as String, journalClone(e.value as Map)));
      }
      return values;
    }

    Map<String, dynamic> draft(Map raw) =>
        _checkedExportDraft(raw, questionId).toJson();
    Map<String, dynamic> writeBody(WriteCommand command) =>
        request(command.body!, switch (command.lane) {
          'draft_sync' => DraftSync.fromJson(command.body!).toJson(),
          'self_check' => SelfCheckSave.fromJson(command.body!).toJson(),
          'submit' => SubmitRequest.fromJson(command.body!).toJson(),
          _ => throw const FormatException('Unknown practice lane'),
        });
    Map<String, dynamic>? writeResult(WriteCommand command) {
      final raw = command.result;
      if (raw == null) {
        if (['result_known', 'acked'].contains(command.phase)) {
          throw const FormatException('Missing practice receipt');
        }
        return null;
      }
      if (command.lane == 'draft_sync') {
        final value = Draft.fromJson(raw);
        if (value.attemptId != command.attemptId || value.revision < 0) {
          throw const FormatException('Wrong exported sync receipt');
        }
        return value.toJson();
      }
      if (command.lane == 'self_check') {
        final value = SelfCheck.fromJson(raw);
        if (value.attemptId != command.attemptId) {
          throw const FormatException('Wrong exported self-check receipt');
        }
        return value.toJson();
      }
      final value = SubmitResult.fromJson(raw);
      if (value.attempt.id != command.attemptId ||
          value.attempt.sessionId != command.sessionId ||
          value.session.id != command.sessionId ||
          value.session.questionId != questionId ||
          value.session.questionVersion != command.questionVersion ||
          value.attempt.status != AttemptStatus.submitted ||
          value.events.any(
            (e) =>
                e.sessionId != command.sessionId ||
                e.meta.questionId != questionId ||
                e.meta.questionVersion != command.questionVersion,
          )) {
        throw const FormatException('Wrong exported submit receipt');
      }
      return value.toJson();
    }

    final contexts = entries('workspaceContexts', (scope, raw) {
      final context = DraftWorkspaceContext.fromJson(raw);
      return {
        'workspace': scope,
        'workspace_id': context.workspaceId,
        'question_version': context.question.version,
        'question_snapshot': context.question.toJson(),
        'session_request': request(
          context.sessionBody,
          SessionCreate.fromJson(context.sessionBody).toJson(),
        ),
        'trusted_session_id': context.trustedSessionId,
      };
    });
    final creations = <Map<String, dynamic>>[];
    for (final e in (bundle['creationIntents'] as Map? ?? {}).entries) {
      final record = e.value as Map;
      for (final raw in (record['history'] as Map).values) {
        consume();
        final c = DraftCreationCommand.fromJson(journalClone(raw as Map));
        creations.add({
          'workspace': e.key as String,
          'current': c.intentId == record['current'],
          'intent_id': c.intentId,
          'generation': c.generation,
          'phase': c.phase,
          'session_key': c.sessionKey,
          'attempt_key': c.attemptKey,
          'session_request': request(c.sessionBody, c.sessionRequest.toJson()),
          'attempt_request': c.attemptBody == null
              ? null
              : request(c.attemptBody!, c.attemptRequest.toJson()),
          'session_id': c.sessionId,
          'attempt_id': c.attemptId,
          'question_version': c.questionVersion,
          'blocked_reason': c.blockedReason,
          'resume_phase': c.resumePhase,
          'transfer_policy': c.transferPolicy == null
              ? null
              : {
                  'kind': c.transferPolicy!['kind'] as String,
                  'continuation_id':
                      c.transferPolicy!['continuationId'] as String,
                },
        });
      }
    }
    final writes = <Map<String, dynamic>>[];
    for (final scope in (bundle['writeJournal'] as Map? ?? {}).entries) {
      for (final lane in (scope.value as Map).values) {
        final record = lane as Map;
        for (final raw in (record['history'] as Map).values) {
          consume();
          final c = WriteCommand.fromJson(journalClone(raw as Map));
          final source = draft(c.toJson()['sourceSnapshot'] as Map);
          writes.add({
            'workspace': scope.key as String,
            'current': c.intentId == record['current'],
            'intent_id': c.intentId,
            'key': c.idempotencyKey,
            'lane': c.lane,
            'phase': c.phase,
            'generation': c.generation,
            'edit_generation': c.editGeneration,
            'question_version': c.questionVersion,
            'session_id': c.sessionId,
            'attempt_id': c.attemptId,
            'source_snapshot': source,
            'body': c.body == null ? null : writeBody(c),
            'result': writeResult(c),
            'answer': c.answer == null
                ? null
                : request(
                    c.answer!,
                    AnswerPayload.fromJson(c.answer!).toJson(),
                  ),
            'elapsed_ms': c.elapsedMs,
            'sync_intent_id': c.syncIntentId,
            'waiting_sync_intent_id': c.waitingSyncIntentId,
            'blocked_reason': c.blockedReason,
            'resume_phase': c.toJson()['resumePhase'] as String?,
          });
        }
      }
    }
    final receipts = entries('writeReceipts', (id, raw) {
      final lane = raw['lane'];
      final context =
          (bundle['workspaceContexts'] as Map? ??
          {})['attempt/${raw['attemptId']}'];
      if (!['draft_sync', 'self_check'].contains(lane) ||
          !['acked', 'rejected'].contains(raw['phase']) ||
          context == null ||
          (context as Map)['trustedSessionId'] != raw['sessionId']) {
        throw const FormatException('Wrong compacted practice receipt');
      }
      return {
        'intent_id': id,
        'key': raw['idempotencyKey'] as String,
        'lane': lane,
        'phase': raw['phase'] as String,
        'session_id': raw['sessionId'] as String,
        'attempt_id': raw['attemptId'] as String,
        'revision': raw['revision'] as int?,
        'marks': lane == 'self_check'
            ? request(
                {'marks': raw['marks']},
                SelfCheckSave.fromJson({'marks': raw['marks']}).toJson(),
              )['marks']
            : null,
      };
    });
    final captures = entries('unboundSubmissions', (scope, raw) {
      final c = SubmissionCapture.fromJson(raw);
      final bound = raw['boundTo'] == null
          ? null
          : ActiveRef.fromJson(journalClone(raw['boundTo'] as Map)).toJson();
      if ((c.phase == 'bound') != (bound != null)) {
        throw const FormatException('Invalid bound capture');
      }
      return {
        'workspace': scope,
        'intent_id': c.intentId,
        'key': c.idempotencyKey,
        'phase': c.phase,
        'question_version': c.questionVersion,
        'edit_generation': c.editGeneration,
        'elapsed_ms': c.elapsedMs,
        'source_snapshot': draft(raw['sourceSnapshot'] as Map),
        'answer': request(c.answer, AnswerPayload.fromJson(c.answer).toJson()),
        'body_template': request(
          c.bodyTemplate,
          DraftSync.fromJson(c.bodyTemplate).toJson(),
        ),
        'bound_to': bound,
      };
    });
    final pending = entries('pending', (scope, raw) {
      final c = PendingDraftCopy.fromJson(raw);
      return {
        'workspace': scope,
        'key': c.idempotencyKey,
        'source_attempt_id': c.sourceAttemptId,
        'observed_revision': c.observedRevision,
        'recovery_generation': c.recoveryGeneration,
        'snapshot': draft(raw['snapshot'] as Map),
      };
    });
    final continuations = entries('continuations', (id, raw) {
      final c = DraftContinuation(raw);
      return {
        'id': id,
        'session_id': c.sessionId,
        'source_attempt_id': c.sourceAttemptId,
        'edit_generation': c.editGeneration,
        'draft': draft(raw['draft'] as Map),
        'consumed_by': raw['consumedBy'] == null
            ? null
            : ActiveRef.fromJson(journalClone(raw['consumedBy'] as Map))
                  .toJson(),
      };
    });
    final edits = entries('editState', (scope, raw) {
      final state = WriteEditState(raw);
      return {
        'workspace': scope,
        'draft_generation': state.draftGeneration,
        'marks_generation': state.marksGeneration,
        'known_revision': state.knownRevision,
        'marks': {for (final e in state.marks.entries) e.key: e.value.toJson()},
        'confirmed_marks': {
          for (final e in state.confirmedMarks.entries) e.key: e.value.toJson(),
        },
      };
    });
    final promotions = entries(
      'promotions',
      (scope, raw) => {
        'workspace': scope,
        'target_attempt_id': raw['targetAttemptId'] as String,
        'source_snapshot': draft(raw['source'] as Map),
      },
    );
    final references = entries(
      'references',
      (id, raw) => {'id': id, ...ActiveRef.fromJson(raw).toJson()},
    );
    result.add({
      'question_id': questionId,
      'record_count': count - before,
      'active': bundle['active'] == null
          ? null
          : ActiveRef.fromJson(journalClone(bundle['active'] as Map)).toJson(),
      'local_workspace_id': bundle['localId'] as String?,
      'cleared_workspaces': (bundle['cleared'] as List? ?? []).cast<String>(),
      'contexts': contexts,
      'creation_commands': creations,
      'write_commands': writes,
      'write_receipts': receipts,
      'unbound_submissions': captures,
      'pending_copies': pending,
      'continuations': continuations,
      'edit_state': edits,
      'promotions': promotions,
      'references': references,
    });
  }
  return result;
}
