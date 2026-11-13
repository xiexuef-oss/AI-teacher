import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/errors.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/rate_widgets.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

/// P10 家长周报：已授权学生某一周的汇总。
///
/// 只有计数和比例，口径和学生自己的学情页一致：独立和辅助分开、样本不足只给计数、解答题不进比例。
/// 不是官方成绩，没有排名、没有连续天数，也没有任何一道具体的题或一次具体的作答。
class ParentWeeklyPage extends ConsumerStatefulWidget {
  const ParentWeeklyPage({super.key, required this.studentId});

  final String studentId;

  @override
  ConsumerState<ParentWeeklyPage> createState() => _ParentWeeklyPageState();
}

class _ParentWeeklyPageState extends ConsumerState<ParentWeeklyPage> {
  /// 看的是哪一周的周一（`2026-11-09`）；null 是当前这一周，由服务端按它的日历决定。
  String? _week;

  WeeklyQuery get _query => (studentId: widget.studentId, weekStart: _week);

  @override
  Widget build(BuildContext context) {
    final query = _query;
    final weekly = ref.watch(parentWeeklyProvider(query));

    // 授权被撤销（或根本没绑定）：服务端对这两种情况都是 404。回去时家长页上不该还留着这位学生。
    ref.listen(parentWeeklyProvider(query), (_, next) {
      final error = next.error;
      if (error != null && isNotFoundError(error)) {
        ref.invalidate(parentStudentsProvider);
      }
    });

    return Scaffold(
      key: const ValueKey('parent.weekly.page'),
      appBar: AppBar(
        leading: BackButton(
          key: const ValueKey('parent.weekly.appBarBack'),
          onPressed: () =>
              context.canPop() ? context.pop() : context.go('/parent'),
        ),
        title: const Text('每周汇总'),
      ),
      body: SafeArea(
        child: weekly.when(
          loading: () => const LoadingView(),
          error: (error, _) => isNotFoundError(error)
              ? EmptyView(
                  key: const ValueKey('parent.weekly.unauthorized'),
                  icon: Icons.lock_outline,
                  title: '看不到这位学生的周报',
                  message: '学生的授权已经撤销，或者还没有授权给你。这里不会显示任何数据。',
                  action: FilledButton(
                    key: const ValueKey('parent.weekly.back'),
                    onPressed: () => context.go('/parent'),
                    child: const Text('回到家长页'),
                  ),
                )
              : ErrorView(
                  error: error,
                  onRetry: () => ref.invalidate(parentWeeklyProvider(query)),
                ),
          data: (report) => _Report(
            report: report,
            onWeek: (week) => setState(() => _week = week),
          ),
        ),
      ),
    );
  }
}

class _Report extends ConsumerWidget {
  const _Report({required this.report, required this.onWeek});

