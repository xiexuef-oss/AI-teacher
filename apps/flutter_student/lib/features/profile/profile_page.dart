import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/errors.dart';
import '../../core/format.dart';
import '../../core/labels.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import 'parent_access_section.dart';
import 'learning_pack_section.dart';
import 'school_material_section.dart';
import 'student_data_export_section.dart';

/// P09 我的：地区、年级、学科、考试年份、教材版本都可以改；考试年份和它的来源在这里看得见。
class ProfilePage extends ConsumerWidget {
  const ProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    final config = ref.watch(launchConfigProvider);
    Widget unavailable(Object error, VoidCallback retry) => ListView(
      padding: const EdgeInsets.all(kPad),
      children: [
        ErrorView(error: error, onRetry: retry),
        const StudentDataExportSection(),
        const StudentDataExportSection(server: true),
        const StudentDataExportSection.scans(),
        const StudentDataExportSection.media(),
        const StudentDataExportSection.recovery(),
      ],
    );
    return Scaffold(
      key: const ValueKey('profile.page'),
      appBar: AppBar(title: const Text('我的')),
      body: SafeArea(
        child: profile.when(
          loading: () => const LoadingView(),
          error: (error, _) {
            final legacy = ref
                .read(profileProvider.notifier)
                .bundle
                ?.legacyProfile;
            final options = config.asData?.value;
            if (legacy != null && options != null) {
              return _ProfileForm(
                key: ValueKey('profile.form.${ref.watch(userIdProvider)}'),
                profile: StudentProfile.fromJson(legacy),
                options: options,
              );
            }
            return unavailable(error, () => ref.invalidate(profileProvider));
          },
          data: (data) => config.when(
            loading: () => const LoadingView(),
            error: (error, _) =>
                unavailable(error, () => ref.invalidate(launchConfigProvider)),
            data: (options) => _ProfileForm(
              key: ValueKey('profile.form.${ref.watch(userIdProvider)}'),
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
  static const _learningModes = {
    'boarding': '住校纸笔学习',
    'weekend': '周末集中学习',
    'digital': '日常数字学习',
  };
  late RegionCode? _region = widget.profile.regionCode;
  late Grade? _grade = widget.profile.grade;
  late final Set<Subject> _subjects = {...widget.profile.subjects};
  late int? _examYear = widget.profile.examYearSource == ExamYearSource.user
      ? widget.profile.examYear
      : null;
  late String? _curriculum = widget.profile.curriculumVersion;
  late String? _mode = widget.profile.learningSettings?.mode;
  late final Set<int> _weekdays = {
    ...widget.profile.learningSettings?.weekdays ?? [1, 2, 3, 4, 5],
  };
  late final _minutes = TextEditingController(
    text: '${widget.profile.learningSettings?.weeklyMinutes ?? 50}',
  );
  late final _schoolProgress = TextEditingController(
    text: widget.profile.learningSettings?.schoolProgress,
  );
  late final _examScope = TextEditingController(
    text: widget.profile.learningSettings?.examScope,
  );
  int? get _weeklyMinutes => int.tryParse(_minutes.text);
  LearningSettings? get _learningSettings => _mode == null
      ? null
      : LearningSettings(
          mode: _mode!,
          weeklyMinutes: _weeklyMinutes ?? 0,
          weekdays: _weekdays.toList()..sort(),
          schoolProgress: _schoolProgress.text.trim(),
          examScope: _examScope.text.trim(),
        );

  void _restoreLearning(LearningSettings? settings) {
    _mode = settings?.mode;
    _minutes.text = '${settings?.weeklyMinutes ?? 50}';
    _weekdays
      ..clear()
      ..addAll(settings?.weekdays ?? [1, 2, 3, 4, 5]);
    _schoolProgress.text = settings?.schoolProgress ?? '';
    _examScope.text = settings?.examScope ?? '';
  }

  // 称呼：只有家长看周报时会看到；留空表示不改（接口没有"清除"这个动作）
  late final TextEditingController _name = TextEditingController(
    text: widget.profile.displayName ?? '',
  );
  bool _saving = false;
  bool _saved = false;
  Object? _error;

  String _summary(Map<String, dynamic> fields) {
    final region = fields['region_code'];
    final grade = fields['grade'];
    final subjects = (fields['subjects'] as List? ?? [])
        .map((s) => subjectName(Subject.fromJson(s)))
        .join('、');
    final learning = fields['learning_settings'] as Map?;
    final schedule = learning == null
        ? ''
        : ' · ${_learningModes[learning['mode']]}'
              ' · 每周 ${fields['learning_budget_edit'] ?? learning['weekly_minutes']} 分钟'
              ' · 学习日 ${(learning['weekdays'] as List).join('、')}'
              ' · 学校进度 ${learning['school_progress'] ?? ''}'
              ' · 考试范围 ${learning['exam_scope'] ?? ''}';
    return '${fields['display_name'] ?? '未填称呼'} · '
        '${region == null ? '未选地区' : regionName(RegionCode.fromJson(region))} · '
        '${grade == null ? '未选年级' : gradeName(Grade.fromJson(grade))} · '
        '$subjects · ${fields['exam_year'] ?? '按年级估算'} · '
        '${fields['curriculum_version'] ?? '教材暂不清楚'}$schedule';
  }

  int _editSerial = 0;
  Map<String, dynamic> get _fields => {
    if (_region != null) 'region_code': _region!.value,
    'subjects': Subject.values
        .where(_subjects.contains)
        .map((s) => s.value)
        .toList(),
    if (_grade != null) 'grade': _grade!.value,
    if (_examYear != null) 'exam_year': _examYear,
    if (_curriculum != null) 'curriculum_version': _curriculum,
    if (_name.text.trim().isNotEmpty) 'display_name': _name.text.trim(),
    if (_learningSettings case final settings?)
      'learning_settings': settings.toJson(),
    if (_mode != null) 'learning_budget_edit': _minutes.text,
  };

  @override
  void initState() {
    super.initState();
    final edit = ref.read(profileProvider.notifier).bundle?.edit;
    if (edit != null) _restore(edit);
  }

  void _restore(Map<String, dynamic> fields) {
    _region = fields['region_code'] == null
        ? null
        : RegionCode.fromJson(fields['region_code']);
    _grade = fields['grade'] == null ? null : Grade.fromJson(fields['grade']);
    _subjects
      ..clear()
      ..addAll(
        (fields['subjects'] as List? ?? []).map(
          (s) => Subject.fromJson(s as String),
        ),
      );
    _examYear = fields['exam_year'] as int?;
    _curriculum = fields['curriculum_version'] as String?;
    _name.text = fields['display_name'] as String? ?? '';
    final settings = fields['learning_settings'];
    _restoreLearning(
      settings == null
          ? widget.profile.learningSettings
          : LearningSettings.fromJson(
              Map<String, dynamic>.from(settings as Map),
            ),
    );
    if (fields['learning_budget_edit'] case final String text) {
      _minutes.text = text;
    }
  }

  void _change(VoidCallback change) {
    setState(() {
      change();
      _saved = false;
      _editSerial++;
    });
    _persist();
  }

  Future<void> _persist() async {
    try {
      await ref.read(profileProvider.notifier).edit(_fields);
    } catch (error) {
      if (mounted) setState(() => _error = error);
    }
  }

  Future<void> _recover() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref.read(profileProvider.notifier).retryPending();
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _resolve(bool useCloud) async {
    final serial = _editSerial;
    try {
      final controller = ref.read(profileProvider.notifier);
      if (!useCloud) {
        await controller.edit(_fields);
        if (!mounted || serial != _editSerial) return;
      }
      await controller.resolveConflict(useCloud: useCloud);
      if (!mounted || serial != _editSerial) return;
      setState(() {
        final fields = controller.bundle?.edit;
        if (fields != null) {
          _restore(fields);
        } else {
          final cloud = controller.bundle!.cloud!;
          _region = cloud.regionCode;
          _grade = cloud.grade;
          _subjects
            ..clear()
            ..addAll(cloud.subjects);
          _examYear = cloud.examYearSource == ExamYearSource.user
              ? cloud.examYear
              : null;
          _curriculum = cloud.curriculumVersion;
          _name.text = cloud.displayName ?? '';
          _restoreLearning(cloud.learningSettings);
        }
        _saved = false;
      });
    } catch (error) {
      if (mounted) setState(() => _error = error);
    }
  }

  bool get _manualYear => widget.profile.examYearSource == ExamYearSource.user;
  bool get _valid =>
      _region != null &&
      _subjects.isNotEmpty &&
      (_mode == null ||
          (_weeklyMinutes ?? -1) >= 0 && _weeklyMinutes! <= 10080);

  @override
  void dispose() {
    _name.dispose();
    _minutes.dispose();
    _schoolProgress.dispose();
    _examScope.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final serial = _editSerial;
    setState(() {
      _saving = true;
      _error = null;
      _saved = false;
    });
    try {
      final name = _name.text.trim();
      await ref
          .read(profileProvider.notifier)
          .save(
            ProfileUpdate(
              expectedRevision: ref
                  .read(profileProvider.notifier)
                  .bundle!
                  .revision!,
              regionCode: _region!,
              subjects: Subject.values.where(_subjects.contains).toList(),
              grade: _grade,
              examYear: _examYear,
              curriculumVersion: _curriculum,
              displayName: name.isEmpty ? null : name,
              learningSettings: _learningSettings,
            ),
          );
      if (mounted && serial == _editSerial) setState(() => _saved = true);
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
    final bundle = ref.read(profileProvider.notifier).bundle;
    final pending = bundle?.pending;
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
              title: '称呼',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  TextField(
                    key: const ValueKey('profile.displayName'),
                    controller: _name,
                    onChanged: (_) => _change(() {}),
                    inputFormatters: [LengthLimitingTextInputFormatter(40)],
                    decoration: const InputDecoration(labelText: '你的称呼（可以不填）'),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '只有你授权的家长看周报时会看到。起个名字就行，不用真名；留空表示不改。',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            const SizedBox(height: kGap),
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
                        _change(() => _region = s.isEmpty ? null : s.first),
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
                        onSelected: (_) => _change(() => _grade = null),
                      ),
                      for (final g in options.grades)
                        ChoiceChip(
                          key: ValueKey('profile.grade.${g.code.value}'),
                          label: Text(gradeName(g.code)),
                          selected: _grade == g.code,
                          onSelected: (_) => _change(() => _grade = g.code),
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
                          onSelected: (on) => _change(
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
                    onChanged: (v) => _change(() => _examYear = v),
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
                        onSelected: (_) => _change(() => _curriculum = null),
                      ),
                      for (final c in options.curriculumVersions)
                        ChoiceChip(
                          key: ValueKey('profile.curriculum.${c.code}'),
                          label: Text(c.name),
                          selected: _curriculum == c.code,
                          onSelected: (_) =>
                              _change(() => _curriculum = c.code),
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
            const Text('离线时使用本机上次保存的选项，可能已有变化；保存时会由服务端重新校验。'),
            if (bundle?.revision == null) ...[
              const Callout(
                tone: Tone.info,
                child: Text('这是旧版离线资料，版本尚未确认。可以继续编辑并保存在本机；联网读取云端资料后才能保存。'),
              ),
              OutlinedButton(
                key: const ValueKey('profile.refresh'),
                onPressed: () => ref.invalidate(profileProvider),
                child: const Text('联网读取资料'),
              ),
            ],
            if (pending == null && bundle?.editConflict == true) ...[
              const Callout(
                tone: Tone.info,
                child: Text('你编辑之后，云端资料已有变化。请比较双方并明确选择，刷新不会自动覆盖任何一方。'),
              ),
              Text('本机：${_summary(bundle!.edit!)}'),
              Text('云端：${_summary(bundle.cloud!.toJson())}'),
              OutlinedButton(
                key: const ValueKey('profile.useLocal'),
                onPressed: _saving ? null : () => _resolve(false),
                child: const Text('保留本机编辑，再次保存'),
              ),
              OutlinedButton(
                key: const ValueKey('profile.useCloud'),
                onPressed: _saving ? null : () => _resolve(true),
                child: const Text('采用云端资料'),
              ),
            ],
            if (pending != null) ...[
              Callout(
                tone: Tone.info,
                child: Text(
                  pending.phase == 'conflict'
                      ? '云端资料已变化。你的本机编辑仍保留，请比较双方后选择。'
                      : '有一笔尚未确认的资料保存。请重试原请求，确认结果。',
                ),
              ),
              if (pending.phase == 'conflict') ...[
                Text('本机：${_summary(bundle?.edit ?? pending.body.toJson())}'),
                Text('云端：${_summary(bundle!.cloud!.toJson())}'),
                OutlinedButton(
                  key: const ValueKey('profile.useLocal'),
                  onPressed: _saving ? null : () => _resolve(false),
                  child: const Text('保留本机编辑，再次保存'),
                ),
                OutlinedButton(
                  key: const ValueKey('profile.useCloud'),
                  onPressed: _saving ? null : () => _resolve(true),
                  child: const Text('采用云端资料'),
                ),
              ] else
                OutlinedButton(
                  key: const ValueKey('profile.retry'),
                  onPressed: _saving ? null : _recover,
                  child: const Text('重试原保存'),
                ),
            ],
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Callout(
                  tone: Tone.danger,
                  child: Text(describeError(_error!)),
                ),
              ),
            Section(
              title: '学习安排',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  DropdownButtonFormField<String>(
                    key: ValueKey('profile.learningMode.$_mode'),
                    initialValue: _mode,
                    decoration: const InputDecoration(labelText: '学习模式'),
                    items: [
                      for (final entry in _learningModes.entries)
                        DropdownMenuItem(
                          value: entry.key,
                          child: Text(entry.value),
                        ),
                    ],
                    onChanged: _saving
                        ? null
                        : (mode) => _change(() => _mode = mode),
                  ),
                  if (_mode != null) ...[
                    TextField(
                      controller: _minutes,
                      enabled: !_saving,
                      keyboardType: TextInputType.number,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      onChanged: (_) => _change(() {}),
                      decoration: InputDecoration(
                        labelText: '每周可用分钟',
                        helperText: '设为 0 时不额外安排题目',
                        errorText:
                            (_weeklyMinutes ?? -1) < 0 ||
                                (_weeklyMinutes ?? 0) > 10080
                            ? '请输入 0 至 10080'
                            : null,
                      ),
                    ),
                    Wrap(
                      spacing: 8,
                      children: [
                        for (var day = 1; day <= 7; day++)
                          FilterChip(
                            label: Text('周${'一二三四五六日'[day - 1]}'),
                            selected: _weekdays.contains(day),
                            onSelected: _saving
                                ? null
                                : (selected) => _change(() {
                                    if (selected) {
                                      _weekdays.add(day);
                                    } else {
                                      _weekdays.remove(day);
                                    }
                                  }),
                          ),
                      ],
                    ),
                    for (final (label, controller) in [
                      ('学校进度', _schoolProgress),
                      ('考试范围', _examScope),
                    ])
                      TextField(
                        controller: controller,
                        enabled: !_saving,
                        maxLength: 500,
                        onChanged: (_) => _change(() {}),
                        decoration: InputDecoration(labelText: label),
                      ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: kGap),
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
              onPressed:
                  _valid &&
                      !_saving &&
                      pending == null &&
                      bundle?.editConflict != true &&
                      bundle?.revision != null
                  ? _save
                  : null,
              child: _saving
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('保存'),
            ),
            const SizedBox(height: 28),
            if (userId != null)
              SchoolMaterialSection(
                key: ValueKey('school-material.$userId'),
                ownerId: userId,
              ),
            if (profile.learningSettings != null && userId != null)
              LearningPackSection(key: ValueKey(userId), ownerId: userId),
            const ParentAccessSection(),
            const SizedBox(height: kGap),
            Section(
              title: '隐私与数据',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '• 草稿和笔迹先保存在这台设备上，联网后才同步。\n'
                    '• 家长只能看到你授权的、汇总后的每周趋势，看不到你每一笔的草稿，你可以随时撤销授权。\n'
                    '• AI 给的是练习反馈，不是官方阅卷分数。\n'
                    '• 本机练习草稿可以在下方导出；云端完整数据导出和删除仍未开放。',
                  ),
                  const StudentDataExportSection(),
                  const StudentDataExportSection(server: true),
                  const StudentDataExportSection.scans(),
                  const StudentDataExportSection.media(),
                  const StudentDataExportSection.recovery(),
                  const SizedBox(height: 8),
                  Text(
                    '本机演示身份（原型阶段，不是真实账号）：${userId == null ? '—' : shortId(userId)}',
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
