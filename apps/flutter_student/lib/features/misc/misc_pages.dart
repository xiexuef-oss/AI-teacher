import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../solve/tutor_panel.dart';
import '../visual/visual_view.dart';

/// P02 拍题。识别、确认题干、匹配题库这条链路还没有实现（契约里已规划，服务端返回 501），
/// 这里如实告诉学生，不假装能用。
class ScanPage extends StatelessWidget {
  const ScanPage({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      key: const ValueKey('scan.page'),
      appBar: AppBar(title: const Text('拍题')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.all(kPad * 1.5),
              children: [
                Icon(
                  Icons.photo_camera_outlined,
                  size: 56,
                  color: theme.colorScheme.primary,
                ),
                const SizedBox(height: kGap),
                Text(
                  '拍题还在准备中',
                  style: theme.textTheme.headlineSmall,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: kGap),
                const Callout(
                  tone: Tone.info,
                  child: Text(
                    '以后你可以拍下一道不会的题：先识别，再由你确认题干对不对，确认之后才开始作答。'
                    '识别结果不会没经过你确认就当成原题。',
                  ),
                ),
                const SizedBox(height: kGap),
                Text(
                  '现在可以去“练习”里选题，或者回首页看今天的任务。',
                  style: theme.textTheme.bodyLarge,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: kPad),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    FilledButton(
                      key: const ValueKey('scan.practice'),
                      onPressed: () => context.go('/practice'),
                      child: const Text('去练习'),
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton(
                      onPressed: () => context.go('/home'),
                      child: const Text('回首页'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// P04 辅导会话回看：按顺序显示这个会话里发生过的所有教学事件（只读）。
class TutorHistoryPage extends ConsumerWidget {
  const TutorHistoryPage({super.key, required this.sessionId});

  final String sessionId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final events = ref.watch(sessionEventsProvider(sessionId));
    return Scaffold(
      key: const ValueKey('tutor.page'),
      appBar: AppBar(title: const Text('辅导记录')),
      body: SafeArea(
        child: events.when(
          loading: () => const LoadingView(),
          error: (error, _) => ErrorView(
            error: error,
            onRetry: () => ref.invalidate(sessionEventsProvider(sessionId)),
          ),
          data: (items) => items.isEmpty
              ? const EmptyView(
                  title: '这个会话里还没有辅导内容',
                  icon: Icons.forum_outlined,
                )
              : Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 760),
                    child: ListView(
                      padding: const EdgeInsets.all(kPad),
                      children: [
                        TutorTimeline(events: items, onSuggestion: (_) {}),
                      ],
                    ),
                  ),
                ),
        ),
      ),
    );
  }
}

/// P05 图解页：单独打开一个注册过的模板（用默认参数）。
class VisualPage extends StatelessWidget {
  const VisualPage({
    super.key,
    required this.templateId,
    this.params = const {},
  });

  final String templateId;
  final Map<String, double> params;

  @override
  Widget build(BuildContext context) {
    final spec = visualTemplates[templateId];
    return Scaffold(
      key: const ValueKey('visual.page'),
      appBar: AppBar(title: Text(spec?.title ?? '图解')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: ListView(
              padding: const EdgeInsets.all(kPad),
              children: [
                VisualView(
                  templateId: templateId,
                  params: params,
                  staticFallback: spec?.staticFallback,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
