import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/errors.dart';
import '../../core/labels.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

/// 首次使用的三步引导（docs/09）：地区 → 年级与学科 → 教材。
/// 地区只能自己选，应用不会用定位去猜；教材可以"暂不清楚"，不影响开始学习。
class OnboardingPage extends ConsumerStatefulWidget {
  const OnboardingPage({super.key});

  @override
  ConsumerState<OnboardingPage> createState() => _OnboardingPageState();
}

class _OnboardingPageState extends ConsumerState<OnboardingPage> {
  int _step = 0;
  RegionCode? _region;
  Grade? _grade;
  final Set<Subject> _subjects = {
    Subject.math,
    Subject.physics,
    Subject.chemistry,
  };
  String? _curriculum;
  bool _saving = false;
  Object? _error;

  bool get _canContinue => switch (_step) {
    0 => _region != null,
    1 => _subjects.isNotEmpty,
    _ => true,
  };

  Future<void> _finish() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref
          .read(profileProvider.notifier)
          .save(
            ProfileUpdate(
              regionCode: _region!,
              subjects: Subject.values.where(_subjects.contains).toList(),
              grade: _grade,
              curriculumVersion: _curriculum,
            ),
          );
      if (mounted) context.go('/home');
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      key: const ValueKey('onboarding.page'),
      appBar: AppBar(title: const Text('先认识一下你')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(kPad, 8, kPad, 0),
                  child: Row(
                    children: [
                      for (var i = 0; i < 3; i++) ...[
                        Expanded(
                          child: LinearProgressIndicator(
                            value: i <= _step ? 1 : 0,
                            minHeight: 6,
                            borderRadius: BorderRadius.circular(3),
                          ),
                        ),
                        if (i < 2) const SizedBox(width: 6),
                      ],
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(kPad, 8, kPad, 0),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text(
                      '第 ${_step + 1} 步，共 3 步',
                      style: theme.textTheme.bodySmall,
                    ),
                  ),
                ),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.all(kPad),
                    children: [
                      if (_step == 0) _regionStep(context),
                      if (_step == 1) _gradeStep(context),
                      if (_step == 2) _curriculumStep(context),
                      if (_error != null) ...[
                        const SizedBox(height: kGap),
                        Callout(
                          tone: Tone.danger,
                          child: Text(describeError(_error!)),
                        ),
                      ],
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(kPad),
                  child: Row(
                    children: [
                      if (_step > 0)
                        OutlinedButton(
                          key: const ValueKey('onboarding.back'),
                          onPressed: _saving
                              ? null
                              : () => setState(() => _step -= 1),
                          child: const Text('上一步'),
                        ),
                      const Spacer(),
                      FilledButton(
                        key: const ValueKey('onboarding.next'),
                        onPressed: !_canContinue || _saving
                            ? null
                            : (_step < 2
                                  ? () => setState(() => _step += 1)
                                  : _finish),
                        child: _saving
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : Text(_step < 2 ? '下一步' : '开始学习'),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _regionStep(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('你在哪里参加高考？', style: theme.textTheme.headlineSmall),
        const SizedBox(height: 6),
        Text(
          '请自己选择。应用不会用定位去猜，选好之后随时可以在“我的”里改。',
          style: theme.textTheme.bodyMedium,
        ),
        const SizedBox(height: kPad),
        Row(
          children: [
            for (final region in [RegionCode.cn51, RegionCode.cn50])
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(right: kGap),
                  child: _BigChoice(
                    key: ValueKey('region.${region.value}'),
                    label: regionName(region),
                    selected: _region == region,
                    onTap: () => setState(() => _region = region),
                  ),
                ),
              ),
          ],
        ),
      ],
    );
  }

  Widget _gradeStep(BuildContext context) {
    final theme = Theme.of(context);
    final config = ref.watch(launchConfigProvider).asData?.value;
    int? estimated;
    if (_grade != null && config != null) {
      for (final g in config.grades) {
        if (g.code == _grade) estimated = g.estimatedExamYear;
      }
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('你现在读几年级？', style: theme.textTheme.headlineSmall),
        const SizedBox(height: 6),
        Text('年级可以先不选，之后在“我的”里补充。', style: theme.textTheme.bodyMedium),
        const SizedBox(height: kPad),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final grade in [Grade.g10, Grade.g11, Grade.g12])
              ChoiceChip(
                key: ValueKey('grade.${grade.value}'),
                label: Text(gradeName(grade)),
                selected: _grade == grade,
                onSelected: (on) => setState(() => _grade = on ? grade : null),
              ),
          ],
        ),
        if (estimated != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              '预计高考年份：$estimated 年（按年级估算，可以在“我的”里修改）',
              style: theme.textTheme.bodyMedium,
            ),
          ),
        const SizedBox(height: 28),
        Text('想练哪些科目？', style: theme.textTheme.headlineSmall),
        const SizedBox(height: 6),
        Text('至少选一科。', style: theme.textTheme.bodyMedium),
        const SizedBox(height: kPad),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final subject in [
              Subject.math,
              Subject.physics,
              Subject.chemistry,
            ])
              FilterChip(
                key: ValueKey('subject.${subject.value}'),
                label: Text(subjectName(subject)),
                selected: _subjects.contains(subject),
                onSelected: (on) => setState(
                  () => on ? _subjects.add(subject) : _subjects.remove(subject),
                ),
              ),
          ],
        ),
      ],
    );
  }

  Widget _curriculumStep(BuildContext context) {
    final theme = Theme.of(context);
    final options =
        ref.watch(launchConfigProvider).asData?.value.curriculumVersions ??
        const <CurriculumOption>[];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('你们学校用哪个版本的教材？', style: theme.textTheme.headlineSmall),
        const SizedBox(height: 6),
        Text(
          '不清楚也没关系，先按通用知识点学习；翻开教材封面确认后，再到“我的”里补充。',
          style: theme.textTheme.bodyMedium,
        ),
        const SizedBox(height: kPad),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ChoiceChip(
              key: const ValueKey('curriculum.unknown'),
              label: const Text('暂不清楚'),
              selected: _curriculum == null,
              onSelected: (_) => setState(() => _curriculum = null),
            ),
            for (final option in options)
              ChoiceChip(
                key: ValueKey('curriculum.${option.code}'),
                label: Text(option.name),
                selected: _curriculum == option.code,
                onSelected: (_) => setState(() => _curriculum = option.code),
              ),
          ],
        ),
      ],
    );
  }
}

class _BigChoice extends StatelessWidget {
  const _BigChoice({
    super.key,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      selected: selected,
      label: '$label${selected ? '，已选' : ''}',
      child: Material(
        color: selected ? scheme.primaryContainer : scheme.surfaceContainerLow,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(
            color: selected ? scheme.primary : scheme.outlineVariant,
            width: selected ? 2.5 : 1,
          ),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: onTap,
          child: SizedBox(
            height: 96,
            child: Center(
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (selected) ...[
                    Icon(Icons.check_circle, color: scheme.primary),
                    const SizedBox(width: 8),
                  ],
                  Text(label, style: Theme.of(context).textTheme.headlineSmall),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
