import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import 'providers.dart';
import 'idempotency.dart';
import '../features/profile/profile_journal_store.dart';

/// 启动配置（地区、年级、学科、教材选项与估算的考试年份）。
final launchConfigProvider = FutureProvider<LaunchConfig>((ref) async {
  final store = ref.read(keyValueStoreProvider);
  try {
    final config = await ref.watch(apiClientProvider).getLaunchConfig();
    try {
      final existing = await store.read('launch_config');
      // Keep malformed bytes untouched for recovery instead of replacing them.
      if (existing != null) {
        LaunchConfig.fromJson(jsonDecode(existing) as Map<String, dynamic>);
      }
      await store.write('launch_config', jsonEncode(config.toJson()));
    } catch (_) {
      // A cache failure never discards a successfully read public configuration.
    }
    return config;
  } on ApiException catch (error) {
    if (!error.isNetwork) rethrow;
    final raw = await store.read('launch_config');
    if (raw != null) {
      try {
        return LaunchConfig.fromJson(jsonDecode(raw) as Map<String, dynamic>);
      } catch (_) {
        // Preserve unknown bytes; never invent regions or options.
      }
    }
    rethrow;
  }
});

/// Profile edits and commands are durable before any network write.
class ProfileController extends AsyncNotifier<StudentProfile> {
  int _epoch = 0;
  ProfileBundle? bundle;
  AuthSession? _owner;
  ProfileJournalStore? _journal;

  bool _active(AuthSession auth, int epoch) {
    if (!ref.mounted) return false;
    final now = ref.read(authProvider).asData?.value;
    return epoch == _epoch &&
        now?.userId == auth.userId &&
        now?.token == auth.token &&
        now?.role == LocalRole.student;
  }

  TutorApiClient _client(AuthSession auth) => TutorApiClient(
    ApiCore(
      baseUrl: ref.read(apiBaseUrlProvider),
      transport: ref.read(apiTransportProvider),
      tokenProvider: () => auth.token,
    ),
  );

  @override
  Future<StudentProfile> build() async {
    final epoch = ++_epoch;
    final auth = await ref.watch(studentSessionProvider.future);
    final journal = ProfileJournalStore(
      ref.read(keyValueStoreProvider),
      auth.userId,
    );
    if (!_active(auth, epoch)) throw StateError('资料身份已变化');
    _owner = auth;
    _journal = journal;
    final local = await journal.read();
    if (_active(auth, epoch)) bundle = local;
    try {
      final profile = await _client(auth).getProfile();
      await journal.rememberCloud(profile);
      final restored = await journal.read();
      if (_active(auth, epoch)) bundle = restored;
      return restored!.cloud!;
    } on ApiException catch (error) {
      if (error.isNetwork) {
        if (local?.cloud != null) return local!.cloud!;
        if (local?.legacyProfile != null) {
          return StudentProfile.fromJson(local!.legacyProfile!);
        }
      }
      rethrow;
    }
  }

  Future<void> edit(Map<String, dynamic> fields) async {
    final auth = _owner;
    final journal = _journal;
    final epoch = _epoch;
    if (auth == null || journal == null || !_active(auth, epoch)) {
      throw StateError('资料身份已变化，请重新打开页面');
    }
    final next = await journal.edit(ProfileEdit(fields));
    if (_active(auth, epoch)) bundle = next;
  }

  Future<StudentProfile> save(ProfileUpdate update) async {
    final auth = _owner;
    final journal = _journal;
    final epoch = _epoch;
    if (auth == null || journal == null || !_active(auth, epoch)) {
      throw StateError('资料身份已变化，请重新打开页面');
    }
    await edit(ProfileEdit(update.toJson()).toJson());
    if (!_active(auth, epoch)) throw StateError('资料身份已变化');
    final command = await journal.prepare(
      update,
      idempotencyKey: newIdempotencyKey('profile'),
      activeEpoch: epoch,
    );
    final prepared = await journal.read();
    if (_active(auth, epoch)) bundle = prepared;
    // The initiating token is fixed even if the active account changes here.
    if (!_active(auth, epoch)) throw StateError('资料身份已变化，原保存仍留在本机');
    return _send(auth, epoch, journal, command);
  }

