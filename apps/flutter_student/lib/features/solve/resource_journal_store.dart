import 'package:tutor_contracts/tutor_contracts.dart';

import 'dart:convert';

import '../../core/storage.dart';
import '../../core/local_serial.dart';
import '../../core/idempotency.dart';
import 'draft_store.dart';

Map<String, dynamic> _seal(Map<String, dynamic> value) {
  final raw = journalClone(value)..remove('checksum');
  raw['checksum'] = journalHash(raw);
  return raw;
}

Map<String, dynamic> _verified(Map value) {
  final raw = journalClone(value);
  final checksum = raw.remove('checksum');
  if (checksum != journalHash(raw)) {
    throw const FormatException('Damaged resource record preserved');
  }
  raw['checksum'] = checksum;
  return raw;
}

class ResourceTarget {
  ResourceTarget.session(String id) : this._('session', id);
  ResourceTarget.review(String id) : this._('review', id);
  ResourceTarget._(this.kind, this.id) {
    if (!RegExp(r'^[A-Za-z0-9._:-]+$').hasMatch(id)) {
      throw ArgumentError('Invalid resource ID');
    }
  }
  final String kind, id;
  String get scope => '$kind/$id';
}

class ResourceSourceGuard {
  ResourceSourceGuard(Map<String, dynamic> value) : _json = journalClone(value);
  final Map<String, dynamic> _json;
  Map<String, dynamic> toJson() => journalClone(_json);
  String get owner => _json['owner'] as String;
  String get questionId => _json['questionId'] as String;
  int get questionVersion => _json['questionVersion'] as int;
  String get sessionId => _json['sessionId'] as String;
  String get attemptId => _json['attemptId'] as String;
  String get workspaceId => _json['workspaceId'] as String;
  int get activeEpoch => _json['activeEpoch'] as int;
  int get viewGeneration => _json['viewGeneration'] as int;
  int get editGeneration => _json['editGeneration'] as int;
  String? get reviewId => _json['reviewId'] as String?;
  String get origin => _json['origin'] as String;
}

class ConfirmedSubmissionEvidence {
  ConfirmedSubmissionEvidence(Map<String, dynamic> value)
    : _json = journalClone(value);
  final Map<String, dynamic> _json;
  Map<String, dynamic> toJson() => journalClone(_json);
}

class ResourceCommand {
  ResourceCommand._(this._json);
  final Map<String, dynamic> _json;
  factory ResourceCommand.fromJson(Map value) {
    final raw = _verified(value);
    if (raw['v'] != 1 ||
        raw['generation'] is! int ||
        raw['generation'] < 1 ||
        ![
          'prepared',
          'result_known',
          'rejection_known',
          'acked',
          'rejected',
          'blocked',
        ].contains(raw['phase'])) {
      throw const FormatException('Unknown resource command preserved');
    }
    return ResourceCommand._(raw);
  }
  Map<String, dynamic> toJson() => journalClone(_json);
  String get intentId => _json['intentId'] as String;
  String get idempotencyKey => _json['idempotencyKey'] as String;
  String get phase => _json['phase'] as String;
  int get generation => _json['generation'] as int;
  Map<String, dynamic> get body => journalClone(_json['body'] as Map);
  Map<String, dynamic>? get result =>
      _json['result'] == null ? null : journalClone(_json['result'] as Map);
  ResourceSourceGuard get source =>
      ResourceSourceGuard(journalClone(_json['source'] as Map));
  String get path => _json['path'] as String;
  String get method => _json['method'] as String;
}

class ResourceRefreshTicket {
  ResourceRefreshTicket._(
    this.target,
    this.intentId,
    this.generation,
    this.refreshId,
  );
  final ResourceTarget target;
  final String intentId, refreshId;
  final int generation;
}

class ResourceView {
  ResourceView(Map value) : _json = journalClone(value);
  final Map<String, dynamic> _json;
  StudySession? get session => _json['session'] == null
      ? null
      : StudySession.fromJson(journalClone(_json['session'] as Map));
  ReviewState? get review => _json['review'] == null
      ? null
      : ReviewState.fromJson(journalClone(_json['review'] as Map));
  List<TutorEvent> get events => [
    for (final value in _json['events'] as List? ?? [])
      TutorEvent.fromJson(journalClone(value as Map)),
  ];
}

