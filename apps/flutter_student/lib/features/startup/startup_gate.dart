import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/providers.dart';
import '../../core/widgets.dart';

/// 启动时的入口：先拿到登录状态；学生再拿资料，决定去引导还是首页；家长直接去家长页。
class StartupGate extends ConsumerStatefulWidget {
  const StartupGate({super.key});

  @override
  ConsumerState<StartupGate> createState() => _StartupGateState();
}

class _StartupGateState extends ConsumerState<StartupGate> {
  bool _navigated = false;

  void _goTo(String target) {
    if (_navigated) return;
    _navigated = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) context.go(target);
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    if (auth.hasError) {
      return Scaffold(
        body: ErrorView(
          error: auth.error!,
          onRetry: () => ref.invalidate(authProvider),
        ),
      );
    }
    if (!auth.hasValue) {
      return const Scaffold(body: LoadingView(label: '正在启动…'));
    }

    // 家长没有学生资料，也不走引导：不去请求 /profile
    if (auth.requireValue.role == LocalRole.parent) {
      _goTo('/parent');
      return const Scaffold(body: LoadingView(label: '正在启动…'));
    }

    final profile = ref.watch(profileProvider);
    if (profile.hasError) {
      return Scaffold(
        body: ErrorView(
          error: profile.error!,
          onRetry: () => ref.invalidate(profileProvider),
        ),
      );
    }
    final data = profile.asData?.value;
    if (data == null) return const Scaffold(body: LoadingView(label: '正在启动…'));

    _goTo(data.onboardingCompleted ? '/home' : '/onboarding');
    return const Scaffold(body: LoadingView(label: '正在启动…'));
  }
}

/// 需要登录状态的页面外面套这一层：没登录完就先等，失败就给重试；
/// 身份和页面对不上（家长打开了学生页，或者反过来）就说明一句、给一个去处，不拿着这个身份去请求数据。
class RequireAuth extends ConsumerWidget {
  const RequireAuth({
    super.key,
    required this.child,
    this.role = LocalRole.student,
  });

  final Widget child;

  /// 这个页面是给哪种身份用的。
  final LocalRole role;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    if (auth.hasError) {
      return Scaffold(
        body: ErrorView(
          error: auth.error!,
          onRetry: () => ref.invalidate(authProvider),
        ),
      );
    }
    if (!auth.hasValue) {
      return const Scaffold(body: LoadingView(label: '正在启动…'));
    }
    final current = auth.requireValue.role;
    if (current != role) {
      final parentPage = role == LocalRole.parent;
      return Scaffold(
        key: const ValueKey('auth.wrongRole'),
        appBar: AppBar(),
        body: EmptyView(
          title: parentPage ? '这是家长看的页面' : '这是学生用的页面',
          message: parentPage
              ? '现在是学生身份（本机演示）。要看周报，请在「我的」里切换到家长身份。'
              : '现在是家长身份（本机演示），家长只能看汇总的周报。',
          icon: Icons.swap_horiz,
          action: FilledButton(
            key: const ValueKey('auth.wrongRole.go'),
            onPressed: () => context.go(parentPage ? '/' : '/parent'),
            child: Text(parentPage ? '回到学生首页' : '去家长页'),
          ),
        ),
      );
    }
    return child;
  }
}