  Future<StudentProfile> retryPending() async {
    final auth = _owner!;
    final epoch = _epoch;
    final journal = _journal!;
    if (!_active(auth, epoch)) throw StateError('资料身份已变化');
    final command = (await journal.read())?.pending;
    if (command == null || command.phase == 'conflict') {
      throw StateError('请先明确选择冲突资料');
    }
    if (!_active(auth, epoch)) throw StateError('资料身份已变化');
    return _send(auth, epoch, journal, command);
  }

  Future<StudentProfile> _send(
    AuthSession auth,
    int epoch,
    ProfileJournalStore journal,
    ProfileCommand command,
  ) async {
    StudentProfile saved;
    try {
      saved =
          command.result ??
          await _client(auth).updateProfile(
            body: command.body,
            idempotencyKey: command.idempotencyKey,
          );
    } on ApiException catch (error) {
      if (error.statusCode == 409 || error.statusCode == 422) {
        final server = error.details['server_profile'];
        final cloud = server is Map<String, dynamic>
            ? StudentProfile.fromJson(server)
            : null;
        await journal.reject(
          command.idempotencyKey,
          code: error.code,
          cloud: cloud,
        );
        final rejected = await journal.read();
        if (_active(auth, epoch)) {
          bundle = rejected;
          state = AsyncData(bundle!.cloud!);
        }
      }
      rethrow;
    }
    await journal.recordResult(command.idempotencyKey, saved);
    await journal.acknowledge(command.idempotencyKey);
    final next = await journal.read();
    if (_active(auth, epoch)) {
      bundle = next;
      state = AsyncData(next!.cloud!);
      ref.invalidate(todayTasksProvider);
    }
    return saved;
  }

  Future<void> resolveConflict({required bool useCloud}) async {
    final auth = _owner!;
    final epoch = _epoch;
    final journal = _journal!;
    if (!_active(auth, epoch)) throw StateError('资料身份已变化');
    final editGeneration = bundle!.editGeneration;
    final current = await journal.read();
    final pending = current?.pending;
    if (pending?.phase == 'conflict') {
      await journal.resolveConflict(
        pending!.idempotencyKey,
        useCloud: useCloud,
        editGeneration: editGeneration,
      );
    } else if (current?.editConflict == true) {
      await journal.resolveEditConflict(
        useCloud: useCloud,
        editGeneration: editGeneration,
      );
    } else {
      throw StateError('没有待选择的冲突');
    }
    final resolved = await journal.read();
    if (_active(auth, epoch)) {
      bundle = resolved;
      state = AsyncData(bundle!.cloud!);
    }
  }
}

final profileProvider =
    AsyncNotifierProvider<ProfileController, StudentProfile>(
      ProfileController.new,
    );

/// 今日任务；断网时显示上次缓存的那一份（并标明是缓存）。
class TasksResult {
  const TasksResult(this.tasks, {this.fromCache = false});

  final TodayTasks tasks;
  final bool fromCache;
}

final todayTasksProvider = FutureProvider.autoDispose<TasksResult>((ref) async {
  final auth = await ref.watch(studentSessionProvider.future);
  final store = ref.read(keyValueStoreProvider);
  final key = 'u/${auth.userId}/tasks';
  try {
    final tasks = await ref.watch(apiClientProvider).getTodayTasks();
    try {
      await store.write(key, jsonEncode(tasks.toJson()));
    } catch (_) {
      // 缓存写不进去不影响显示
    }
    return TasksResult(tasks);
  } on ApiException catch (error) {
    if (error.isNetwork) {
      final raw = await store.read(key);
      if (raw != null) {
        try {
          return TasksResult(
            TodayTasks.fromJson(jsonDecode(raw) as Map<String, dynamic>),
            fromCache: true,
          );
        } catch (_) {
          // 缓存损坏：按没有缓存处理
        }
      }
    }
    rethrow;
  }
});

