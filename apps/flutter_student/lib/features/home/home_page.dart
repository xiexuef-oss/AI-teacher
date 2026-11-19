import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/adaptive_split.dart';
import '../../core/data.dart';
import '../../core/labels.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

/// P01 首页。学生只看到四个入口：开始今日学习、拍题、练习、我的。
class HomePage extends ConsumerWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      key: const ValueKey('home.page'),
      appBar: AppBar(
        title: const Text('今天学点什么'),
        actions: const [
          Padding(padding: EdgeInsets.only(right: 12), child: _ProfileChips()),
        ],
      ),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, box) {
            final wide = box.maxWidth >= kExpandedBreakpoint;
            final main = const _TodayColumn();
            final entries = _Entries(vertical: wide);
            if (wide) {
              // 两栏各自滚动：任务多、字体放大或出现提示横幅时，内容都不会溢出
              return Padding(
                padding: const EdgeInsets.all(kPad),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      flex: 3,
                      child: SingleChildScrollView(child: main),
                    ),
                    const SizedBox(width: kPad),
                    Expanded(
                      flex: 2,
                      child: SingleChildScrollView(child: entries),
                    ),
                  ],
                ),
              );
            }
            return ListView(
              padding: const EdgeInsets.all(kPad),
              children: [
                main,
                const SizedBox(height: kPad),
                entries,
              ],
            );
          },
        ),
      ),
    );
  }
}

class _ProfileChips extends ConsumerWidget {
  const _ProfileChips();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider).asData?.value;
    if (profile == null || profile.regionCode == null) {
      return const SizedBox.shrink();
    }
    return Wrap(
      spacing: 6,
      children: [
        InfoChip(regionName(profile.regionCode!), icon: Icons.place_outlined),
        if (profile.grade != null) InfoChip(gradeName(profile.grade!)),
        if (profile.examYear != null) InfoChip('${profile.examYear} 届'),
      ],
    );
  }
}

// ---------------------------------------------------------------- 今日学习

class _TodayColumn extends ConsumerWidget {
  const _TodayColumn();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(todayTasksProvider);
    return tasks.when(
      loading: () => const Section(
        child: SizedBox(height: 160, child: LoadingView(label: '正在安排今天的任务…')),
      ),
      error: (error, _) => Section(
        child: SizedBox(
          height: 220,
          child: ErrorView(
            error: error,
            onRetry: () => ref.invalidate(todayTasksProvider),
          ),
        ),
      ),
      data: (result) {
        final skipped =
            ref.watch(skippedTasksProvider(result.tasks.date)).asData?.value ??
            const <String>{};
        final visible = result.tasks.items
            .where((t) => !skipped.contains(t.id))
            .toList();
        final starters = visible
            .where((task) => task.kind == TaskKind.newTopic)
            .toList();
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (result.fromCache)
              const Padding(
                padding: EdgeInsets.only(bottom: kGap),
                child: Callout(
                  tone: Tone.info,
                  icon: Icons.offline_pin_outlined,
                  child: Text('没有网络：显示的是上次保存的任务。联网之后会自动更新。'),
                ),
              ),
            if (result.tasks.coldStart == true)
              Padding(
                padding: const EdgeInsets.only(bottom: kGap),
                child: Section(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '开始第一次练习',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        '还没有练习记录。先从基础题开始，或选择正在学的知识点。这里只帮助选题，不代表掌握度诊断。',
                      ),
                      Wrap(
                        spacing: 8,
                        children: [
                          if (starters.isNotEmpty)
                            TextButton(
                              onPressed: () =>
                                  startTask(context, starters.first),
                              child: const Text('先练一道基础题'),
                            ),
                          OutlinedButton(
                            onPressed: () => context.push('/practice'),
                            child: const Text('按知识点选题'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            _StartCard(
              tasks: visible,
              date: result.tasks.date,
              allSkipped: result.tasks.items.isNotEmpty && visible.isEmpty,
            ),
            const SizedBox(height: kGap),
            for (final task in visible)
              Padding(
                padding: const EdgeInsets.only(bottom: kGap),
                child: _TaskTile(task: task, date: result.tasks.date),
              ),
          ],
        );
      },
    );
  }
}

void startTask(BuildContext context, StudyTask task) {
  final origin = switch (task.kind) {
    TaskKind.reviewMistake || TaskKind.retest => 'review',
    TaskKind.variant => 'variant',
    _ => 'task',
  };
  context.push(
    solveRoute(
      task.questionId,
      origin: origin,
      reviewItemId: task.reviewItemId,
    ),
  );
}

class _StartCard extends StatelessWidget {
  const _StartCard({
    required this.tasks,
    required this.date,
    required this.allSkipped,
  });

  final List<StudyTask> tasks;
  final String date;
  final bool allSkipped;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final minutes = tasks.fold<int>(0, (sum, t) => sum + t.estimatedMinutes);
    final subtitle = tasks.isNotEmpty
        ? '今天有 ${tasks.length} 项任务，大约 $minutes 分钟。可以跳过不想做的。'
        : (allSkipped ? '今天的任务都跳过了。想多练一点，去“练习”里选题。' : '今天没有安排任务。去“练习”里选一道题吧。');
    return Material(
      color: scheme.primaryContainer,
      borderRadius: BorderRadius.circular(20),
      child: InkWell(
        key: const ValueKey('home.start'),
        borderRadius: BorderRadius.circular(20),
        onTap: tasks.isNotEmpty
            ? () => startTask(context, tasks.first)
            : () => context.push('/practice'),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              Icon(Icons.play_circle_fill, size: 56, color: scheme.primary),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '开始今日学习',
                      style: theme.textTheme.headlineSmall?.copyWith(
                        color: scheme.onPrimaryContainer,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      subtitle,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: scheme.onPrimaryContainer,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: scheme.onPrimaryContainer),
            ],
          ),
        ),
      ),
    );
  }
}

