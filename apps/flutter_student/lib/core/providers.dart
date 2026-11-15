import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../config.dart';
import 'storage.dart';

/// 本地存储。启动时在 main() 里用真实实现覆盖；测试里用内存实现覆盖。
final keyValueStoreProvider = Provider<KeyValueStore>(
  (ref) => throw StateError('keyValueStoreProvider 必须在 ProviderScope 里被覆盖'),
);

/// 传输层。测试里换成假的后端。
final apiTransportProvider = Provider<ApiTransport>((ref) => HttpTransport());

final apiBaseUrlProvider = Provider<String>((ref) => apiBaseUrl);

/// 当前时间。测试里可以固定。
final clockProvider = Provider<DateTime Function()>((ref) => DateTime.now);

/// 当前的登录状态：本地身份 Mock 发的身份，学生或者家长。
class AuthSession {
  const AuthSession({
    required this.userId,
    required this.token,
    this.role = LocalRole.student,
  });

  final String userId;
  final String token;
  final LocalRole role;
}

/// 本机上存凭据的一个"槽"。当前身份在 `auth.*`；本机演示里切换到另一个身份时，暂时不用的那个
/// 收在 `auth.other.*`，切回去还是原来的（学生的草稿按用户 ID 分开存，不会混到另一个身份里）。
class _Slot {
  const _Slot(this._prefix);

  final String _prefix;

  Future<AuthSession?> read(KeyValueStore store) async {
    final token = await store.read('$_prefix.token');
    final user = await store.read('$_prefix.userId');
    if (token == null || user == null) return null;
    // 这个版本之前存下的身份没有记角色：都是学生
    final role = await store.read('$_prefix.role');
    return AuthSession(
      userId: user,
      token: token,
      role: role == null ? LocalRole.student : LocalRole.fromJson(role),
    );
  }

  Future<void> write(KeyValueStore store, AuthSession session) async {
    await store.write('$_prefix.token', session.token);
    await store.write('$_prefix.userId', session.userId);
    await store.write('$_prefix.role', session.role.value);
  }

  Future<void> clear(KeyValueStore store) async {
    await store.delete('$_prefix.token');
    await store.delete('$_prefix.userId');
    await store.delete('$_prefix.role');
  }
}

const _current = _Slot('auth');
const _other = _Slot('auth.other');

/// 本地身份 Mock（ADR-006 Q-03）：第一次启动时向后端领一个随机 bearer，保存在本机。
/// 真实登录方式冻结之前，这里是唯一的身份来源。
class AuthController extends AsyncNotifier<AuthSession> {
  @override
  Future<AuthSession> build() async {
    final stored = await _current.read(ref.read(keyValueStoreProvider));
    if (stored != null) return stored;
    final created = await _createIdentity(LocalRole.student);
    await _current.write(ref.read(keyValueStoreProvider), created);
    return created;
  }

  Future<AuthSession> _createIdentity(LocalRole role) async {
    final core = ApiCore(
      baseUrl: ref.read(apiBaseUrlProvider),
      transport: ref.read(apiTransportProvider),
    );
    // 学生是默认角色，不带参数，和以前的请求一样
    final identity = await TutorApiClient(core)
        .createLocalIdentity(role: role == LocalRole.student ? null : role);
    return AuthSession(
      userId: identity.userId,
      token: identity.accessToken,
      role: identity.role,
    );
  }

  /// 登录失效（401）后重新领取身份，角色不变。没有同步的草稿按用户 ID 分开保存在本机，
  /// 不会混进新身份里；旧身份的草稿留在原处。
  Future<void> relogin() async {
    final store = ref.read(keyValueStoreProvider);
    final role = state.asData?.value.role ?? LocalRole.student;
    await _current.clear(store);
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final created = await _createIdentity(role);
      await _current.write(store, created);
      return created;
    });
  }

  /// 本机演示：在学生和家长这两个身份之间切换。暂时不用的身份收起来，切回去还是原来的那个；
  /// 另一个角色还没有身份时才去领一个新的。新身份领不到（比如断网）就什么都不改，把错误抛给调用方。
  ///
  /// 状态换掉的那一刻，套着 `RequireAuth` 的页面会马上换成"这个页面不是当前身份用的"，
  /// 所以不会有半个学生页面拿着家长的凭据去请求数据。
  Future<void> switchTo(LocalRole role) async {
    final current = state.asData?.value;
    if (current == null || current.role == role) return;
    final store = ref.read(keyValueStoreProvider);
    final stashed = await _other.read(store);
    final target = stashed != null && stashed.role == role
        ? stashed
        : await _createIdentity(role);
    await _other.write(store, current);
    await _current.write(store, target);
    state = AsyncData(target);
  }
}

final authProvider = AsyncNotifierProvider<AuthController, AuthSession>(
  AuthController.new,
);

/// 当前身份不是这个数据要的身份：学生的数据不拿家长的凭据去请求，反过来也一样。
class WrongSession implements Exception {
  const WrongSession(this.needed);

  final LocalRole needed;

  @override
  String toString() => 'WrongSession(需要${needed.value}身份)';
}

/// 学生身份的登录状态；当前是别的身份（本机演示切到了家长）就抛 [WrongSession]。
/// 学生的数据都从这里取，切身份的那一刻依赖它的数据会立刻重算——重算时直接失败，
/// 不会拿着家长的凭据去请求学生的接口。
final studentSessionProvider = FutureProvider<AuthSession>((ref) async {
  final auth = await ref.watch(authProvider.future);
  if (auth.role != LocalRole.student) {
    throw const WrongSession(LocalRole.student);
  }
  return auth;
});

/// 家长身份的登录状态，道理同上。
final parentSessionProvider = FutureProvider<AuthSession>((ref) async {
  final auth = await ref.watch(authProvider.future);
  if (auth.role != LocalRole.parent) throw const WrongSession(LocalRole.parent);
  return auth;
});

/// 带当前身份 bearer 的 API 客户端。
final apiClientProvider = Provider<TutorApiClient>((ref) {
  final core = ApiCore(
    baseUrl: ref.watch(apiBaseUrlProvider),
    transport: ref.watch(apiTransportProvider),
    tokenProvider: () => ref.read(authProvider).asData?.value.token,
  );
  return TutorApiClient(core);
});

/// 当前用户的 ID（登录完成后才有）。
final userIdProvider = Provider<String?>(
  (ref) => ref.watch(authProvider).asData?.value.userId,
);