/// after_seq advances by actual events, never by the server's global last_seq.
class ResourceEventRefresh {
  ResourceEventRefresh(this.sessionId);
  final String sessionId;
  final Map<int, TutorEvent> _events = {};
  final Map<String, int> _ids = {};
  int _cursor = 0, _highWater = 0;
  bool _readPage = false;
  int get nextAfterSeq => _cursor;
  int get highWater => _highWater;
  bool get complete =>
      _readPage &&
      _cursor >= _highWater &&
      _events.length == _cursor &&
      (_cursor == 0 || _events.keys.reduce((a, b) => a < b ? a : b) == 1);
  void addPage(TutorEventPage page) {
    if (page.lastSeq < 0) throw StateError('Invalid event high-water mark');
    var cursor = _cursor;
    for (final supplied in page.items) {
      final event = TutorEvent.fromJson(journalClone(supplied.toJson()));
      if (event.sessionId != sessionId ||
          event.seqNo < 1 ||
          event.seqNo > page.lastSeq) {
        throw StateError('Event resource mismatch');
      }
      final previous = _events[event.seqNo];
      if ((previous != null &&
              journalCanonical(previous.toJson()) !=
                  journalCanonical(event.toJson())) ||
          (_ids.containsKey(event.id) && _ids[event.id] != event.seqNo)) {
        throw StateError('Event identity conflict');
      }
      _events[event.seqNo] = event;
      _ids[event.id] = event.seqNo;
      if (event.seqNo > cursor) cursor = event.seqNo;
    }
    _readPage = true;
    _cursor = cursor;
    if (page.lastSeq > _highWater) _highWater = page.lastSeq;
  }

  List<TutorEvent> get events {
    final values = _events.values.toList()
      ..sort((a, b) => a.seqNo.compareTo(b.seqNo));
    return [
      for (final event in values)
        TutorEvent.fromJson(journalClone(event.toJson())),
    ];
  }
}

class ResourceJournalStore {
  ResourceJournalStore(this.store, this.owner);
  final KeyValueStore store;
  final String owner;

  Map<String, dynamic> _exportResult(
    ResourceTarget target,
    ResourceSourceGuard source,
    Map value,
  ) {
    if (target.kind == 'session') {
      final step = TutorStep.fromJson(journalClone(value));
      if (step.session.id != target.id ||
          step.session.questionId != source.questionId ||
          step.session.questionVersion != source.questionVersion) {
        throw const FormatException('Wrong exported tutor receipt');
      }
      for (final event in step.events) {
        _validateEvent(event, source, target.id);
      }
      return step.toJson();
    }
    final result = ReviewCompletion.fromJson(journalClone(value));
    if (result.reviewItem.id != target.id ||
        result.reviewItem.questionId != source.questionId) {
      throw const FormatException('Wrong exported review receipt');
    }
    return result.toJson();
  }

  Map<String, dynamic>? _exportRejection(dynamic value) => value == null
      ? null
      : {
          'status': (value as Map)['status'] as int,
          'code': value['code'] as String,
        };