class _TaskTile extends ConsumerWidget {
  const _TaskTile({required this.task, required this.date});

  final StudyTask task;
  final String date;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Section(
      key: ValueKey('task.${task.id}'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              InfoChip(
                taskKindName(task.kind),
                icon: switch (task.kind) {
                  TaskKind.reviewMistake ||
                  TaskKind.retest => Icons.event_repeat,
                  TaskKind.weakPoint => Icons.flag_outlined,
                  TaskKind.variant => Icons.shuffle,
                  _ => Icons.fiber_new_outlined,
                },
                tone: task.kind == TaskKind.newTopic ? Tone.neutral : Tone.info,
              ),
              InfoChip(subjectName(task.subject)),
              InfoChip(
                '约 ${task.estimatedMinutes} 分钟',
                icon: Icons.timer_outlined,
              ),
              InfoChip(task.applicability.label, icon: Icons.place_outlined),
            ],
          ),
          const SizedBox(height: 10),
          Text(task.title, style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(task.reason, style: theme.textTheme.bodyMedium),
          const SizedBox(height: 12),
          Row(
            children: [
              FilledButton(
                key: ValueKey('task.start.${task.id}'),
                onPressed: () => startTask(context, task),
                child: const Text('开始'),
              ),
              const SizedBox(width: 8),
              TextButton(
                key: ValueKey('task.skip.${task.id}'),
                onPressed: () =>
                    ref.read(skippedTasksStoreProvider).skip(date, task.id),
                child: const Text('今天跳过'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- 其他入口

class _Entries extends StatelessWidget {
  const _Entries({required this.vertical});

  final bool vertical;

  @override
  Widget build(BuildContext context) {
    final tiles = [
      _EntryTile(
        key: const ValueKey('home.diagnostic'),
        icon: Icons.checklist_outlined,
        title: '三题摸底',
        subtitle: '做三道题，退出后可以继续',
        onTap: () => context.push('/diagnostic'),
      ),
      _EntryTile(
        key: const ValueKey('home.scan'),
        icon: Icons.photo_camera_outlined,
        title: '拍题',
        subtitle: '拍一道不会的题',
        onTap: () => context.push('/scan'),
      ),
      _EntryTile(
        key: const ValueKey('home.practice'),
        icon: Icons.edit_note,
        title: '练习',
        subtitle: '按科目、题型选题；错题复习在这里',
        onTap: () => context.push('/practice'),
      ),
      _EntryTile(
        key: const ValueKey('home.profile'),
        icon: Icons.person_outline,
        title: '我的',
        subtitle: '年级、地区、学情和隐私',
        onTap: () => context.push('/profile'),
      ),
    ];
    if (vertical) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final t in tiles)
            Padding(
              padding: const EdgeInsets.only(bottom: kGap),
              child: t,
            ),
        ],
      );
    }
    return LayoutBuilder(
      builder: (context, box) {
        // 手机宽度：一行一个、铺满；平板竖屏这样的中等宽度：每个 220 宽，放得下就并排
        final tileWidth = box.maxWidth < 480 ? box.maxWidth : 220.0;
        return Wrap(
          spacing: kGap,
          runSpacing: kGap,
          children: [
            for (final t in tiles) SizedBox(width: tileWidth, child: t),
          ],
        );
      },
    );
  }
}

class _EntryTile extends StatelessWidget {
  const _EntryTile({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 96),
          child: Padding(
            padding: const EdgeInsets.all(kPad),
            child: Row(
              children: [
                Icon(icon, size: 36, color: theme.colorScheme.primary),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(title, style: theme.textTheme.titleLarge),
                      Text(subtitle, style: theme.textTheme.bodySmall),
                    ],
                  ),
                ),
                const Icon(Icons.chevron_right),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
