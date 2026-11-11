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

/// 学生的登录状态。
class AuthSession {
  const AuthSession({required this.userId, required this.token});

  final String userId;
  final String token;
}

const _tokenKey = 'auth.token';
const _userKey = 'auth.userId';

/// 本地身份 Mock（ADR-006 Q-03）：第一次启动时向后端领一个随机 bearer，保存在本机。
/// 真实登录方式冻结之前，这里是唯一的身份来源。
class AuthController extends AsyncNotifier<AuthSession> {
  @override
  Future<AuthSession> build() async {
    final store = ref.read(keyValueStoreProvider);
    final token = await store.read(_tokenKey);
    final user = await store.read(_userKey);
    if (token != null && user != null) {
      return AuthSession(userId: user, token: token);
    }
    return _createIdentity();
  }

  Future<AuthSession> _createIdentity() async {
    final core = ApiCore(
      baseUrl: ref.read(apiBaseUrlProvider),
      transport: ref.read(apiTransportProvider),
    );
    final identity = await TutorApiClient(core).createLocalIdentity();
    final store = ref.read(keyValueStoreProvider);
    await store.write(_tokenKey, identity.accessToken);
    await store.write(_userKey, identity.userId);
    return AuthSession(userId: identity.userId, token: identity.accessToken);
  }

  /// 登录失效（401）后重新领取身份。没有同步的草稿按用户 ID 分开保存在本机，
  /// 不会混进新身份里；旧身份的草稿留在原处。
  Future<void> relogin() async {
    final store = ref.read(keyValueStoreProvider);
    await store.delete(_tokenKey);
    await store.delete(_userKey);
    state = const AsyncLoading();
    state = await AsyncValue.guard(_createIdentity);
  }
}

final authProvider = AsyncNotifierProvider<AuthController, AuthSession>(
  AuthController.new,
);

/// 带学生 bearer 的 API 客户端。
final apiClientProvider = Provider<TutorApiClient>((ref) {
  final core = ApiCore(
    baseUrl: ref.watch(apiBaseUrlProvider),
    transport: ref.watch(apiTransportProvider),
    tokenProvider: () => ref.read(authProvider).asData?.value.token,
  );
  return TutorApiClient(core);
});

/// 当前学生的 ID（登录完成后才有）。
final userIdProvider = Provider<String?>(
  (ref) => ref.watch(authProvider).asData?.value.userId,
);