  Map<String, dynamic> _exportCommand(
    ResourceTarget target,
    Map value,
    String questionId,
  ) {
    final source = ResourceSourceGuard(journalClone(value['source'] as Map));
    if (source.owner != owner ||
        source.questionId != questionId ||
        source.questionVersion < 1 ||
        source.editGeneration < 0 ||
        source.viewGeneration < 0 ||
        (value['receipt'] == true &&
            !['acked', 'rejected'].contains(value['phase'])) ||
        (target.kind == 'session' && source.sessionId != target.id) ||
        (target.kind == 'review' && source.reviewId != target.id)) {
      throw const FormatException('Wrong exported resource source');
    }
    final summary = value['resultSummary'] as Map?;
    final provenance = value['provenance'] as Map?;
    if (provenance != null &&
        (provenance['owner'] != owner ||
            provenance['questionId'] != questionId ||
            provenance['reviewId'] != target.id)) {
      throw const FormatException('Wrong exported review provenance');
    }
    return {
      'intent_id': value['intentId'] as String,
      'key': value['idempotencyKey'] as String,
      'phase': value['phase'] as String,
      'generation': value['generation'] as int?,
      'compacted_receipt': value['receipt'] == true,
      'body': target.kind == 'session'
          ? TutorAction.fromJson(journalClone(value['body'] as Map)).toJson()
          : ReviewComplete.fromJson(journalClone(value['body'] as Map))
                .toJson(),
      'source': {
        'question_id': source.questionId,
        'question_version': source.questionVersion,
        'session_id': source.sessionId,
        'attempt_id': source.attemptId,
        'workspace_id': source.workspaceId,
        'review_id': source.reviewId,
        'origin': source.origin,
        'edit_generation': source.editGeneration,
        'view_generation': source.viewGeneration,
      },
      'result': value['result'] == null
          ? null
          : _exportResult(target, source, value['result'] as Map),
      'rejection': _exportRejection(
        value['rejection'] ?? summary?['rejection'],
      ),
      'result_summary': summary == null
          ? null
          : {
              if (summary['eventIds'] != null)
                'event_ids': (summary['eventIds'] as List).cast<String>(),
              if (summary['completion'] != null)
                'completion': _exportResult(
                  target,
                  source,
                  summary['completion'] as Map,
                ),
            },
      'provenance': provenance == null
          ? null
          : {
              'kind': provenance['kind'] as String,
              'first_attempt_id': provenance['firstAttemptId'] as String,
              'submission_no': provenance['submissionNo'] as int,
              if (provenance['submitIntentId'] != null)
                'submit_intent_id': provenance['submitIntentId'] as String,
              if (provenance['submitKey'] != null)
                'submit_key': provenance['submitKey'] as String,
              if (provenance['evaluationState'] != null)
                'evaluation_state': provenance['evaluationState'] as String,
              if (provenance['explicitConfirmation'] != null)
                'explicit_confirmation':
                    provenance['explicitConfirmation'] as bool,
            },
    };
  }

  Future<List<Map<String, dynamic>>> exportSnapshot({int limit = 1000}) =>
      LocalSerial.run(store, owner, () async {
        final prefix = 'u/$owner/resource-journal/';
        final keys = await store.keys(prefix);
        if (limit < 1 || keys.length > limit) {
          throw StateError('Recovery export too large');
        }
        final result = <Map<String, dynamic>>[];
        var commands = 0;
        for (final key in keys..sort()) {
          if (!key.startsWith(prefix)) {
            throw const FormatException('Wrong resource namespace');
          }
          final parts = key.substring(prefix.length).split('/');
          if (parts.length != 2 || !['session', 'review'].contains(parts[0])) {
            throw const FormatException('Unknown resource key preserved');
          }
          final target = parts[0] == 'session'
              ? ResourceTarget.session(parts[1])
              : ResourceTarget.review(parts[1]);
          final data = await _load(target);
          if (data['questionId'] is! String) {
            throw const FormatException('Missing resource journal');
          }
          final history = (data['history'] as Map).values.toList();
          commands += history.length;
          if (commands > limit) throw StateError('Recovery export too large');
          final current = _current(data);
          final source = current?.source;
          final view = data['view'] as Map?;
          Map<String, dynamic>? exportedView;
          if (view != null) {
            if (source == null) {
              throw const FormatException('Missing resource view source');
            }
            if (target.kind == 'session') {
              exportedView = _exportResult(target, source, view);
            } else {
              final review = ReviewState.fromJson(
                journalClone(view['review'] as Map),
              );
              if (review.id != target.id ||
                  review.questionId != source.questionId) {
                throw const FormatException('Wrong exported review view');
              }
              exportedView = {'review': review.toJson()};
            }
          }
          result.add({
            'kind': target.kind,
            'id': target.id,
            'question_id': data['questionId'],
            'current_intent_id': data['current'],
            'view': exportedView,
            'commands': [
              for (final item in history)
                _exportCommand(
                  target,
                  item as Map,
                  data['questionId'] as String,
                ),
            ],
          });
        }
        return result;
      });
  String _key(ResourceTarget target) =>
      'u/$owner/resource-journal/${target.scope}';
  Future<Map<String, dynamic>> _load(ResourceTarget target) async {
    final text = await store.read(_key(target));
    if (text == null) {
      return {
        'v': 1,
        'owner': owner,
        'target': target.scope,
        'history': <String, dynamic>{},
      };
    }
    final raw = _verified(jsonDecode(text) as Map);
    if (raw['v'] != 1 ||
        raw['owner'] != owner ||
        raw['target'] != target.scope ||
        raw['history'] is! Map) {
      throw const FormatException('Unknown resource journal preserved');
    }
    for (final entry in (raw['history'] as Map).entries) {
      final value = entry.value as Map;
      if (value['receipt'] == true) {
        final receipt = _verified(value);
        if (receipt['intentId'] != entry.key ||
            receipt['owner'] != owner ||
            receipt['target'] != target.scope) {
          throw const FormatException('Invalid resource receipt');
        }
        continue;
      }
      final command = ResourceCommand.fromJson(value);
      final data = command.toJson();
      final expectedPath = target.kind == 'session'
          ? '/tutor/sessions/${target.id}/next'
          : '/reviews/${target.id}/complete';
      if (data['owner'] != owner ||
          data['target'] != target.scope ||
          command.intentId != entry.key ||
          data['questionId'] != raw['questionId'] ||
          command.source.owner != owner ||
          command.source.questionId != raw['questionId'] ||
          command.method != 'POST' ||
          command.path != expectedPath ||
          (target.kind == 'session' && command.source.sessionId != target.id)) {
        throw const FormatException('Resource identity mismatch');
      }
      if (target.kind == 'session') {
        TutorAction.fromJson(command.body);
      } else {
        ReviewComplete.fromJson(command.body);
      }
    }
    if (raw['current'] != null &&
        !(raw['history'] as Map).containsKey(raw['current'])) {
      throw const FormatException('Missing current resource intent');
    }
    return raw;
  }

