import 'package:flutter/material.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/math_text.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import 'answer_input.dart' show SymbolPalette, insertAtCursor;
import 'draft_store.dart' show ProofStepDraft;

const _circled = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧'];

/// 已知条件的编号：①②③…（最多 8 条）。学生写依据时可以说"由已知①"。
String givenMark(int index) =>
    index < _circled.length ? _circled[index] : '(${index + 1})';

/// 证明题题干下面的"已知"和"求证"。参考证明不在这里：它只在提交之后随自查给出。
class ProofStatementBlock extends StatelessWidget {
  const ProofStatementBlock({super.key, required this.proof});

  final ProofStatement proof;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final body = theme.textTheme.bodyLarge?.copyWith(fontSize: 18, height: 1.7);
    return Section(
      key: const ValueKey('proof.statement'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (proof.givens.isNotEmpty) ...[
            Text('已知', style: theme.textTheme.titleSmall),
            const SizedBox(height: 4),
            for (var i = 0; i < proof.givens.length; i++)
              Padding(
                key: ValueKey('proof.given.$i'),
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(width: 30, child: Text(givenMark(i), style: body)),
                    Expanded(child: MathText(proof.givens[i], style: body)),
                  ],
                ),
              ),
            const SizedBox(height: 8),
          ],
          Text('求证', style: theme.textTheme.titleSmall),
          const SizedBox(height: 4),
          MathText(
            proof.claim,
            key: const ValueKey('proof.claim'),
            style: body?.copyWith(fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

/// 一步的两个输入框和它们的焦点。第 i 张卡片永远对应第 i 个槽，内容由 [ProofInput.steps] 同步进来。
class _Slot {
  _Slot(ProofStepDraft step)
    : text = TextEditingController(text: step.text),
      reason = TextEditingController(text: step.reason),
      textFocus = FocusNode(),
      reasonFocus = FocusNode();

  final TextEditingController text;
  final TextEditingController reason;
  final FocusNode textFocus;
  final FocusNode reasonFocus;

  void dispose() {
    text.dispose();
    reason.dispose();
    textFocus.dispose();
    reasonFocus.dispose();
  }
}

/// 证明题：把证明写成一步一步，每一步写上依据。顺序就是证明的顺序，可以上移、下移、删除，也可以只在旁边的草稿上手写。
/// 证明题不自动评分，这里只负责把学生写的东西接住——提交之后才有对照参考证明和要点的自查。
///
/// [structure] 是步骤结构的版本号：添加、删除、挪动、整体换掉（采用云端稿、再试一次）时会变，
/// 这时所有输入框都按 [steps] 重新同步；平时只同步没有焦点的输入框，不打断正在输入的光标。
class ProofInput extends StatefulWidget {
  const ProofInput({
    super.key,
    required this.steps,
    required this.structure,
    required this.onText,
    required this.onReason,
    required this.onAdd,
    required this.onRemove,
    required this.onMove,
    this.canAdd = true,
    this.enabled = true,
  });

  final List<ProofStepDraft> steps;
  final int structure;
  final void Function(int index, String value) onText;
  final void Function(int index, String value) onReason;
  final VoidCallback onAdd;
  final ValueChanged<int> onRemove;
  final void Function(int index, int delta) onMove;
  final bool canAdd;
  final bool enabled;

  @override
  State<ProofInput> createState() => _ProofInputState();
}

class _ProofInputState extends State<ProofInput> {
  /// 证明里常用、平板上不好敲的符号。
  static const symbols = [
    '∵',
    '∴',
    '≤',
    '≥',
    '≠',
    '≈',
    '∈',
    '∠',
    '⊥',
    '∥',
    '△',
    '√',
    'π',
    '²',
    '³',
    '×',
    '÷',
    '±',
    '∞',
    '→',
    '(',
    ')',
    '=',
    '^',
  ];

  final List<_Slot> _slots = [];

  /// 最近聚焦的输入框：(第几步, 是不是依据框)。符号条插到这里。
  (int, bool)? _active;

  @override
  void initState() {
    super.initState();
    _syncSlots(force: true);
  }

  @override
  void didUpdateWidget(ProofInput oldWidget) {
    super.didUpdateWidget(oldWidget);
    _syncSlots(force: oldWidget.structure != widget.structure);
  }

  @override
  void dispose() {
    for (final slot in _slots) {
      slot.dispose();
    }
    super.dispose();
  }

  _Slot _newSlot(int index) {
    final slot = _Slot(widget.steps[index]);
    slot.textFocus.addListener(() {
      if (slot.textFocus.hasFocus) _active = (index, false);
    });
    slot.reasonFocus.addListener(() {
      if (slot.reasonFocus.hasFocus) _active = (index, true);
    });
    return slot;
  }

  /// 让槽的个数和内容跟上 [ProofInput.steps]。
  void _syncSlots({required bool force}) {
    while (_slots.length > widget.steps.length) {
      _slots.removeLast().dispose();
    }
    while (_slots.length < widget.steps.length) {
      _slots.add(_newSlot(_slots.length));
    }
    for (var i = 0; i < _slots.length; i++) {
      final step = widget.steps[i];
      final slot = _slots[i];
      if (slot.text.text != step.text && (force || !slot.textFocus.hasFocus)) {
        slot.text.text = step.text;
      }
      if (slot.reason.text != step.reason &&
          (force || !slot.reasonFocus.hasFocus)) {
        slot.reason.text = step.reason;
      }
    }
    if (force) _active = null;
  }

  void _insert(String symbol) {
    final (index, isReason) = _active ?? (0, false);
    if (index >= _slots.length) return;
    final slot = _slots[index];
    final controller = isReason ? slot.reason : slot.text;
    final text = insertAtCursor(controller, symbol);
    if (isReason) {
      widget.onReason(index, text);
    } else {
      widget.onText(index, text);
    }
    (isReason ? slot.reasonFocus : slot.textFocus).requestFocus();
  }

  Widget _iconButton({
    required String key,
    required String tooltip,
    required IconData icon,
    required VoidCallback? onPressed,
  }) {
    return IconButton(
      key: ValueKey(key),
      tooltip: tooltip,
      icon: Icon(icon),
      onPressed: onPressed,
      constraints: const BoxConstraints(
        minWidth: AppTheme.minTarget,
        minHeight: AppTheme.minTarget,
      ),
    );
  }

  Widget _stepCard(BuildContext context, int i) {
    final theme = Theme.of(context);
    final slot = _slots[i];
    final last = widget.steps.length - 1;
    final enabled = widget.enabled;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: DecoratedBox(
        key: ValueKey('proof.step.$i'),
        decoration: BoxDecoration(
          border: Border.all(color: theme.colorScheme.outlineVariant),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Padding(
          padding: EdgeInsets.fromLTRB(12, enabled ? 0 : 10, 12, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '第 ${i + 1} 步',
                      style: theme.textTheme.titleSmall,
                    ),
                  ),
                  if (enabled) ...[
                    _iconButton(
                      key: 'proof.step.$i.up',
                      tooltip: '第 ${i + 1} 步上移',
                      icon: Icons.arrow_upward,
                      onPressed: i > 0 ? () => widget.onMove(i, -1) : null,
                    ),
                    _iconButton(
                      key: 'proof.step.$i.down',
                      tooltip: '第 ${i + 1} 步下移',
                      icon: Icons.arrow_downward,
                      onPressed: i < last ? () => widget.onMove(i, 1) : null,
                    ),
                    _iconButton(
                      key: 'proof.step.$i.remove',
                      tooltip: '删除第 ${i + 1} 步',
                      icon: Icons.delete_outline,
                      onPressed: () => widget.onRemove(i),
                    ),
                  ],
                ],
              ),
              TextField(
                key: ValueKey('proof.step.$i.text'),
                controller: slot.text,
                focusNode: slot.textFocus,
                enabled: enabled,
                keyboardType: TextInputType.multiline,
                minLines: 2,
                maxLines: 8,
                maxLength: 1000,
                style: theme.textTheme.bodyLarge,
                decoration: InputDecoration(
                  labelText: '第 ${i + 1} 步：这一步写什么',
                  alignLabelWithHint: true,
                  hintText: '例如：因为 ……，所以 ……',
                  counterText: '',
                ),
                onChanged: (value) => widget.onText(i, value),
              ),
              const SizedBox(height: 8),
              TextField(
                key: ValueKey('proof.step.$i.reason'),
                controller: slot.reason,
                focusNode: slot.reasonFocus,
                enabled: enabled,
                keyboardType: TextInputType.multiline,
                minLines: 1,
                maxLines: 3,
                maxLength: 400,
                style: theme.textTheme.bodyLarge,
                decoration: InputDecoration(
                  labelText: '第 ${i + 1} 步的依据',
                  alignLabelWithHint: true,
                  hintText: '定义、定理、已知条件（如“已知①”）或前面的某一步',
                  counterText: '',
                ),
                onChanged: (value) => widget.onReason(i, value),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final enabled = widget.enabled;
    return Column(
      key: const ValueKey('proof.input'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (enabled)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(
              '一步一步写：每一步写上依据（已知条件、定义、定理，或前面的某一步），证明才完整。'
              '也可以直接在旁边的草稿上手写。',
              style: theme.textTheme.bodyMedium,
            ),
          ),
        for (var i = 0; i < widget.steps.length; i++) _stepCard(context, i),
        if (enabled) ...[
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              key: const ValueKey('proof.addStep'),
              onPressed: widget.canAdd ? widget.onAdd : null,
              icon: const Icon(Icons.add),
              label: Text(widget.canAdd ? '添加一步' : '最多 30 步'),
            ),
          ),
          const SizedBox(height: 12),
          SymbolPalette(symbols: symbols, onInsert: _insert),
        ],
      ],
    );
  }
}
