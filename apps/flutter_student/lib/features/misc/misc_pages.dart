import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../solve/tutor_panel.dart';
import '../visual/visual_view.dart';

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
