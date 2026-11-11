import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/errors.dart';
import '../../core/labels.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

/// P09 我的：地区、年级、学科、考试年份、教材版本都可以改；考试年份和它的来源在这里看得见。
class ProfilePage extends ConsumerWidget {
  const ProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    final config = ref.watch(launchConfigProvider);
    return Scaffold(
      key: const ValueKey('profile.page'),
      appBar: AppBar(title: const Text('我的')),
      body: SafeArea(
        child: profile.when(
          loading: () => const LoadingView(),
          error: (error, _) => ErrorView(
            error: error,
            onRetry: () => ref.invalidate(profileProvider),
          ),
          data: (data) => config.when(
            loading: () => const LoadingView(),
            error: (error, _) => ErrorView(
              error: error,
              onRetry: () => ref.invalidate(launchConfigProvider),
            ),
            data: (options) => _ProfileForm(
              key: ValueKey(
                'profile.form.${data.updatedAt.microsecondsSinceEpoch}',
              ),
              profile: data,
              options: options,
            ),
          ),
        ),
      ),
    );
  }
}

class _ProfileForm extends ConsumerStatefulWidget {
  const _ProfileForm({super.key, required this.profile, required this.options});

  final StudentProfile profile;
  final LaunchConfig options;

  @override
  ConsumerState<_ProfileForm> createState() => _ProfileFormState();
}

class _ProfileFormState extends ConsumerState<_ProfileForm> {
  late RegionCode? _region = widget.profile.regionCode;
  late Grade? _grade = widget.profile.grade;
  late final Set<Subject> _subjects = {...widget.profile.subjects};
  late int? _examYear = widget.profile.examYearSource == ExamYearSource.user
      ? widget.profile.examYear
      : null;
  late String? _curriculum = widget.profile.curriculumVersion;
  bool _saving = false;
  bool _saved = false;
  Object? _error;

