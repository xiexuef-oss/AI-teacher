import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart' show LocalRole;

import 'core/widgets.dart';
import 'features/diagnostic/diagnostic_page.dart';
import 'features/diagnostic/diagnostic_history_page.dart';
import 'features/home/home_page.dart';
import 'features/misc/misc_pages.dart';
import 'features/scan/scan_page.dart';
import 'features/onboarding/onboarding_page.dart';
import 'features/parent/parent_home_page.dart';
import 'features/parent/parent_weekly_page.dart';
import 'features/practice/practice_page.dart';
import 'features/profile/profile_page.dart';
import 'features/progress/progress_page.dart';
import 'features/review/review_page.dart';
import 'features/solve/solve_controller.dart';
import 'features/solve/solve_page.dart';
import 'features/solve/cloud_drafts_page.dart';
import 'features/startup/startup_gate.dart';

/// 页面清单（docs/03 §2）。除了入口 `/`，所有页面都要等登录状态就绪；
/// 学生的页面只给学生身份用，家长的页面（`/parent` 开头）只给家长身份用。
final routerProvider = Provider<GoRouter>((ref) {
  Widget guarded(Widget child) => RequireAuth(child: child);
  Widget guardedParent(Widget child) =>
      RequireAuth(role: LocalRole.parent, child: child);

  return GoRouter(
    initialLocation: '/',
    errorBuilder: (context, state) => Scaffold(
      appBar: AppBar(title: const Text('找不到这个页面')),
      body: EmptyView(
        title: '这个页面不存在',
        message: state.uri.toString(),
        icon: Icons.explore_off_outlined,
        action: FilledButton(
          onPressed: () => context.go('/'),
          child: const Text('回到首页'),
        ),
      ),
    ),
    routes: [
      GoRoute(path: '/', builder: (context, state) => const StartupGate()),
      GoRoute(
        path: '/onboarding',
        builder: (context, state) => guarded(const OnboardingPage()),
      ),
      GoRoute(
        path: '/home',
        builder: (context, state) => guarded(const HomePage()),
      ),
      GoRoute(
        path: '/scan',
        builder: (context, state) => guarded(const ScanPage()),
      ),
      GoRoute(
        path: '/practice',
        builder: (context, state) => guarded(const PracticePage()),
      ),
      GoRoute(
        path: '/diagnostic',
        builder: (context, state) => guarded(const DiagnosticPage()),
      ),
      GoRoute(
        path: '/diagnostic/history',
        builder: (context, state) => guarded(
          DiagnosticHistoryScreen(cursor: state.uri.queryParameters['cursor']),
        ),
      ),
      GoRoute(
        path: '/review',
        builder: (context, state) => guarded(const ReviewPage()),
      ),
      GoRoute(
        path: '/progress',
        builder: (context, state) => guarded(const ProgressPage()),
      ),
      GoRoute(
        path: '/profile',
        builder: (context, state) => guarded(const ProfilePage()),
      ),
      GoRoute(
        path: '/questions/:id/drafts',
        builder: (context, state) =>
            guarded(CloudDraftsPage(questionId: state.pathParameters['id']!)),
      ),
      GoRoute(
        path: '/questions/:id/solve',
        builder: (context, state) {
          final query = state.uri.queryParameters;
          final args = SolveArgs(
            questionId: state.pathParameters['id']!,
            origin:
                const {
                  'task',
                  'practice',
                  'review',
                  'variant',
                }.contains(query['origin'])
                ? query['origin']!
                : 'practice',
            reviewItemId: query['review'],
            parentSessionId: query['parent'],
            sessionId: query['session'],
            attemptId: query['attempt'],
          );
          // key 带上参数：同一个页面位置换了题，要整个重建（草稿控制器是按题建的）
          return guarded(
            SolvePage(
              key: ValueKey(
                'solve.${args.questionId}.${args.origin}.${args.reviewItemId}.${args.sessionId}.${args.attemptId}',
              ),
              args: args,
            ),
          );
        },
      ),
      GoRoute(
        path: '/tutor/:sessionId',
        builder: (context, state) => guarded(
          TutorHistoryPage(sessionId: state.pathParameters['sessionId']!),
        ),
      ),
      GoRoute(
        path: '/visual/:templateId',
        builder: (context, state) => guarded(
          VisualPage(templateId: state.pathParameters['templateId']!),
        ),
      ),
      GoRoute(
        path: '/parent',
        builder: (context, state) => guardedParent(const ParentHomePage()),
      ),
      GoRoute(
        path: '/parent/weekly/:studentId',
        builder: (context, state) => guardedParent(
          ParentWeeklyPage(
            // key 带上学生：换了学生要整个重建（翻到哪一周是页面自己的状态）
            key: ValueKey('parent.weekly.${state.pathParameters['studentId']}'),
            studentId: state.pathParameters['studentId']!,
          ),
        ),
      ),
    ],
  );
});