  ResourceCommand? _current(Map<String, dynamic> data) {
    final raw = (data['history'] as Map)[data['current']];
    return raw == null ? null : ResourceCommand.fromJson(raw as Map);
  }

  Future<void> _save(ResourceTarget target, Map<String, dynamic> data) =>
      store.write(_key(target), jsonEncode(_seal(data)));
  void _put(Map<String, dynamic> data, ResourceCommand command) {
    data['current'] = command.intentId;
    (data['history'] as Map)[command.intentId] = command.toJson();
  }

  ResourceCommand _cas(
    Map<String, dynamic> data,
    String intentId,
    int generation,
  ) {
    final command =
        _current(data) ?? (throw StateError('No pending resource action'));
    if (command.intentId != intentId || command.generation != generation) {
      throw StateError('Stale resource generation');
    }
    return command;
  }

  ResourceCommand _next(ResourceCommand command, Map<String, dynamic> patch) =>
      ResourceCommand.fromJson(
        _seal({
          ...command.toJson(),
          ...patch,
          'generation': command.generation + 1,
        }),
      );
  Future<ResourceCommand?> read(ResourceTarget target) async =>
      _current(await _load(target));
  Future<ResourceView?> readView(ResourceTarget target) async {
    final data = await _load(target);
    return data['view'] == null ? null : ResourceView(data['view'] as Map);
  }

