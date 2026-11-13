import 'package:flutter/material.dart' hide DataTable;
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/math_text.dart';
import '../../core/widgets.dart';
import 'answer_input.dart';

/// 实验安全提示：每道实验题都有，放在题干下面。
///
/// 这是纸面练习，不是操作指导（PRD §5：审核实验安全提示）。服务端只会发低风险和中等风险的题，
/// 高风险的实验现在不收录。
class ExperimentSafetyNotice extends StatelessWidget {
  const ExperimentSafetyNotice({super.key, required this.safety});

  final ExperimentSafety safety;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final medium = safety.level == ExperimentSafetyLevel.medium;
    return Callout(
      key: const ValueKey('experiment.safety'),
      tone: Tone.warning,
      icon: Icons.health_and_safety_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text('实验安全提示', style: theme.textTheme.titleSmall),
              InfoChip(
                medium ? '中等风险，注意防护' : '低风险',
                icon: Icons.shield_outlined,
                tone: medium ? Tone.warning : Tone.neutral,
              ),
            ],
          ),
          const SizedBox(height: 6),
          for (final note in safety.notes)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text('• $note', style: theme.textTheme.bodyMedium),
            ),
          Text(
            '这是纸面练习，不是操作指导：真实实验请在老师指导下、按实验室规程进行。',
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

/// 实验题：数据表里留空的格子填数，文字小问写分析；也可以只在旁边的草稿上手写。
/// 实验题不自动评分，这里只负责把学生填的东西接住——提交之后才有对照参考数据和要点的自查。
///
/// 题目给定的数据只是文字，不能改；留空的格子才有输入框。格子的键是 "表键.行键.列键"。
class ExperimentInput extends StatefulWidget {
  const ExperimentInput({
    super.key,
    required this.tables,
    required this.subquestions,
    required this.cells,
    required this.parts,
    required this.onCell,
    required this.onPart,
    this.enabled = true,
  });

  final List<DataTable> tables;
  final List<Subquestion> subquestions;
  final Map<String, String> cells;
  final Map<String, String> parts;
  final void Function(String table, String row, String col, String value)
  onCell;
  final void Function(String key, String value) onPart;
  final bool enabled;

  @override
  State<ExperimentInput> createState() => _ExperimentInputState();
}

class _ExperimentInputState extends State<ExperimentInput> {
  final Map<String, TextEditingController> _controllers = {};
  final Map<String, FocusNode> _focus = {};

  static String _cellKey(String table, String row, String col) =>
      '$table.$row.$col';

  Iterable<(String, String, String)> get _blankCells sync* {
    for (final table in widget.tables) {
      for (final row in table.rows) {
        for (final cell in row.cells) {
          if (cell.text == null) yield (table.key, row.key, cell.col);
        }
      }
    }
  }

  @override
  void initState() {
    super.initState();
    for (final (table, row, col) in _blankCells) {
      final key = _cellKey(table, row, col);
      _controllers[key] = TextEditingController(text: widget.cells[key] ?? '');
      _focus[key] = FocusNode();
    }
  }

  @override
  void didUpdateWidget(ExperimentInput oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 外部改了内容（采用云端稿、再试一次清空）：同步到输入框，但不打断正在输入的光标
    for (final entry in _controllers.entries) {
      final value = widget.cells[entry.key] ?? '';
      if (entry.value.text != value &&
          !(_focus[entry.key]?.hasFocus ?? false)) {
        entry.value.text = value;
      }
    }
  }

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    for (final f in _focus.values) {
      f.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final table in widget.tables) ...[
          _tableView(context, table),
          const SizedBox(height: 16),
        ],
        if (widget.subquestions.isNotEmpty)
          WrittenInput(
            subquestions: widget.subquestions,
            values: widget.parts,
            onChanged: widget.onPart,
            enabled: widget.enabled,
          )
        else
          Text(
            '把数填进表里就可以提交；也可以直接在旁边的草稿上手写。',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
      ],
    );
  }

  Widget _tableView(BuildContext context, DataTable table) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final hasRowLabels = table.rows.any((r) => (r.label ?? '').isNotEmpty);

    Widget head(String text) => Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
      child: Text(
        text,
        style: theme.textTheme.labelLarge?.copyWith(
          fontWeight: FontWeight.w700,
        ),
      ),
    );

    return Column(
      key: ValueKey('experiment.table.${table.key}'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(table.title, style: theme.textTheme.titleSmall),
        const SizedBox(height: 8),
        // 窄屏、大字体时表格比屏幕宽：横着滑，不截断
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Table(
            border: TableBorder.all(color: scheme.outlineVariant),
            defaultColumnWidth: const FixedColumnWidth(136),
            columnWidths: hasRowLabels
                ? const {0: FixedColumnWidth(150)}
                : const {},
            defaultVerticalAlignment: TableCellVerticalAlignment.middle,
            children: [
              TableRow(
                decoration: BoxDecoration(
                  color: scheme.surfaceContainerHighest,
                ),
                children: [
                  if (hasRowLabels) head(''),
                  for (final column in table.columns)
                    head(
                      column.unit == null
                          ? column.label
                          : '${column.label}（${column.unit}）',
                    ),
                ],
              ),
              for (var r = 0; r < table.rows.length; r++)
                TableRow(
                  children: [
                    if (hasRowLabels)
                      Padding(
                        padding: const EdgeInsets.all(10),
                        child: MathText(
                          table.rows[r].label ?? '',
                          style: theme.textTheme.bodyMedium,
                        ),
                      ),
                    for (final column in table.columns)
                      _cell(context, table, table.rows[r], r, column),
                  ],
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _cell(
    BuildContext context,
    DataTable table,
    DataTableRow row,
    int rowIndex,
    DataTableColumn column,
  ) {
    final theme = Theme.of(context);
    DataTableCell? given;
    for (final cell in row.cells) {
      if (cell.col == column.key) given = cell;
    }
    final text = given?.text;
    if (given != null && text != null) {
      return Padding(
        padding: const EdgeInsets.all(10),
        child: MathText(text, style: theme.textTheme.bodyLarge),
      );
    }
    final key = _cellKey(table.key, row.key, column.key);
    final controller = _controllers[key];
    if (controller == null) return const SizedBox.shrink();
    final rowName = (row.label ?? '').isNotEmpty
        ? row.label!
        : '第 ${rowIndex + 1} 行';
    return Padding(
      padding: const EdgeInsets.all(6),
      child: Semantics(
        label: '${table.title}，$rowName，${column.label}，请填写',
        child: TextField(
          key: ValueKey('cell.$key'),
          controller: controller,
          focusNode: _focus[key],
          enabled: widget.enabled,
          maxLength: 40,
          maxLines: 1,
          keyboardType: const TextInputType.numberWithOptions(
            decimal: true,
            signed: true,
          ),
          style: theme.textTheme.bodyLarge,
          decoration: const InputDecoration(counterText: ''),
          onChanged: (value) =>
              widget.onCell(table.key, row.key, column.key, value),
        ),
      ),
    );
  }
}