  final ParentWeekly report;
  final void Function(String weekStart) onWeek;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final now = ref.watch(clockProvider)();
    final empty = report.sessionsCount == 0 && report.attemptsCount == 0;

    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 960),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(kPad),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                report.studentDisplayName ?? '学生 ${shortId(report.studentId)}',
                style: theme.textTheme.titleMedium,
              ),
              const SizedBox(height: 4),
              Text(
                '${monthDayOfIso(report.weekStart)} – ${monthDayOfIso(report.weekEnd)}',
                key: const ValueKey('parent.weekly.range'),
                style: theme.textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                report.isComplete ? '这一周已经结束' : '这一周还没结束',
                style: theme.textTheme.bodyMedium,
              ),
              if (!report.isComplete)
                Text(
                  '还没过完，数字还会变。',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              const SizedBox(height: kGap),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      key: const ValueKey('parent.weekly.previous'),
                      onPressed: () =>
                          onWeek(addDaysToIso(report.weekStart, -7)),
                      icon: const Icon(Icons.chevron_left),
                      label: const Text('上一周'),
                    ),
                  ),
                  const SizedBox(width: kGap),
                  Expanded(
                    child: OutlinedButton.icon(
                      key: const ValueKey('parent.weekly.next'),
                      // 这一周还没结束，就是最新的一周，没有再往后的了
                      onPressed: report.isComplete
                          ? () => onWeek(addDaysToIso(report.weekStart, 7))
                          : null,
                      iconAlignment: IconAlignment.end,
                      icon: const Icon(Icons.chevron_right),
                      label: const Text('下一周'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: kPad),
              if (empty)
                Callout(
                  key: const ValueKey('parent.weekly.empty'),
                  tone: Tone.neutral,
                  icon: Icons.event_busy_outlined,
                  child: const Text(
                    '这一周还没有学习记录。\n'
                    '没有记录不代表出了问题，可能只是这一周没安排练习。',
                  ),
                )
              else ...[
                Wrap(
                  spacing: kGap,
                  runSpacing: kGap,
                  children: [
                    _Count(
                      keyName: 'activeDays',
                      label: '有作答的天数',
                      value: '${report.activeDays} 天',
                    ),
                    _Count(
                      keyName: 'sessions',
                      label: '开始的练习',
                      value: '${report.sessionsCount} 次',
                    ),
                    _Count(
                      keyName: 'attempts',
                      label: '提交作答',
                      value: '${report.attemptsCount} 份',
                    ),
                  ],
                ),
                const SizedBox(height: kPad),
                Wrap(
                  spacing: kGap,
                  runSpacing: kGap,
                  children: [
                    RateCard(
                      keyPrefix: 'parent.weekly',
                      keyName: 'independent',
                      title: '独立正确率',
                      stat: report.independent,
                      minSamples: report.minSamples,
                      help: '不看提示、不看解析，一次做对的比例。最能说明真实水平。',
                      emphasized: true,
                    ),
                    RateCard(
                      keyPrefix: 'parent.weekly',
                      keyName: 'assisted',
                      title: '辅助正确率',
                      stat: report.assisted,
                      minSamples: report.minSamples,
                      help: '看过提示或解析之后做对的比例，单独计算。',
                    ),
                    RateCard(
                      keyPrefix: 'parent.weekly',
                      keyName: 'hint',
                      title: '提示依赖率',
                      stat: report.hintDependency,
                      minSamples: report.minSamples,
                      help: '第一次作答前就用了提示或解析的比例。',
                    ),
                    RateCard(
                      keyPrefix: 'parent.weekly',
                      keyName: 'retest',
                      title: '复测成功率',
                      stat: report.retestSuccess,
                      minSamples: report.minSamples,
                      help: '隔了几天、不看提示的复测里做对的比例。',
                    ),
                  ],
                ),
                const SizedBox(height: kPad),
                _TrendCard(report: report),
                if (report.writtenAttempts > 0) ...[
                  const SizedBox(height: kGap),
                  Callout(
                    key: const ValueKey('parent.weekly.written'),
                    tone: Tone.neutral,
                    icon: Icons.edit_note,
                    child: Text(
                      '解答题 ${report.writtenAttempts} 份：解答题不自动评分，'
                      '只记提交了几份，不计入上面的比例。',
                    ),
                  ),
                ],
                const SizedBox(height: kPad),
                RateBuckets(
                  title: '按科目',
                  buckets: report.bySubject,
                  minSamples: report.minSamples,
                ),
              ],
              const SizedBox(height: 20),
              Text(report.disclaimer, style: theme.textTheme.bodySmall),
              const SizedBox(height: 4),
              Text(
                '更新于 ${formatWhen(report.generatedAt, now)}',
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

class _Count extends StatelessWidget {
  const _Count({
    required this.keyName,
    required this.label,
    required this.value,
  });

  final String keyName;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ConstrainedBox(
      constraints: const BoxConstraints(minWidth: 112),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: kPad, vertical: 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: theme.textTheme.bodySmall),
              const SizedBox(height: 2),
              Text(
                value,
                key: ValueKey('parent.weekly.$keyName'),
                style: theme.textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 和上一周比：只用中性的话说"高了、低了、差不多、暂时比不了"，没有排名和评语；
/// 图标旁边一定有文字，也不用红绿颜色。
class _TrendCard extends StatelessWidget {
  const _TrendCard({required this.report});

  final ParentWeekly report;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (IconData icon, String text) = switch (report.independentTrend) {
      WeeklyTrend.up => (Icons.trending_up, '独立正确率比上一周高了'),
      WeeklyTrend.down => (Icons.trending_down, '独立正确率比上一周低了'),
      WeeklyTrend.flat => (Icons.trending_flat, '独立正确率和上一周差不多'),
      // 服务端新增了这个版本不认识的值时，也按"暂时比不了"处理，不乱猜
      _ => (Icons.help_outline, '独立正确率暂时比不了：这一周或上一周的有效作答还不够多。'),
    };
    final previous = report.previousWeek;
    return Section(
      title: '和上一周比',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: theme.colorScheme.onSurfaceVariant),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  text,
                  key: const ValueKey('parent.weekly.trend'),
                  style: theme.textTheme.bodyLarge,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '上一周（${monthDayOfIso(previous.weekStart)}起）提交作答 ${previous.attemptsCount} 份。'
            '比上一周高或低 5 个百分点以上才算「变了」，小的起伏算差不多。',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}
