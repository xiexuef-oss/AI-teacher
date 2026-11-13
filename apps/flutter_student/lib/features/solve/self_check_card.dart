import 'dart:async';

import 'package:flutter/material.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/errors.dart';
import '../../core/math_text.dart';
import '../../core/widgets.dart';
import 'solve_controller.dart';

/// 解答题提交之后的对照自查。
///
/// 解答题不自动评分：系统不给对错，也不打分。学生对照每一个要点，自己标"做到了 / 做到一部分 / 没做到"。
/// 这是学生自己的记录，不是官方阅卷分数，也不会计入正确率；这里只显示各档的个数，不折算成分数。
class SelfCheckCard extends StatelessWidget {
  const SelfCheckCard({super.key, required this.controller});

  final SolveController controller;

  static const _levels = [
    (SelfCheckLevel.done, '做到了', Icons.check_circle_outline),
    (SelfCheckLevel.partial, '做到一部分', Icons.timelapse),
    (SelfCheckLevel.missed, '没做到', Icons.highlight_off),
  ];

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final check = c.selfCheck;
    return Section(
      key: const ValueKey('selfcheck.card'),
      title: '对照要点自查',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '解答题不自动评分。对照下面每一条，自己检查一遍，标出做到了没有。'
            '这是你自己的记录，不是官方阅卷分数，也不会计入正确率。',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 12),
          if (check == null) _waiting(c) else ..._checklist(context, c, check),
        ],
      ),
    );
  }

  /// 要点还没取到：在取，或者取失败了。
  Widget _waiting(SolveController c) {
    if (c.selfCheckBusy) {
      return const Row(
        children: [
          SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: 10),
          Text('正在取要点…'),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Callout(
          tone: Tone.warning,
          child: Text(
            c.selfCheckError == null
                ? '要点还没有取到。'
                : describeError(c.selfCheckError!),
          ),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          key: const ValueKey('selfcheck.retry'),
          onPressed: () => unawaited(c.loadSelfCheck()),
          icon: const Icon(Icons.refresh),
          label: const Text('重试'),
        ),
      ],
    );
  }

  /// 按小问分组；只有一个分组时不加小标题。
  List<Widget> _checklist(
    BuildContext context,
    SolveController c,
    SelfCheck check,
  ) {
    final theme = Theme.of(context);
    final groups = <String?, List<SelfCheckPoint>>{};
    for (final point in check.points) {
      groups.putIfAbsent(point.part$, () => []).add(point);
    }
    final subquestions = c.question?.content.subquestions ?? const [];
    String heading(String? part) {
      if (part == null) return '整份解答';
      final index = subquestions.indexWhere((s) => s.key == part);
      return index < 0 ? '第 $part 问' : '第 ${index + 1} 问';
    }

    final marked = check.points.where((p) => c.marks.containsKey(p.key)).length;
    final saved = check.savedAt != null;
    final canSave = c.selfCheckComplete && c.selfCheckDirty && !c.selfCheckBusy;
    final summary = check.summary;

    return [
      for (final entry in groups.entries) ...[
        if (groups.length > 1)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text(heading(entry.key), style: theme.textTheme.titleSmall),
          ),
        for (final point in entry.value)
          Padding(
            key: ValueKey('selfcheck.point.${point.key}'),
            padding: const EdgeInsets.only(bottom: 14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                MathText(
                  point.text,
                  style: theme.textTheme.bodyLarge?.copyWith(height: 1.5),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final (level, label, icon) in _levels)
                      ChoiceChip(
                        key: ValueKey('selfcheck.${point.key}.${level.value}'),
                        avatar: Icon(icon, size: 18),
                        label: Text(label),
                        selected: c.marks[point.key] == level,
                        onSelected: (_) => c.markPoint(point.key, level),
                      ),
                  ],
                ),
              ],
            ),
          ),
      ],
      const Divider(),
      Wrap(
        spacing: 12,
        runSpacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Text(
            '已标 $marked / ${check.points.length} 条',
            style: theme.textTheme.bodyMedium,
          ),
          FilledButton.icon(
            key: const ValueKey('selfcheck.save'),
            onPressed: canSave ? () => unawaited(c.saveSelfCheck()) : null,
            icon: c.selfCheckBusy
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.save_outlined),
            label: Text(saved ? '更新自查' : '保存自查'),
          ),
          if (saved && c.selfCheckDirty)
            const InfoChip(
              '有改动还没保存',
              icon: Icons.edit_note,
              tone: Tone.warning,
            ),
        ],
      ),
      if (saved) ...[
        const SizedBox(height: 8),
        Text(
          '做到了 ${summary.done} · 做到一部分 ${summary.partial} · '
          '没做到 ${summary.missed}（共 ${summary.total} 条）',
          key: const ValueKey('selfcheck.summary'),
          style: theme.textTheme.bodyMedium?.copyWith(
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
      if (c.selfCheckError != null) ...[
        const SizedBox(height: 8),
        Callout(
          tone: Tone.warning,
          child: Text(describeError(c.selfCheckError!)),
        ),
      ],
      const SizedBox(height: 8),
      Text(
        check.disclaimer,
        style: theme.textTheme.bodySmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
      ),
    ];
  }
}