/// 当天被跳过的任务（只在本机记录，按日期分开）。
class SkippedTasks {
  SkippedTasks(this._ref);

  final Ref _ref;

  String _key(String date) => 'u/${_ref.read(userIdProvider)}/skipped/$date';

  Future<Set<String>> read(String date) async {
    final raw = await _ref.read(keyValueStoreProvider).read(_key(date));
    if (raw == null) return {};
    try {
      return (jsonDecode(raw) as List<dynamic>).cast<String>().toSet();
    } catch (_) {
      return {};
    }
  }

  Future<void> skip(String date, String taskId) async {
    final current = await read(date);
    current.add(taskId);
    await _ref
        .read(keyValueStoreProvider)
        .write(_key(date), jsonEncode(current.toList()));
    _ref.invalidate(skippedTasksProvider(date));
  }
}

final skippedTasksStoreProvider = Provider<SkippedTasks>(SkippedTasks.new);

final skippedTasksProvider = FutureProvider.autoDispose
    .family<Set<String>, String>(
      (ref, date) => ref.read(skippedTasksStoreProvider).read(date),
    );

/// 复测队列（含未到期的）。
final reviewsProvider = FutureProvider.autoDispose<ReviewPage>((ref) async {
  await ref.watch(studentSessionProvider.future);
  return ref
      .watch(apiClientProvider)
      .listDueReviews(scope: ReviewScope.all, limit: 50);
});

final progressProvider = FutureProvider.autoDispose<ProgressSummary>((
  ref,
) async {
  await ref.watch(studentSessionProvider.future);
  return ref.watch(apiClientProvider).getProgressSummary();
});

/// 某个会话已有的教学事件（只读回看）。
final sessionEventsProvider = FutureProvider.autoDispose
    .family<List<TutorEvent>, String>((ref, sessionId) async {
      await ref.watch(studentSessionProvider.future);
      final page = await ref
          .watch(apiClientProvider)
          .listSessionEvents(sessionId: sessionId, afterSeq: 0, limit: 200);
      return page.items;
    });

// ---------------------------------------------------------------- 家长周报与授权（PRD P0 第 8 条）

/// 家长：现在能看的学生（学生撤销授权之后，这里就没有他了）。
final parentStudentsProvider = FutureProvider.autoDispose<ParentStudents>((
  ref,
) async {
  await ref.watch(parentSessionProvider.future);
  return ref.watch(apiClientProvider).listParentStudents();
});

/// 某位学生的某一周。[weekStart] 是那一周的周一（`2026-11-09`）；null 是当前这一周。
typedef WeeklyQuery = ({String studentId, String? weekStart});

final parentWeeklyProvider = FutureProvider.autoDispose
    .family<ParentWeekly, WeeklyQuery>((ref, query) async {
      await ref.watch(parentSessionProvider.future);
      return ref
          .watch(apiClientProvider)
          .getParentWeekly(
            studentId: query.studentId,
            weekStart: query.weekStart,
          );
    });

/// 家长：读取指定周已发布的快照，不使用离线缓存。
final parentWeeklySnapshotProvider = FutureProvider.autoDispose
    .family<
      ParentWeeklySnapshot,
      ({String studentId, String weekStart, int? revision})
    >((ref, query) async {
      await ref.watch(parentSessionProvider.future);
      return ref
          .watch(apiClientProvider)
          .getParentWeeklySnapshot(
            studentId: query.studentId,
            weekStart: query.weekStart,
            revision: query.revision,
          );
    });

/// 学生：自己授权过哪些家长，以及有没有还没被用掉的邀请码。
final parentLinksProvider = FutureProvider.autoDispose<ParentLinks>((
  ref,
) async {
  await ref.watch(studentSessionProvider.future);
  return ref.watch(apiClientProvider).listParentLinks();
});