  Future<ResourceCommand> _prepare(
    ResourceTarget target,
    DraftStore source,
    String questionId,
    Map<String, dynamic> body,
    int viewGeneration,
    Future<ConfirmedSubmissionEvidence?> Function(ResourceSourceGuard) proof,
  ) => LocalSerial.run(store, owner, () async {
    if (source.userId != owner || !source.sharesStorage(store)) {
      throw StateError('Wrong resource owner');
    }
    final guard = await source.readResourceOrigin(
      questionId,
      viewGeneration: viewGeneration,
    );
    final evidence = await proof(guard);
    final data = await _load(target);
    if (data['questionId'] != null && data['questionId'] != questionId) {
      throw StateError('Resource question changed');
    }
    final old = _current(data);
    if (old != null) {
      if (!['acked', 'rejected'].contains(old.phase)) {
        throw StateError('Resource action still unresolved');
      }
      (data['history'] as Map)[old.intentId] = _seal({
        'v': 1,
        'receipt': true,
        'owner': owner,
        'target': target.scope,
        'intentId': old.intentId,
        'idempotencyKey': old.idempotencyKey,
        'phase': old.phase,
        'body': old.body,
        'source': old.source.toJson(),
        'resultSummary': old.toJson()['resultSummary'],
        'provenance': old.toJson()['provenance'],
      });
    }
    data['questionId'] = questionId;
    final command = ResourceCommand.fromJson(
      _seal({
        'v': 1,
        'owner': owner,
        'target': target.scope,
        'questionId': questionId,
        'source': guard.toJson(),
        'intentId': newIdempotencyKey('resource-intent'),
        'idempotencyKey': newIdempotencyKey(
          target.kind == 'session' ? 'tutor' : 'review',
        ),
        'method': 'POST',
        'path': target.kind == 'session'
            ? '/tutor/sessions/${target.id}/next'
            : '/reviews/${target.id}/complete',
        'body': body,
        'phase': 'prepared',
        'generation': 1,
        'provenance': evidence?.toJson(),
      }),
    );
    _put(data, command);
    await _save(target, data);
    return command;
  });
  Future<ResourceCommand> prepareTutor({
    required DraftStore source,
    required String questionId,
    required String sessionId,
    required TutorAction body,
    int viewGeneration = 0,
  }) => _prepare(
    ResourceTarget.session(sessionId),
    source,
    questionId,
    body.toJson(),
    viewGeneration,
    (guard) async {
      if (guard.sessionId != sessionId) {
        throw StateError('Tutor session differs from source');
      }
      return null;
    },
  );
  Future<ResourceCommand> prepareReviewCompletion({
    required DraftStore source,
    required String questionId,
    required String reviewId,
    required Attempt providedAttempt,
    required String firstAttemptId,
    required String submitIntentId,
    required ReviewState review,
    int viewGeneration = 0,
  }) => _prepare(
    ResourceTarget.review(reviewId),
    source,
    questionId,
    ReviewComplete(attemptId: providedAttempt.id).toJson(),
    viewGeneration,
    (guard) async {
      final evidence = await source.readConfirmedSubmission(
        questionId,
        firstAttemptId: firstAttemptId,
        submitIntentId: submitIntentId,
      );
      final value = evidence.toJson();
      if (guard.origin != 'review' ||
          guard.reviewId != reviewId ||
          review.id != reviewId ||
          review.questionId != questionId ||
          guard.sessionId != providedAttempt.sessionId ||
          value['sessionId'] != providedAttempt.sessionId ||
          value['reviewId'] != reviewId ||
          value['questionVersion'] != guard.questionVersion) {
        throw StateError('Review submission provenance mismatch');
      }
      return evidence;
    },
  );
  Future<ResourceCommand> prepareObservedReviewCompletion({
    required DraftStore source,
    required String questionId,
    required String reviewId,
    required Attempt providedAttempt,
    required Attempt firstAttempt,
    required StudySession session,
    required ReviewState review,
    required bool explicitConfirmation,
    int viewGeneration = 0,
  }) => _prepare(
    ResourceTarget.review(reviewId),
    source,
    questionId,
    ReviewComplete(attemptId: providedAttempt.id).toJson(),
    viewGeneration,
    (guard) async {
      if (!explicitConfirmation ||
          await source.hasUnresolvedSubmission(questionId, session.id)) {
        throw StateError(
          'Explicit new action required; recover unknown submit first',
        );
      }
      if (guard.origin != 'review' ||
          guard.reviewId != reviewId ||
          session.id != guard.sessionId ||
          session.questionId != questionId ||
          session.questionVersion != guard.questionVersion ||
          session.origin != SessionOrigin.review ||
          session.reviewItemId != reviewId ||
          review.id != reviewId ||
          review.questionId != questionId ||
          providedAttempt.sessionId != session.id ||
          session.firstSubmittedAttemptId != firstAttempt.id ||
          firstAttempt.sessionId != session.id ||
          firstAttempt.submissionNo != 1 ||
          firstAttempt.status != AttemptStatus.submitted ||
          firstAttempt.evaluation?.state != EvaluationState.verified) {
        throw StateError('Observed first submission mismatch');
      }
      return ConfirmedSubmissionEvidence({
        'kind': 'server_observed_explicit',
        'owner': owner,
        'questionId': questionId,
        'questionVersion': guard.questionVersion,
        'sessionId': session.id,
        'reviewId': reviewId,
        'firstAttemptId': firstAttempt.id,
        'submissionNo': 1,
        'observedHash': journalHash({
          'session': session.toJson(),
          'first': firstAttempt.toJson(),
          'review': review.toJson(),
        }),
        'explicitConfirmation': true,
      });
    },
  );
  Future<ResourceCommand> recordResult(
    ResourceTarget target, {
    required String intentId,
    required int expectedGeneration,
    required Map<String, dynamic> result,
  }) => LocalSerial.run(store, owner, () async {
    final data = await _load(target);
    final command = _cas(data, intentId, expectedGeneration);
    if (command.phase == 'result_known' &&
        journalCanonical(command.result) == journalCanonical(result)) {
      return command;
    }
    if (command.phase != 'prepared') {
      throw StateError('Resource request is not prepared');
    }
    if (target.kind == 'session') {
      final step = TutorStep.fromJson(result);
      if (step.session.id != target.id ||
          step.session.questionId != command.source.questionId ||
          step.session.questionVersion != command.source.questionVersion) {
        throw StateError('Tutor receipt resource mismatch');
      }
      for (final event in step.events) {
        _validateEvent(event, command.source, target.id);
      }
    } else {
      final completion = ReviewCompletion.fromJson(result);
      if (completion.reviewItem.id != target.id ||
          completion.reviewItem.questionId != command.source.questionId) {
        throw StateError('Review receipt mismatch');
      }
    }
    final next = _next(command, {'phase': 'result_known', 'result': result});
    _put(data, next);
    await _save(target, data);
    return next;
  });
  void _validateEvent(
    TutorEvent event,
    ResourceSourceGuard source,
    String sessionId,
  ) {
    if (event.sessionId != sessionId ||
        event.meta.questionId != source.questionId ||
        event.meta.questionVersion != source.questionVersion ||
        event.seqNo < 1) {
      throw StateError('Teaching event resource mismatch');
    }
  }

