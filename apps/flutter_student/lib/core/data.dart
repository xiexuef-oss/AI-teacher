import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import 'providers.dart';

/// 启动配置（地区、年级、学科、教材选项与估算的考试年份）。
final launchConfigProvider = FutureProvider<LaunchConfig>(
  (ref) => ref.watch(apiClientProvider).getLaunchConfig(),
);

/// 学生资料。保存后用返回值直接更新，不再多请求一次；断网时用上次缓存的那一份，
/// 这样没网也能进首页看缓存的内容（docs/01 US-01）。
class ProfileController extends AsyncNotifier<StudentProfile> {
  String _cacheKey(String userId) => 'u/$userId/profile';

  Future<void> _remember(String userId, StudentProfile profile) async {
    try {
      await ref
          .read(keyValueStoreProvider)
          .write(_cacheKey(userId), jsonEncode(profile.toJson()));
    } catch (_) {
      // 缓存写不进去不影响使用
    }
  }

  @override
  Future<StudentProfile> build() async {
    // 学生资料是学生身份的：本机演示切到家长身份之后不拿家长的凭据去请求，切回来时按学生的凭据重新加载
    final auth = await ref.watch(studentSessionProvider.future);
    try {
      final profile = await ref.read(apiClientProvider).getProfile();
      await _remember(auth.userId, profile);
      return profile;
    } on ApiException catch (error) {
      if (error.isNetwork) {
        final raw = await ref
            .read(keyValueStoreProvider)
            .read(_cacheKey(auth.userId));
        if (raw != null) {
          try {
            return StudentProfile.fromJson(
              jsonDecode(raw) as Map<String, dynamic>,
            );
          } catch (_) {
            // 缓存损坏：按没有缓存处理
          }
        }
      }
      rethrow;
    }
  }

  Future<StudentProfile> save(ProfileUpdate update) async {
    final saved = await ref.read(apiClientProvider).updateProfile(body: update);
    state = AsyncData(saved);
    final userId = ref.read(userIdProvider);
    if (userId != null) await _remember(userId, saved);
    // 地区、年级、学科变了，今日任务都要重算
    ref.invalidate(todayTasksProvider);
    return saved;
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

/// 学生：自己授权过哪些家长，以及有没有还没被用掉的邀请码。
final parentLinksProvider = FutureProvider.autoDispose<ParentLinks>((
  ref,
) async {
  await ref.watch(studentSessionProvider.future);
  return ref.watch(apiClientProvider).listParentLinks();
});
