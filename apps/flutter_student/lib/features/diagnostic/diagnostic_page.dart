import 'dart:convert';
import 'dart:typed_data';

import 'package:file_saver/file_saver.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/errors.dart';
import '../../core/file_export.dart';
import '../../core/labels.dart';
import '../../core/math_text.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import 'diagnostic_actions.dart';
import 'diagnostic_store.dart';

class DiagnosticPage extends ConsumerStatefulWidget {
  const DiagnosticPage({super.key});
  @override
  ConsumerState<DiagnosticPage> createState() => _DiagnosticPageState();
}

class _DiagnosticPageState extends ConsumerState<DiagnosticPage> {
  Subject? _subject;
  bool _exporting = false;

  Future<void> _export() async {
    final owner = ref.read(authProvider).asData?.value;
    if (_exporting || owner == null || owner.role != LocalRole.student) return;
    setState(() => _exporting = true);
    try {
      final snapshot = await DiagnosticStore(
        ref.read(keyValueStoreProvider),
        owner.userId,
      ).exportSnapshot();
      snapshot['exported_at'] = ref
          .read(clockProvider)()
          .toUtc()
          .toIso8601String();
      final bytes = Uint8List.fromList(utf8.encode(jsonEncode(snapshot)));
      if (!mounted || !identical(owner, ref.read(authProvider).asData?.value)) {
        return;
      }
      final result = await saveDataFile(
        bytes,
        name: 'diagnostic-records-${DateTime.now().microsecondsSinceEpoch}',
        extension: 'json',
        mimeType: MimeType.json,
      );
      if (mounted && identical(owner, ref.read(authProvider).asData?.value)) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(result)));
      }
    } catch (_) {
      if (mounted && identical(owner, ref.read(authProvider).asData?.value)) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('摸底记录导出失败，原记录未改动。')));
      }
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Future<bool> _confirm(String title, String message) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(title),
          content: Text(message),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('返回'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('确认'),
            ),
          ],
        ),
      ) ??
      false;

  Future<void> _perform(Future<StudySession?> Function() action) async {
    if (!mounted) return;
    final auth = ref.read(authProvider).asData?.value;
    try {
      final session = await action();
      if (!mounted ||
          !identical(auth, ref.read(authProvider).asData?.value) ||
          session == null) {
        return;
      }
      await _solve(session.questionId, session.id);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(describeError(error))));
      }
    }
  }

  Future<void> _solve(String questionId, String sessionId) async {
    final auth = ref.read(authProvider).asData?.value;
    await context.push(
      Uri(
        path: '/questions/$questionId/solve',
        queryParameters: {'session': sessionId, 'origin': 'practice'},
      ).toString(),
    );
    if (mounted && identical(auth, ref.read(authProvider).asData?.value)) {
      await ref.read(diagnosticActionsProvider.notifier).refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    final value = ref.watch(diagnosticActionsProvider);
    final profile = ref.watch(profileProvider).asData?.value;
    final actions = ref.read(diagnosticActionsProvider.notifier);
    return Scaffold(
      key: const ValueKey('diagnostic.page'),
      appBar: AppBar(
        title: const Text('三题摸底'),
        actions: [
          IconButton(
            tooltip: '历史摸底',
            onPressed: () => context.push('/diagnostic/history'),
            icon: const Icon(Icons.history),
          ),
          IconButton(
            key: const ValueKey('diagnostic.export'),
            tooltip: '导出本机摸底记录',
            onPressed: _exporting ? null : _export,
            icon: const Icon(Icons.download_outlined),
          ),
          IconButton(
            tooltip: '刷新摸底进度',
            onPressed: value.asData?.value.busy == true
                ? null
                : actions.refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: value.when(
          loading: () => const LoadingView(),
          error: (error, _) => ErrorView(
            error: error,
            onRetry: () => ref.invalidate(diagnosticActionsProvider),
          ),
          data: (view) {
            final run = view.bundle.cloud?.run;
            final pending = view.bundle.pending;
            final subjects = (profile?.subjects ?? const <Subject>[])
                .where((s) => s != Subject.$unknown)
                .toList();
            final selected = subjects.contains(_subject)
                ? _subject
                : subjects.firstOrNull;
            return Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 900),
                child: ListView(
                  padding: const EdgeInsets.all(kPad),
                  children: [
                    const Text('用三道客观题了解本轮练习情况。可以中途退出，稍后继续；草稿和笔迹仍先保存在这台设备。'),
                    const SizedBox(height: kGap),
                    const Text('只展示本轮计数，不推算掌握度或分数。自编工程样题未经过学科审校。'),
                    const Text(
                      '顶部导出可保存本机摸底进度和恢复记录；作答和笔迹请在“我的”导出。JSON暂不支持导入应用。',
                    ),
                    if (!view.fresh) ...[
                      const SizedBox(height: kGap),
                      const Text('当前显示本机记录，尚未确认最新进度。已有会话可以继续；开始新题前请刷新。'),
                    ],
                    if (view.problem != null)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: kGap),
                        child: Text(
                          describeError(view.problem!),
                          key: const ValueKey('diagnostic.error'),
                        ),
                      ),
                    if (pending != null)
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(kPad),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                pending.phase == 'result_known'
                                    ? '已收到原操作结果，等待刷新确认'
                                    : '上次操作结果尚未确认，原操作已保存在本机',
                              ),
                              Wrap(
                                spacing: kGap,
                                children: [
                                  FilledButton(
                                    key: const ValueKey('diagnostic.resume'),
                                    onPressed: view.busy
                                        ? null
                                        : () => _perform(actions.resume),
                                    child: Text(
                                      pending.phase == 'result_known'
                                          ? '确认并刷新进度'
                                          : '重试原操作',
                                    ),
                                  ),
                                  if (pending.phase == 'prepared')
                                    TextButton(
                                      key: const ValueKey('diagnostic.stop'),
                                      onPressed: view.busy
                                          ? null
                                          : () async {
                                              if (await _confirm(
                                                '停止重试原操作？',
                                                '这只停止本机重试，不会取消已经发送的操作。原记录会保留，请刷新进度后再决定下一步。',
                                              )) {
                                                await _perform(() async {
                                                  await actions.stopRetrying();
                                                  return null;
                                                });
                                              }
                                            },
                                      child: const Text('停止重试'),
                                    ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                    if (run != null) ...[
                      const SizedBox(height: kGap),
                      Text(
                        '${subjectName(run.subject)} · ${run.status == 'completed'
                            ? '本轮已完成'
                            : run.status == 'abandoned'
                            ? '本轮已结束'
                            : '已提交 ${run.summary.submitted}/3 题'}',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      Text(
                        '按本轮开始时的资料选题；年级 ${run.scope.grade == null ? '暂不清楚' : gradeName(run.scope.grade!)}，地区 ${regionName(run.scope.regionCode)}。',
                      ),
                      for (final item in run.items)
                        Card(
                          child: Padding(
                            padding: const EdgeInsets.all(kPad),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                MathText(
                                  '${item.position}. ${item.question.title}',
                                ),
                                Text(
                                  '${item.question.source.label} · ${answerModeName(item.question.answerMode)} · ${item.question.applicability.label}',
                                ),
                                if (item.submission != null)
                                  Text(
                                    item.submission!.evaluationState ==
                                                EvaluationState.uncertain ||
                                            item.submission!.isCorrect == null
                                        ? '已提交 · 未确认'
                                        : !item.submission!.independent
                                        ? '已提交 · 借助提示'
                                        : item.submission!.isCorrect!
                                        ? '已提交 · 独立正确'
                                        : '已提交 · 独立不正确',
                                  ),
                                Align(
                                  alignment: Alignment.centerRight,
                                  child: FilledButton(
                                    key: ValueKey(
                                      'diagnostic.open.${item.position}',
                                    ),
                                    onPressed:
                                        view.busy ||
                                            pending != null ||
                                            (item.sessionId == null &&
                                                (!view.fresh ||
                                                    run.status == 'abandoned'))
                                        ? null
                                        : () {
                                            if (item.sessionId != null) {
                                              _perform(() async {
                                                await _solve(
                                                  item.question.id,
                                                  item.sessionId!,
                                                );
                                                return null;
                                              });
                                            } else {
                                              _perform(
                                                () => actions.open(
                                                  run.id,
                                                  item.position,
                                                ),
                                              );
                                            }
                                          },
                                    child: Text(
                                      item.submission != null
                                          ? '回看作答'
                                          : item.sessionId != null
                                          ? '继续作答'
                                          : '开始作答',
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      if (run.summary.submitted > 0)
                        Text(
                          '本轮已提交 ${run.summary.submitted} 题：独立正确 ${run.summary.independentCorrect}，独立不正确 ${run.summary.independentIncorrect}，借助提示 ${run.summary.assisted}，未确认 ${run.summary.unconfirmed}。仅统计每题本轮首份提交，重答不会替换。',
                        ),
                      if (run.status == 'active')
                        TextButton(
                          key: const ValueKey('diagnostic.abandon'),
                          onPressed: view.busy || pending != null || !view.fresh
                              ? null
                              : () async {
                                  if (await _confirm(
                                    '结束本轮摸底？',
                                    '已经写下的草稿、笔迹和提交记录会保留。结束后可以重新开始。',
                                  )) {
                                    await _perform(
                                      () => actions.abandon(run.id),
                                    );
                                  }
                                },
                          child: const Text('结束本轮，保留记录'),
                        ),
                    ],
                    if (run?.status != 'active') ...[
                      const SizedBox(height: kGap),
                      Text(
                        '选择本轮学科',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Wrap(
                        spacing: kGap,
                        children: [
                          for (final subject in subjects)
                            ChoiceChip(
                              key: ValueKey(
                                'diagnostic.subject.${subject.toJson()}',
                              ),
                              label: Text(subjectName(subject)),
                              selected: selected == subject,
                              onSelected: view.busy || pending != null
                                  ? null
                                  : (_) => setState(() => _subject = subject),
                            ),
                        ],
                      ),
                      if (subjects.isEmpty)
                        TextButton(
                          onPressed: () => context.push('/profile'),
                          child: const Text('先设置学习资料'),
                        ),
                      FilledButton(
                        key: const ValueKey('diagnostic.create'),
                        onPressed:
                            selected == null ||
                                !view.fresh ||
                                view.busy ||
                                pending != null
                            ? null
                            : () => _perform(() => actions.create(selected)),
                        child: const Text('开始三题摸底'),
                      ),
                    ],
                    if (view.busy)
                      const Padding(
                        padding: EdgeInsets.all(kGap),
                        child: LinearProgressIndicator(),
                      ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}
