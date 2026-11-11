import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/format.dart';
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
                      _RateCard(
                        keyName: 'independent',
                        title: '独立正确率',
                        stat: p.independent,
                        minSamples: p.minSamples,
                        help: '不看提示、不看解析，一次做对的比例。这是最能说明真实水平的数字。',
                        emphasized: true,
                      ),
                      _RateCard(
                        keyName: 'assisted',
                        title: '辅助正确率',
                        stat: p.assisted,
                        minSamples: p.minSamples,
                        help: '看过提示或解析之后做对的比例，单独计算，不和独立正确率混在一起。',
                      ),
                      _RateCard(
                        keyName: 'hint',
                        title: '提示依赖率',
                        stat: p.hintDependency,
                        minSamples: p.minSamples,
                        help: '第一次作答前用了提示或解析的比例，越低越好。',
                      ),
                      _RateCard(
                        keyName: 'retest',
                        title: '复测成功率',
                        stat: p.retestSuccess,
                        minSamples: p.minSamples,
                        help: '隔了一段时间、不看提示的复测里做对的比例。',
                      ),
                      _RateCard(
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
                  const SizedBox(height: 20),
                  _Buckets(
                    title: '按科目',
                    buckets: p.bySubject,
                    minSamples: p.minSamples,
                  ),
                  const SizedBox(height: kGap),
                  _Buckets(
                    title: '按题型',
                    buckets: p.byAnswerMode,
                    minSamples: p.minSamples,
                  ),
                  const SizedBox(height: kGap),
                  _Buckets(
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

String _count(RateStat stat) => '${stat.numerator}/${stat.denominator}';

class _RateCard extends StatelessWidget {
  const _RateCard({
    required this.keyName,
    required this.title,
    required this.stat,
    required this.minSamples,
    required this.help,
    this.emphasized = false,
  });

  final String keyName;
  final String title;
  final RateStat stat;
  final int minSamples;
  final String help;
  final bool emphasized;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final value = stat.rate == null ? '信息不足' : percent(stat.rate!);
    final detail = stat.denominator == 0
        ? '还没有数据'
        : (stat.insufficientData
              ? '目前 ${_count(stat)}，至少 $minSamples 次有效作答才显示比例'
              : '${_count(stat)} 次有效作答');
    return SizedBox(
      width: emphasized ? 304 : 244,
      child: Card(
        key: ValueKey('progress.$keyName'),
        color: emphasized ? scheme.primaryContainer : null,
        child: Padding(
          padding: const EdgeInsets.all(kPad),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: theme.textTheme.titleSmall),
              const SizedBox(height: 6),
              Text(
                value,
                style:
                    (stat.rate == null
                            ? theme.textTheme.titleLarge
                            : theme.textTheme.headlineMedium)
                        ?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 2),
              Text(detail, style: theme.textTheme.bodySmall),
              const SizedBox(height: 8),
              Text(
                help,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Buckets extends StatelessWidget {
  const _Buckets({
    required this.title,
    required this.buckets,
    required this.minSamples,
  });

  final String title;
  final List<ProgressBucket> buckets;
  final int minSamples;

  String _cell(RateStat stat) {
    if (stat.denominator == 0) return '—';
    final rate = stat.rate == null ? '' : '  ${percent(stat.rate!)}';
    return '${_count(stat)}$rate';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Section(
      title: title,
      child: Column(
        children: [
          Row(
            children: [
              const Expanded(flex: 2, child: SizedBox.shrink()),
              Expanded(
                flex: 3,
                child: Text('独立（对/总）', style: theme.textTheme.labelMedium),
              ),
              Expanded(
                flex: 3,
                child: Text('辅助（对/总）', style: theme.textTheme.labelMedium),
              ),
            ],
          ),
          const Divider(),
          for (final bucket in buckets)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                children: [
                  Expanded(
                    flex: 2,
                    child: Text(
                      bucket.label,
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                  Expanded(
                    flex: 3,
                    child: Text(
                      _cell(bucket.independent),
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                  Expanded(
                    flex: 3,
                    child: Text(
                      _cell(bucket.assisted),
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