  bool get _manualYear => widget.profile.examYearSource == ExamYearSource.user;
  bool get _valid => _region != null && _subjects.isNotEmpty;

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _error = null;
      _saved = false;
    });
    try {
      await ref
          .read(profileProvider.notifier)
          .save(
            ProfileUpdate(
              regionCode: _region!,
              subjects: Subject.values.where(_subjects.contains).toList(),
              grade: _grade,
              examYear: _examYear,
              curriculumVersion: _curriculum,
            ),
          );
      if (mounted) setState(() => _saved = true);
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final profile = widget.profile;
    final options = widget.options;
    final userId = ref.watch(userIdProvider);
    final years = [
      for (var y = options.examYearMin; y <= options.examYearMax; y++) y,
    ];
    final shownYear = _examYear ?? profile.examYear;

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: ListView(
          padding: const EdgeInsets.all(kPad),
          children: [
            Wrap(
              spacing: kGap,
              runSpacing: kGap,
              children: [
                OutlinedButton.icon(
                  key: const ValueKey('profile.progress'),
                  onPressed: () => context.push('/progress'),
                  icon: const Icon(Icons.insights_outlined),
                  label: const Text('我的学情'),
                ),
                OutlinedButton.icon(
                  key: const ValueKey('profile.review'),
                  onPressed: () => context.push('/review'),
                  icon: const Icon(Icons.event_repeat),
                  label: const Text('错题复习'),
                ),
              ],
            ),
            const SizedBox(height: kPad),
            for (final notice in profile.notices)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Callout(tone: Tone.info, child: Text(notice.message)),
              ),
            Section(
              title: '地区与年级',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('地区（自己选择，不用定位）', style: theme.textTheme.labelLarge),
                  const SizedBox(height: 6),
                  SegmentedButton<RegionCode>(
                    key: const ValueKey('profile.region'),
                    showSelectedIcon: false,
                    segments: [
                      for (final region in options.regions.map((r) => r.code))
                        ButtonSegment(
                          value: region,
                          label: Text(regionName(region)),
                        ),
                    ],
                    selected: {?_region},
                    emptySelectionAllowed: true,
                    onSelectionChanged: (s) =>
                        setState(() => _region = s.isEmpty ? null : s.first),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '切换地区只影响之后的推荐，已经做过的记录不变。',
                    style: theme.textTheme.bodySmall,
                  ),
                  const SizedBox(height: kPad),
                  Text('年级', style: theme.textTheme.labelLarge),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      ChoiceChip(
                        key: const ValueKey('profile.grade.none'),
                        label: const Text('先不选'),
                        selected: _grade == null,
                        onSelected: (_) => setState(() => _grade = null),
                      ),
                      for (final g in options.grades)
                        ChoiceChip(
                          key: ValueKey('profile.grade.${g.code.value}'),
                          label: Text(gradeName(g.code)),
                          selected: _grade == g.code,
                          onSelected: (_) => setState(() => _grade = g.code),
                        ),
                    ],
                  ),
                  const SizedBox(height: kPad),
                  Text('科目（至少一科）', style: theme.textTheme.labelLarge),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final s in options.subjects.map((s) => s.code))
                        FilterChip(
                          key: ValueKey('profile.subject.${s.value}'),
                          label: Text(subjectName(s)),
                          selected: _subjects.contains(s),
                          onSelected: (on) => setState(
                            () => on ? _subjects.add(s) : _subjects.remove(s),
                          ),
                        ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: kGap),
            Section(
              title: '考试年份与教材',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('预期高考年份', style: theme.textTheme.labelLarge),
                  const SizedBox(height: 6),
                  DropdownButtonFormField<int?>(
                    key: const ValueKey('profile.examYear'),
                    initialValue: _examYear,
                    items: [
                      if (!_manualYear)
                        const DropdownMenuItem<int?>(
                          value: null,
                          child: Text('按年级估算'),
                        ),
                      for (final y in years)
                        DropdownMenuItem<int?>(value: y, child: Text('$y 年')),
                    ],
                    onChanged: (v) => setState(() => _examYear = v),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _manualYear
                        ? '这是你手动设置的年份，换年级也不会被改掉。'
                        : '目前是按年级估算的${shownYear == null ? '（还没选年级，所以暂时没有）' : '：$shownYear 年'}；学年从 9 月开始算。',
                    style: theme.textTheme.bodySmall,
                  ),
                  if (profile.examSchemeCode != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      '考试制度版本：${profile.examSchemeCode}',
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                  const SizedBox(height: kPad),
                  Text('教材版本', style: theme.textTheme.labelLarge),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      ChoiceChip(
                        key: const ValueKey('profile.curriculum.none'),
                        label: const Text('暂不清楚'),
                        selected: _curriculum == null,
                        onSelected: (_) => setState(() => _curriculum = null),
                      ),
                      for (final c in options.curriculumVersions)
                        ChoiceChip(
                          key: ValueKey('profile.curriculum.${c.code}'),
                          label: Text(c.name),
                          selected: _curriculum == c.code,
                          onSelected: (_) =>
                              setState(() => _curriculum = c.code),
                        ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '教材版本和省份没有对应关系，需要你自己确认。',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            const SizedBox(height: kPad),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Callout(
                  tone: Tone.danger,
                  child: Text(describeError(_error!)),
                ),
              ),
            if (_saved)
              const Padding(
                padding: EdgeInsets.only(bottom: 8),
                child: Callout(
                  key: ValueKey('profile.saved'),
                  tone: Tone.success,
                  child: Text('已保存。'),
                ),
              ),
            FilledButton(
              key: const ValueKey('profile.save'),
              onPressed: _valid && !_saving ? _save : null,
              child: _saving
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('保存'),
            ),
            const SizedBox(height: 28),
            Section(
              title: '隐私与数据',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '• 草稿和笔迹先保存在这台设备上，联网后才同步。\n'
                    '• 家长以后只能看到你授权的、汇总后的每周趋势，看不到你每一笔的草稿。\n'
                    '• AI 给的是练习反馈，不是官方阅卷分数。\n'
                    '• 查看、导出、删除你的数据的功能会在正式上线前提供，现在还没有。',
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '本机演示身份（原型阶段，不是真实账号）：${userId == null ? '—' : userId.substring(0, userId.length < 8 ? userId.length : 8)}',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
