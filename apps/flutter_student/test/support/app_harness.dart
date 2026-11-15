import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_student/features/home/home_page.dart';
import 'package:tutor_student/app.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/core/theme.dart';
import 'package:tutor_student/features/solve/solve_controller.dart';
import 'package:tutor_student/features/solve/solve_page.dart';

import 'fake_backend.dart';

/// 平板横屏 / 竖屏 / 手机的逻辑尺寸。
const tabletLandscape = Size(1280, 800);
const tabletPortrait = Size(800, 1100);
const mediumLandscape = Size(820, 600);
const phone = Size(390, 844);

/// 测试里统一的"现在"：2026-11-10 08:00（UTC），与导出样例时的时钟一致。
final DateTime testNow = DateTime.utc(2026, 11, 10, 8);

class AppHarness {
  AppHarness({FakeBackend? backend, MemoryStore? store})
    : backend = backend ?? FakeBackend(),
      store = store ?? MemoryStore() {
    if (backend == null) {
      this.backend
        ..installAppBasics()
        ..installParentFlow()
        ..installLearningFlow();
    }
  }

  final FakeBackend backend;
  final MemoryStore store;

  /// 让应用启动时已经是某个身份：本机存着它的凭据，不会再去领新的。
  void signInAs({
    required String role,
    String userId = FakeBackend.parentUserId,
    String token = 'parent-token-for-tests-0000000000000000',
  }) {
    store.data['auth.token'] = token;
    store.data['auth.userId'] = userId;
    store.data['auth.role'] = role;
  }

  List<Override> get overrides => [
    keyValueStoreProvider.overrideWithValue(store),
    apiTransportProvider.overrideWithValue(backend),
    clockProvider.overrideWithValue(() => testNow),
  ];

  /// 整个应用（含路由、启动判断）。
  Widget app({ThemeMode themeMode = ThemeMode.light}) => ProviderScope(
    retry: (count, error) => null,
    overrides: overrides,
    child: const TutorApp(),
  );

  /// 单独放一个页面（不带路由），用来测字体放大和各种屏幕尺寸。页面里的跳转在这里不工作。
  Widget page(Widget child, {double textScale = 1, ThemeData? theme}) =>
      ProviderScope(
        retry: (count, error) => null,
        overrides: overrides,
        child: MaterialApp(
          theme: theme ?? AppTheme.light(),
          builder: (context, app) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: TextScaler.linear(textScale)),
            child: app!,
          ),
          home: child,
        ),
      );

  /// 只放作答页，省掉路由。
  Widget solvePage({
    String questionId = '',
    String origin = 'practice',
    String? reviewItemId,
    ThemeData? theme,
    double textScale = 1,
  }) {
    final id = questionId.isEmpty
        ? Fixtures.load().value('question_single_choice')['id'] as String
        : questionId;
    return ProviderScope(
      retry: (count, error) => null,
      overrides: [...overrides, userIdProvider.overrideWithValue('user-1')],
      child: MaterialApp(
        theme: theme ?? AppTheme.light(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
        home: SolvePage(
          args: SolveArgs(
            questionId: id,
            origin: origin,
            reviewItemId: reviewItemId,
          ),
        ),
      ),
    );
  }
}

/// 设置窗口的逻辑尺寸（devicePixelRatio 固定为 1）。
void useSize(WidgetTester tester, Size size) {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

/// 让排队的异步工作（假后端、本机存储、动画的前几帧）跑完。
/// 不用 pumpAndSettle：加载圈这类无限动画永远"不安定"。
Future<void> settle(WidgetTester tester, {int frames = 8}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

/// 拆掉整棵树，让页面的 dispose 取消所有定时器。
Future<void> teardownTree(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(milliseconds: 50));
}

/// 取当前应用的 GoRouter，用来在测试里直接跳转。
class GoRouterOf {
  static GoRouter of(WidgetTester tester) =>
      GoRouter.of(tester.element(find.byType(Scaffold).first));
}

/// 首页单独放进来（不带路由），用来测字体放大、深色主题。
class HomePageForTest extends StatelessWidget {
  const HomePageForTest({super.key});

  @override
  Widget build(BuildContext context) => const MaterialApp(home: HomePage());
}
