import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/idempotency.dart';
import '../../core/providers.dart';
import 'diagnostic_store.dart';

class DiagnosticView {
  const DiagnosticView(
    this.bundle, {
    this.fresh = false,
    this.busy = false,
    this.problem,
  });
  final DiagnosticBundle bundle;
  final bool fresh, busy;
  final Object? problem;
}

final diagnosticActionsProvider =
    AsyncNotifierProvider<DiagnosticActions, DiagnosticView>(
      DiagnosticActions.new,
    );

class DiagnosticActions extends AsyncNotifier<DiagnosticView> {
  int _epoch = 0, _readGeneration = 0;
  bool _busy = false;
  AuthSession? _auth;
  DiagnosticStore? _journal;

  bool _active(AuthSession auth, int epoch) {
    if (!ref.mounted || epoch != _epoch) return false;
    final current = ref.read(authProvider).asData?.value;
    return current?.userId == auth.userId &&
        current?.token == auth.token &&
        current?.role == LocalRole.student;
  }

  TutorApiClient _api(AuthSession auth) => TutorApiClient(
    ApiCore(
      baseUrl: ref.read(apiBaseUrlProvider),
      transport: ref.read(apiTransportProvider),
      tokenProvider: () => auth.token,
    ),
  );

  @override
  Future<DiagnosticView> build() async {
    final epoch = ++_epoch;
    _busy = false;
    final auth = await ref.watch(studentSessionProvider.future);
    final journal = DiagnosticStore(
      ref.read(keyValueStoreProvider),
      auth.userId,
    );
    if (!_active(auth, epoch)) throw StateError('摸底身份已变化');
    _auth = auth;
    _journal = journal;
    final local = await journal.read();
    try {
      final cloud = await _api(auth).getDiagnosticWorkspace();
      if (!_active(auth, epoch)) throw StateError('摸底身份已变化');
      await journal.rememberCloud(cloud);
      return DiagnosticView(await journal.read(), fresh: true);
    } on ApiException catch (error) {
      return DiagnosticView(local, problem: error);
    }
  }

  Future<void> refresh() async {
    final auth = _auth, journal = _journal;
    if (auth == null || journal == null) return;
    final epoch = _epoch, generation = ++_readGeneration;
    try {
      final cloud = await _api(auth).getDiagnosticWorkspace();
      if (!_active(auth, epoch) || generation != _readGeneration) return;
      await journal.rememberCloud(cloud);
      final local = await journal.read();
      if (_active(auth, epoch) && generation == _readGeneration) {
        state = AsyncData(DiagnosticView(local, fresh: true, busy: _busy));
      }
    } catch (error) {
      final local = await journal.read();
      if (_active(auth, epoch) && generation == _readGeneration) {
        state = AsyncData(DiagnosticView(local, busy: _busy, problem: error));
      }
    }
  }

  Future<StudySession?> create(Subject subject) =>
      _run((api, journal, revision) async {
        final profile = await api.getProfile();
        if (profile.revision == null) throw StateError('学习资料版本未知，请刷新资料');
        return journal.prepareCreate(
          DiagnosticCreate(
            subject: subject,
            expectedRevision: revision,
            expectedProfileRevision: profile.revision!,
          ),
          newIdempotencyKey('diagnostic-create'),
        );
      });

  Future<StudySession?> open(String runId, int position) => _run(
    (api, journal, revision) => journal.prepareOpen(
      runId,
      position,
      DiagnosticRevision(expectedRevision: revision),
      newIdempotencyKey('diagnostic-open'),
    ),
  );

  Future<StudySession?> abandon(String runId) => _run(
    (api, journal, revision) => journal.prepareAbandon(
      runId,
      DiagnosticRevision(expectedRevision: revision),
      newIdempotencyKey('diagnostic-abandon'),
    ),
  );

  Future<StudySession?> resume() => _run((api, journal, revision) async {
    final command = (await journal.read()).pending;
    if (command == null) throw StateError('没有待恢复的摸底操作');
    return command;
  }, recovering: true);