  Future<ResourceCommand> recordRejection(
    ResourceTarget target, {
    required String intentId,
    required int expectedGeneration,
    required int status,
    required String code,
  }) => LocalSerial.run(store, owner, () async {
    final data = await _load(target);
    final command = _cas(data, intentId, expectedGeneration);
    if (command.phase != 'prepared' ||
        status < 400 ||
        status >= 500 ||
        status == 401) {
      throw StateError('Not a definite business rejection');
    }
    final next = _next(command, {
      'phase': 'rejection_known',
      'rejection': {'status': status, 'code': code},
    });
    _put(data, next);
    await _save(target, data);
    return next;
  });
  Future<ResourceCommand> block(
    ResourceTarget target, {
    required String intentId,
    required int expectedGeneration,
    required String reason,
  }) => LocalSerial.run(store, owner, () async {
    final data = await _load(target);
    final command = _cas(data, intentId, expectedGeneration);
    if (command.phase != 'prepared') throw StateError('Cannot block a receipt');
    final next = _next(command, {'phase': 'blocked', 'reason': reason});
    _put(data, next);
    await _save(target, data);
    return next;
  });
  Future<ResourceCommand> resume(
    ResourceTarget target, {
    required String intentId,
    required int expectedGeneration,
  }) => LocalSerial.run(store, owner, () async {
    final data = await _load(target);
    final command = _cas(data, intentId, expectedGeneration);
    if (command.phase != 'blocked') throw StateError('Not blocked');
    final next = _next(command, {'phase': 'prepared', 'reason': null});
    _put(data, next);
    await _save(target, data);
    return next;
  });
  Future<ResourceRefreshTicket> beginRefresh(
    ResourceTarget target, {
    required String intentId,
    required int expectedGeneration,
  }) => LocalSerial.run(store, owner, () async {
    final data = await _load(target);
    final command = _cas(data, intentId, expectedGeneration);
    if (!['result_known', 'rejection_known'].contains(command.phase)) {
      throw StateError('No known outcome to refresh');
    }
    final id = newIdempotencyKey('refresh');
    final next = _next(command, {'refreshId': id});
    _put(data, next);
    await _save(target, data);
    return ResourceRefreshTicket._(target, next.intentId, next.generation, id);
  });
  ResourceCommand _ticket(
    Map<String, dynamic> data,
    ResourceRefreshTicket ticket,
  ) {
    final command = _cas(data, ticket.intentId, ticket.generation);
    if (!['result_known', 'rejection_known'].contains(command.phase) ||
        command.toJson()['refreshId'] != ticket.refreshId) {
      throw StateError('Expired refresh ticket');
    }
    return command;
  }

