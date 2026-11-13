import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/rate_widgets.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

/// P08 学情：独立与辅助正确率分开显示；样本不足时只给计数，不显示伪精确的百分比。
class ProgressPage extends ConsumerWidget {
  const ProgressPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final progress = ref.watch(progressProvider);
    return Scaffold(
      key: const ValueKey('progress.page'),
      appBar: AppBar(title: const Text('学情')),
      body: SafeArea(
        child: progress.when(
          loading: () => const LoadingView(),
          error: (error, _) => ErrorView(
            error: error,
            onRetry: () => ref.invalidate(progressProvider),
          ),
          data: (p) => Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 960),
              child: ListView(
                padding: const EdgeInsets.all(kPad),
                children: [
                  Wrap(
                    spacing: kGap,
                    runSpacing: kGap,
                    children: [
                      RateCard(
                        keyName: 'independent',
                        title: '独立正确率',
                        stat: p.independent,
                        minSamples: p.minSamples,
                        help: '不看提示、不看解析，一次做对的比例。这是最能说明真实水平的数字。',
                        emphasized: true,
                      ),
                      RateCard(
                        keyName: 'assisted',
                        title: '辅助正确率',
                        stat: p.assisted,
                        minSamples: p.minSamples,
                        help: '看过提示或解析之后做对的比例，单独计算，不和独立正确率混在一起。',
                      ),
                      RateCard(
                        keyName: 'hint',
                        title: '提示依赖率',
                        stat: p.hintDependency,
                        minSamples: p.minSamples,
                        help: '第一次作答前用了提示或解析的比例，越低越好。',
                      ),
                      RateCard(
                        keyName: 'retest',
                        title: '复测成功率',
                        stat: p.retestSuccess,
                        minSamples: p.minSamples,
                        help: '隔了一段时间、不看提示的复测里做对的比例。',
                      ),
                      RateCard(
                        keyName: 'variant',
                        title: '变式迁移率',
                        stat: p.variantTransfer,
                        minSamples: p.minSamples,
                        help: '换了问法的变式题，不看提示一次做对的比例。',
                      ),
                    ],
                  ),
                  if (p.uncertainAttempts > 0) ...[
                    const SizedBox(height: kGap),
                    Callout(
                      key: const ValueKey('progress.uncertain'),
                      tone: Tone.warning,
                      icon: Icons.help_outline,
                      child: Text(
                        '有 ${p.uncertainAttempts} 次作答没能自动判定（待确认），没有计入任何正确率。',
                      ),
                    ),
                  ],
                  if (p.subjective.attempts > 0) ...[
                    const SizedBox(height: kGap),
                    _SubjectiveCard(stats: p.subjective),
                  ],
                  const SizedBox(height: 20),
                  RateBuckets(
                    title: '按科目',
                    buckets: p.bySubject,
                    minSamples: p.minSamples,
                  ),
                  const SizedBox(height: kGap),
                  RateBuckets(
                    title: '按题型',
                    buckets: p.byAnswerMode,
                    minSamples: p.minSamples,
                  ),
                  const SizedBox(height: kGap),
                  RateBuckets(
                    title: '按难度',
                    buckets: p.byDifficulty,
                    minSamples: p.minSamples,
                  ),
                  const SizedBox(height: 20),
                  Text(
                    p.disclaimer,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 解答题不自动评分，不进任何正确率：这里只有计数，都是学生自己对照要点标的。
class _SubjectiveCard extends StatelessWidget {
  const _SubjectiveCard({required this.stats});

  final SubjectiveProgress stats;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final checked = stats.selfChecked > 0;
    return Section(
      key: const ValueKey('progress.subjective'),
      title: '解答题',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '提交了 ${stats.attempts} 份，其中 ${stats.selfChecked} 份做了对照自查。',
            style: theme.textTheme.bodyLarge,
          ),
          if (checked) ...[
            const SizedBox(height: 4),
            Text(
              '自查里：做到了 ${stats.pointsDone} 条 · 做到一部分 ${stats.pointsPartial} 条 · '
              '没做到 ${stats.pointsMissed} 条',
              key: const ValueKey('progress.subjective.points'),
              style: theme.textTheme.bodyMedium,
            ),
          ],
          const SizedBox(height: 8),
          Text(
            '解答题不自动评分，这些是你自己对照要点标的，不是官方阅卷分数，也不计入上面的任何正确率。',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}