  Future<void> stopRetrying() async {
    final journal = _journal;
    final auth = _auth;
    final epoch = _epoch;
    if (_busy || journal == null || auth == null || !_active(auth, epoch)) {
      return;
    }
    final pending = (await journal.read()).pending;
    if (pending == null) return;
    await journal.stop(pending.key);
    if (_active(auth, epoch)) await refresh();
  }

  Future<StudySession?> _run(
    Future<DiagnosticCommand> Function(TutorApiClient, DiagnosticStore, int)
    prepare, {
    bool recovering = false,
  }) async {
    final auth = _auth, journal = _journal;
    final epoch = _epoch;
    if (_busy || auth == null || journal == null || !_active(auth, epoch)) {
      return null;
    }
    final current = state.asData?.value;
    if (current == null || (!recovering && !current.fresh)) return null;
    _busy = true;
    ++_readGeneration;
    state = AsyncData(
      DiagnosticView(current.bundle, fresh: current.fresh, busy: true),
    );
    DiagnosticCommand? command;
    try {
      final api = _api(auth);
      command = await prepare(
        api,
        journal,
        current.bundle.cloud?.revision ?? 0,
      );
      // A profile GET or local write may have overlapped an identity replacement.
      // Keep the prepared command in its owner's store, but never dispatch it now.
      if (!_active(auth, epoch)) return null;
      final saved = (await journal.read()).pending;
      if (saved?.key != command.key) throw StateError('摸底操作来源已变化');
      command = saved!;
      if (!_active(auth, epoch)) return null;
      if (command.phase == 'prepared') {
        Map<String, dynamic> result;
        switch (command.action) {
          case DiagnosticAction.create:
            result = (await api.createDiagnostic(
              body: DiagnosticCreate.fromJson(command.body),
              idempotencyKey: command.key,
            )).toJson();
          case DiagnosticAction.open:
            result = (await api.openDiagnosticSession(
              diagnosticId: command.runId!,
              position: '${command.position}',
              body: DiagnosticRevision.fromJson(command.body),
              idempotencyKey: command.key,
            )).toJson();
          case DiagnosticAction.abandon:
            result = (await api.abandonDiagnostic(
              diagnosticId: command.runId!,
              body: DiagnosticRevision.fromJson(command.body),
              idempotencyKey: command.key,
            )).toJson();
        }
        // A late response still belongs in the original owner's history.
        await journal.recordResult(command.key, result);
      }
      if (!_active(auth, epoch)) return null;
      final cloud = await api.getDiagnosticWorkspace();
      if (!_active(auth, epoch)) return null;
      await journal.rememberCloud(cloud);
      final known = (await journal.read()).pending;
      if (known?.key != command.key || known?.phase != 'result_known') {
        return null;
      }
      await journal.acknowledge(command.key);
      final local = await journal.read();
      if (!_active(auth, epoch)) return null;
      state = AsyncData(DiagnosticView(local, fresh: true));
      if (command.action == DiagnosticAction.open &&
          cloud.run?.id == command.runId) {
        final session = StudySession.fromJson(known!.result!);
        final item = cloud.run!.items.singleWhere(
          (item) => item.position == command!.position,
        );
        if (item.sessionId == session.id &&
            item.question.id == session.questionId &&
            item.questionVersion == session.questionVersion) {
          return session;
        }
      }
      return null;
    } catch (error) {
      if (command != null &&
          error is ApiException &&
          (error.statusCode == 422 ||
              (error.statusCode == 409 &&
                  (error.code.startsWith('diagnostic_') ||
                      error.code == 'question_version_conflict')))) {
        final pending = (await journal.read()).pending;
        if (pending?.key == command.key && pending?.phase == 'prepared') {
          await journal.reject(command.key, error.code);
        }
      }
      final local = await journal.read();
      if (_active(auth, epoch)) {
        state = AsyncData(DiagnosticView(local, problem: error));
      }
      return null;
    } finally {
      if (_active(auth, epoch)) {
        _busy = false;
        final view = state.asData?.value;
        if (view != null && view.busy) {
          state = AsyncData(
            DiagnosticView(
              view.bundle,
              fresh: view.fresh,
              problem: view.problem,
            ),
          );
        }
      }
    }
  }
}
