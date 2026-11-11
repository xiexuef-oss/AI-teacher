import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/format.dart';
import '../../core/labels.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

/// P07 错题与间隔复测。到期的题可以开始复测；复测要求不看提示独立完成。
class ReviewPage extends ConsumerWidget {
  const ReviewPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final reviews = ref.watch(reviewsProvider);
    final now = ref.watch(clockProvider)();
    return Scaffold(
      key: const ValueKey('review.page'),
      appBar: AppBar(title: const Text('错题复习')),
      body: SafeArea(
        child: reviews.when(
          loading: () => const LoadingView(),
          error: (error, _) => ErrorView(
            error: error,
            onRetry: () => ref.invalidate(reviewsProvider),
          ),
          data: (page) {
            if (page.items.isEmpty) {
              return EmptyView(
                title: '现在没有需要复习的题',
                message: '做错的题，或者要靠提示才做对的题，会按 1 天、3 天、7 天的间隔回来复测。',
                icon: Icons.event_available_outlined,
                action: FilledButton(
                  onPressed: () => context.go('/practice'),
                  child: const Text('去练习'),
                ),
              );
            }
            final due = page.items.where((i) => i.isDue).toList();
            final upcoming = page.items.where((i) => !i.isDue).toList();
            return Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 900),
                child: ListView(
                  padding: const EdgeInsets.all(kPad),
                  children: [
                    Text(
                      '现在可以复测（${due.length}）',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    if (due.isEmpty)
                      const Callout(
                        tone: Tone.neutral,
                        child: Text('还没有到期的题。到时间会出现在这里，也会出现在首页的今日任务里。'),
                      )
                    else
                      for (final item in due)
                        _ReviewTile(item: item, now: now, due: true),
                    if (upcoming.isNotEmpty) ...[
                      const SizedBox(height: 20),
                      Text(
                        '之后安排（${upcoming.length}）',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 8),
                      for (final item in upcoming)
                        _ReviewTile(item: item, now: now, due: false),
                    ],
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _ReviewTile extends StatelessWidget {
  const _ReviewTile({required this.item, required this.now, required this.due});

  final ReviewItem item;
  final DateTime now;
  final bool due;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: kGap),
      child: Section(
        key: ValueKey('review.${item.id}'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                InfoChip(subjectName(item.subject)),
                InfoChip(
                  item.stage == 0 ? '复习旧错题' : '第 ${item.stage + 1} 次间隔复测',
                  icon: Icons.event_repeat,
                  tone: Tone.info,
                ),
                InfoChip('${item.stage}/${item.totalStages} 档已通过'),
                if (item.lastResult == ReviewResult.failed)
                  const InfoChip(
                    '上次没通过',
                    icon: Icons.replay,
                    tone: Tone.warning,
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(item.questionTitle, style: theme.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(
              due ? '已到时间' : '复测时间：${formatWhen(item.dueAt, now)}',
              style: theme.textTheme.bodyMedium,
            ),
            if (due) ...[
              const SizedBox(height: 12),
              FilledButton.icon(
                key: ValueKey('review.start.${item.id}'),
                onPressed: () => context.push(
                  solveRoute(
                    item.questionId,
                    origin: 'review',
                    reviewItemId: item.id,
                  ),
                ),
                icon: const Icon(Icons.play_arrow),
                label: const Text('开始复测（不看提示）'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
