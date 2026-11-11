import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/data.dart';
import '../../core/providers.dart';
import '../../core/widgets.dart';

/// 启动时的入口：先拿到登录状态和资料，再决定去引导还是首页。
class StartupGate extends ConsumerStatefulWidget {
  const StartupGate({super.key});

  @override
  ConsumerState<StartupGate> createState() => _StartupGateState();
}

class _StartupGateState extends ConsumerState<StartupGate> {
  bool _navigated = false;

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

    if (!_navigated) {
      _navigated = true;
      final target = data.onboardingCompleted ? '/home' : '/onboarding';
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) context.go(target);
      });
    }
    return const Scaffold(body: LoadingView(label: '正在启动…'));
  }
}

/// 需要登录状态的页面外面套这一层：没登录完就先等，失败就给重试。
class RequireAuth extends ConsumerWidget {
  const RequireAuth({super.key, required this.child});

  final Widget child;

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
    return child;
  }
}