  Future<ResourceView> ackTutor(
    ResourceRefreshTicket ticket, {
    required StudySession latestSession,
    required ResourceEventRefresh events,
  }) => LocalSerial.run(store, owner, () async {
    final data = await _load(ticket.target);
    final command = _ticket(data, ticket);
    if (ticket.target.kind != 'session' ||
        latestSession.id != ticket.target.id ||
        latestSession.questionId != command.source.questionId ||
        latestSession.questionVersion != command.source.questionVersion ||
        events.sessionId != ticket.target.id ||
        !events.complete ||
        events.nextAfterSeq < latestSession.lastEventSeq) {
      throw StateError('Incomplete tutor refresh');
    }
    for (final event in events.events) {
      _validateEvent(event, command.source, ticket.target.id);
    }
    final old = data['view'] == null
        ? null
        : ResourceView(data['view'] as Map).session;
    if (old != null && latestSession.lastEventSeq < old.lastEventSeq) {
      throw StateError('Session refresh is older than cache');
    }
    final receipt = command.result == null
        ? null
        : TutorStep.fromJson(command.result!).session;
    final session = latestSession.toJson();
    for (final key in ['assisted', 'used_solution', 'independent_ended']) {
      session[key] =
          session[key] == true ||
          old?.toJson()[key] == true ||
          receipt?.toJson()[key] == true;
    }
    var hints = latestSession.hintLevelRevealed;
    if (old != null && old.hintLevelRevealed > hints) {
      hints = old.hintLevelRevealed;
    }
    if (receipt != null && receipt.hintLevelRevealed > hints) {
      hints = receipt.hintLevelRevealed;
    }
    session['hint_level_revealed'] = hints;
    final collected = {for (final e in events.events) e.id: e};
    final collectedBySeq = {for (final e in events.events) e.seqNo: e};
    if (data['view'] != null) {
      for (final oldEvent in ResourceView(data['view'] as Map).events) {
        final sameId = collected[oldEvent.id];
        final sameSeq = collectedBySeq[oldEvent.seqNo];
        if (sameId == null ||
            sameSeq == null ||
            journalCanonical(sameId.toJson()) !=
                journalCanonical(oldEvent.toJson()) ||
            journalCanonical(sameSeq.toJson()) !=
                journalCanonical(oldEvent.toJson())) {
          throw StateError(
            'Refreshed event history changed an immutable event',
          );
        }
      }
    }
    for (final e
        in command.result == null
            ? <TutorEvent>[]
            : TutorStep.fromJson(command.result!).events) {
      final fetched = collected[e.id];
      if (fetched == null ||
          journalCanonical(fetched.toJson()) != journalCanonical(e.toJson())) {
        throw StateError('Receipt events missing from refreshed history');
      }
    }
    final view = {
      'session': session,
      'events': events.events.map((e) => e.toJson()).toList(),
    };
    data['view'] = view;
    _put(
      data,
      _next(command, {
        'phase': command.phase == 'result_known' ? 'acked' : 'rejected',
        'result': null,
        'resultSummary': {
          'resultHash': journalHash(command.result),
          'eventIds': command.result == null
              ? <String>[]
              : TutorStep.fromJson(command.result!).events
                    .map((event) => event.id)
                    .toList(),
          'rejection': command.toJson()['rejection'],
        },
      }),
    );
    await _save(ticket.target, data);
    return ResourceView(view);
  });
  Future<ResourceView> ackReview(
    ResourceRefreshTicket ticket, {
    required ReviewState latestState,
  }) => LocalSerial.run(store, owner, () async {
    final data = await _load(ticket.target);
    final command = _ticket(data, ticket);
    if (ticket.target.kind != 'review' ||
        latestState.id != ticket.target.id ||
        latestState.questionId != command.source.questionId) {
      throw StateError('Review refresh mismatch');
    }
    final view = {'review': latestState.toJson()};
    data['view'] = view;
    _put(
      data,
      _next(command, {
        'phase': command.phase == 'result_known' ? 'acked' : 'rejected',
        'result': null,
        'resultSummary': {
          'resultHash': journalHash(command.result),
          'completion': command.result,
          'rejection': command.toJson()['rejection'],
        },
      }),
    );
    await _save(ticket.target, data);
    return ResourceView(view);
  });
}
