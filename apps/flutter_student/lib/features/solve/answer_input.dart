import 'package:flutter/material.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/math_text.dart';
import '../../core/theme.dart';

/// 选择题：点选项。单选是换选，多选是勾选。选中状态靠边框、对勾和文字"已选"表达，不只靠颜色。
class ChoiceInput extends StatelessWidget {
  const ChoiceInput({
    super.key,
    required this.options,
    required this.multiple,
    required this.selected,
    required this.onToggle,
    this.enabled = true,
  });

  final List<QuestionOption> options;
  final bool multiple;
  final Set<String> selected;
  final ValueChanged<String> onToggle;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (multiple)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              '多选题：把你认为正确的选项都点上。',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ),
        for (final option in options)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: _OptionTile(
              option: option,
              selected: selected.contains(option.key),
              multiple: multiple,
              enabled: enabled,
              onTap: () => onToggle(option.key),
            ),
          ),
      ],
    );
  }
}

class _OptionTile extends StatelessWidget {
  const _OptionTile({
    required this.option,
    required this.selected,
    required this.multiple,
    required this.enabled,
    required this.onTap,
  });

  final QuestionOption option;
  final bool selected;
  final bool multiple;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final shape = multiple ? BoxShape.rectangle : BoxShape.circle;
    return Semantics(
      button: true,
      enabled: enabled,
      selected: selected,
      inMutuallyExclusiveGroup: !multiple,
      label: '选项 ${option.key}${selected ? '，已选' : ''}',
      child: Material(
        color: selected
            ? scheme.primaryContainer.withValues(alpha: 0.55)
            : scheme.surfaceContainerLow,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: BorderSide(
            color: selected ? scheme.primary : scheme.outlineVariant,
            width: selected ? 2 : 1,
          ),
        ),
        child: InkWell(
          key: ValueKey('option.${option.key}'),
          borderRadius: BorderRadius.circular(14),
          onTap: enabled ? onTap : null,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 56),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: [
                  Container(
                    width: 32,
                    height: 32,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      shape: shape,
                      borderRadius: multiple ? BorderRadius.circular(8) : null,
                      color: selected ? scheme.primary : Colors.transparent,
                      border: Border.all(
                        color: selected ? scheme.primary : scheme.outline,
                      ),
                    ),
                    child: Text(
                      option.key,
                      style: TextStyle(
                        fontWeight: FontWeight.w700,
                        color: selected ? scheme.onPrimary : scheme.onSurface,
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: MathText(
                      option.text,
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                  ),
                  if (selected) ...[
                    const SizedBox(width: 8),
                    Icon(Icons.check_circle, color: scheme.primary),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 填空题：每个空一个输入框，下面是平板上不好敲的数学符号。
class FillInput extends StatefulWidget {
  const FillInput({
    super.key,
    required this.blanks,
    required this.values,
    required this.onChanged,
    this.enabled = true,
  });

  final List<QuestionBlank> blanks;
  final Map<String, String> values;
  final void Function(String key, String value) onChanged;
  final bool enabled;

  @override
  State<FillInput> createState() => _FillInputState();
}

class _FillInputState extends State<FillInput> {
  final Map<String, TextEditingController> _controllers = {};
  final Map<String, FocusNode> _focus = {};
  String? _active;

  static const symbols = [
    '√',
    'π',
    '²',
    '³',
    '×',
    '÷',
    '≤',
    '≥',
    '∞',
    '°',
    'θ',
    '(',
    ')',
    '[',
    ']',
    ',',
  ];

  @override
  void initState() {
    super.initState();
    for (final blank in widget.blanks) {
      _controllers[blank.key] = TextEditingController(
        text: widget.values[blank.key] ?? '',
      );
      _focus[blank.key] = FocusNode()
        ..addListener(() {
          final node = _focus[blank.key]!;
          if (node.hasFocus) setState(() => _active = blank.key);
        });
    }
    _active = widget.blanks.isEmpty ? null : widget.blanks.first.key;
  }

  @override
  void didUpdateWidget(FillInput oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 外部改了内容（例如冲突时选择采用云端稿）：同步到输入框，但不打断正在输入的光标
    for (final blank in widget.blanks) {
      final controller = _controllers[blank.key];
      final value = widget.values[blank.key] ?? '';
      if (controller != null &&
          controller.text != value &&
          !(_focus[blank.key]?.hasFocus ?? false)) {
        controller.text = value;
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

  void _insert(String symbol) {
    final key = _active;
    if (key == null) return;
    widget.onChanged(key, insertAtCursor(_controllers[key]!, symbol));
    _focus[key]?.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final many = widget.blanks.length > 1;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var i = 0; i < widget.blanks.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Semantics(
              container: true,
              explicitChildNodes: true,
              child: TextField(
                key: ValueKey('blank.${widget.blanks[i].key}'),
                controller: _controllers[widget.blanks[i].key],
                focusNode: _focus[widget.blanks[i].key],
                enabled: widget.enabled,
                maxLength: 200,
                maxLines: 1,
                style: theme.textTheme.bodyLarge,
                decoration: InputDecoration(
                  labelText:
                      widget.blanks[i].label ??
                      (many ? '第 ${i + 1} 空' : '你的答案'),
                  hintText: widget.blanks[i].placeholder,
                  helperText: widget.blanks[i].unitHint,
                  counterText: '',
                ),
                onChanged: (value) =>
                    widget.onChanged(widget.blanks[i].key, value),
              ),
            ),
          ),
        SymbolPalette(
          symbols: symbols,
          onInsert: _insert,
          enabled: widget.enabled,
        ),
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(
            '区间可以写成 (-∞,2]；需要单位的空要带上单位。',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ),
      ],
    );
  }
}

/// 在光标处（有选中内容就替换它）插入一个符号，返回插入后的整段文字。
String insertAtCursor(TextEditingController controller, String symbol) {
  final selection = controller.selection;
  final start = selection.isValid ? selection.start : controller.text.length;
  final end = selection.isValid ? selection.end : controller.text.length;
  final text = controller.text.replaceRange(start, end, symbol);
  controller.value = TextEditingValue(
    text: text,
    selection: TextSelection.collapsed(offset: start + symbol.length),
  );
  return text;
}

/// 平板上不好敲的符号：点一下插进当前输入框。
class SymbolPalette extends StatelessWidget {
  const SymbolPalette({
    super.key,
    required this.symbols,
    required this.onInsert,
    this.enabled = true,
  });

  final List<String> symbols;
  final ValueChanged<String> onInsert;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Wrap(
      spacing: 4,
      runSpacing: 4,
      children: [
        for (final symbol in symbols)
          Semantics(
            button: true,
            label: '插入 $symbol',
            child: ExcludeSemantics(
              child: SizedBox(
                width: AppTheme.minTarget - 4,
                height: AppTheme.minTarget - 4,
                child: OutlinedButton(
                  key: ValueKey('symbol.$symbol'),
                  style: OutlinedButton.styleFrom(
                    padding: EdgeInsets.zero,
                    minimumSize: const Size(
                      AppTheme.minTarget - 4,
                      AppTheme.minTarget - 4,
                    ),
                  ),
                  onPressed: enabled ? () => onInsert(symbol) : null,
                  child: Text(symbol, style: theme.textTheme.titleMedium),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

/// 解答题：每个小问一个多行输入框；也可以只在旁边的草稿上手写，两样都有也行。
/// 解答题不自动评分，这里只负责把学生写的东西接住——提交之后才会有对照要点的自查。
class WrittenInput extends StatefulWidget {
  const WrittenInput({
    super.key,
    required this.subquestions,
    required this.values,
    required this.onChanged,
    this.enabled = true,
  });

  final List<Subquestion> subquestions;
  final Map<String, String> values;
  final void Function(String key, String value) onChanged;
  final bool enabled;

  @override
  State<WrittenInput> createState() => _WrittenInputState();
}

class _WrittenInputState extends State<WrittenInput> {
  static const symbols = [
    '√',
    'π',
    '²',
    '³',
    '×',
    '÷',
    '≤',
    '≥',
    '∞',
    '°',
    'θ',
    'Δ',
    '→',
    '↑',
    '↓',
    '±',
    '(',
    ')',
    '=',
    '^',
  ];

  final Map<String, TextEditingController> _controllers = {};
  final Map<String, FocusNode> _focus = {};
  String? _active;

  @override
  void initState() {
    super.initState();
    for (final sub in widget.subquestions) {
      _controllers[sub.key] = TextEditingController(
        text: widget.values[sub.key] ?? '',
      );
      _focus[sub.key] = FocusNode()
        ..addListener(() {
          if (_focus[sub.key]!.hasFocus) setState(() => _active = sub.key);
        });
    }
    _active = widget.subquestions.isEmpty
        ? null
        : widget.subquestions.first.key;
  }

  @override
  void didUpdateWidget(WrittenInput oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 外部改了内容（采用云端稿、再试一次清空）：同步到输入框，但不打断正在输入的光标
    for (final sub in widget.subquestions) {
      final controller = _controllers[sub.key];
      final value = widget.values[sub.key] ?? '';
      if (controller != null &&
          controller.text != value &&
          !(_focus[sub.key]?.hasFocus ?? false)) {
        controller.text = value;
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

  void _insert(String symbol) {
    final key = _active;
    if (key == null) return;
    widget.onChanged(key, insertAtCursor(_controllers[key]!, symbol));
    _focus[key]?.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final many = widget.subquestions.length > 1;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var i = 0; i < widget.subquestions.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (many)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: Text(
                          '（${i + 1}）',
                          style: theme.textTheme.titleSmall,
                        ),
                      ),
                    Expanded(
                      child: MathText(
                        widget.subquestions[i].stem,
                        style: theme.textTheme.bodyLarge?.copyWith(height: 1.6),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                TextField(
                  key: ValueKey('part.${widget.subquestions[i].key}'),
                  controller: _controllers[widget.subquestions[i].key],
                  focusNode: _focus[widget.subquestions[i].key],
                  enabled: widget.enabled,
                  keyboardType: TextInputType.multiline,
                  minLines: 4,
                  maxLines: 14,
                  maxLength: 4000,
                  style: theme.textTheme.bodyLarge,
                  decoration: InputDecoration(
                    labelText: many ? '第 ${i + 1} 问的解答' : '你的解答',
                    alignLabelWithHint: true,
                    hintText: '写出主要步骤和依据；也可以直接在旁边的草稿上手写。',
                    counterText: '',
                  ),
                  onChanged: (value) =>
                      widget.onChanged(widget.subquestions[i].key, value),
                ),
              ],
            ),
          ),
        SymbolPalette(
          symbols: symbols,
          onInsert: _insert,
          enabled: widget.enabled,
        ),
      ],
    );
  }
}
