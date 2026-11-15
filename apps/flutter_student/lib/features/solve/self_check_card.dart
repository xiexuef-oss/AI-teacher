import 'dart:async';

import 'package:flutter/material.dart' hide DataTable;
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/errors.dart';
import '../../core/math_text.dart';
import '../../core/widgets.dart';
import 'experiment_input.dart' show experimentRowName;
import 'solve_controller.dart';

/// 解答题、实验题提交之后的对照自查。
///
/// 解答题和实验题不自动评分：系统不给对错，也不打分。学生对照每一个要点，自己标"做到了 / 做到一部分 / 没做到"。
/// 实验题还给数据表里留空格子的参考数据，让学生把自己填的数和它并排对照——只是并排，不判对错。
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
    final experiment = c.question?.answerMode == AnswerMode.experiment;
    return Section(
      key: const ValueKey('selfcheck.card'),
      title: '对照要点自查',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            experiment
                ? '实验题不自动评分。先把你填的数和参考数据并排看一遍，再对照下面每一条，自己检查，标出做到了没有。'
                      '这是你自己的记录，不是官方阅卷分数，也不会计入正确率。'
                : '解答题不自动评分。对照下面每一条，自己检查一遍，标出做到了没有。'
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
    final tables = c.question?.content.dataTables ?? const <DataTable>[];
    final experiment = c.question?.answerMode == AnswerMode.experiment;
    String heading(String? part) {
      if (part == null) return experiment ? '整份作答' : '整份解答';
      final index = subquestions.indexWhere((s) => s.key == part);
      if (index >= 0) return '第 ${index + 1} 问';
      final table = tables.where((t) => t.key == part);
      if (table.isNotEmpty) return '数据表：${table.first.title}';
      return '第 $part 问';
    }

    final marked = check.points.where((p) => c.marks.containsKey(p.key)).length;
    final saved = check.savedAt != null;
    final canSave = c.selfCheckComplete && c.selfCheckDirty && !c.selfCheckBusy;
    final summary = check.summary;

    return [
      if (check.referenceCells.isNotEmpty) ...[
        _ReferenceTable(
          tables: tables,
          mine: c.cells,
          reference: {
            for (final cell in check.referenceCells)
              '${cell.table}.${cell.row}.${cell.col}': cell.value,
          },
        ),
        const SizedBox(height: 16),
      ],
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

/// 实验题数据表里留空的格子：你填的和参考数据并排，没填的也列出来。
/// 只是并排，不判对错——不用对勾和红绿色，也不说"对了"或"错了"。
class _ReferenceTable extends StatelessWidget {
  const _ReferenceTable({
    required this.tables,
    required this.mine,
    required this.reference,
  });

  final List<DataTable> tables;

  /// 学生填的，键是 "表键.行键.列键"。
  final Map<String, String> mine;
  final Map<String, String> reference;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final head = theme.textTheme.labelLarge;
    Text value(String text, {bool strong = false}) => Text(
      text,
      style: theme.textTheme.bodyLarge?.copyWith(
        fontWeight: strong ? FontWeight.w700 : null,
      ),
    );

    final sections = <Widget>[];
    for (final table in tables) {
      final lines = <Widget>[];
      for (var r = 0; r < table.rows.length; r++) {
        final row = table.rows[r];
        for (final cell in row.cells) {
          final key = '${table.key}.${row.key}.${cell.col}';
          if (cell.text != null || !reference.containsKey(key)) continue;
          final column = table.columns.where((c) => c.key == cell.col);
          final label = column.isEmpty ? cell.col : column.first.label;
          final unit = column.isEmpty || column.first.unit == null
              ? ''
              : '（${column.first.unit}）';
          final rowName = experimentRowName(table, row, r);
          final filled = (mine[key] ?? '').trim();
          lines.add(
            _RefLine(
              key: ValueKey('selfcheck.ref.$key'),
              label: rowName,
              sub: '$label$unit',
              mine: value(filled.isEmpty ? '没填' : filled),
              reference: value(reference[key]!, strong: true),
            ),
          );
        }
      }
      if (lines.isEmpty) continue;
      sections.addAll([
        Padding(
          padding: const EdgeInsets.only(top: 6, bottom: 2),
          child: Text(table.title, style: head),
        ),
        _RefLine(
          label: '格子',
          mine: Text('你填的', style: head),
          reference: Text('参考数据', style: head),
          heading: true,
        ),
        const Divider(height: 1),
        ...lines,
      ]);
    }

    return Column(
      key: const ValueKey('selfcheck.reference'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('对照参考数据', style: theme.textTheme.titleSmall),
        const SizedBox(height: 4),
        Text(
          '参考数据只是让你对照的，不是评分：数不一样，先看是哪一步不同，再去标下面的要点。',
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: 8),
        ...sections,
      ],
    );
  }
}

class _RefLine extends StatelessWidget {
  const _RefLine({
    super.key,
    required this.label,
    this.sub,
    required this.mine,
    required this.reference,
    this.heading = false,
  });

  /// 这一行叫什么（行名）。
  final String label;

  /// 行名下面的一行小字：列名和单位。
  final String? sub;
  final Widget mine;
  final Widget reference;
  final bool heading;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 5,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (heading)
                  Text(label, style: theme.textTheme.labelLarge)
                else
                  MathText(label, style: theme.textTheme.bodyMedium),
                if (sub != null)
                  Text(
                    sub!,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
              ],
            ),
          ),
          Expanded(flex: 3, child: mine),
          Expanded(flex: 3, child: reference),
        ],
      ),
    );
  }
}
