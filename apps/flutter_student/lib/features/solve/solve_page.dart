import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/adaptive_split.dart';
import '../../core/data.dart';
import '../../core/errors.dart';
import '../../core/labels.dart';
import '../../core/math_text.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import 'answer_input.dart';
import 'experiment_input.dart';
import 'proof_input.dart';
import 'question_attachments.dart';
import 'ink/ink_canvas.dart';
import 'ink/ink_controller.dart';
import 'draft_store.dart';
import 'self_check_card.dart';
import 'solve_controller.dart';
import 'tutor_panel.dart';

/// P03 统一作答页：左边题目与辅导，右边草稿画布，底部固定操作栏。
class SolvePage extends ConsumerStatefulWidget {
  const SolvePage({super.key, required this.args});

  final SolveArgs args;

  @override
  ConsumerState<SolvePage> createState() => _SolvePageState();
}

class _SolvePageState extends ConsumerState<SolvePage>
    with WidgetsBindingObserver {
  late final SolveController _controller;
  final ScrollController _scroll = ScrollController();
  final GlobalKey _selfCheckKey = GlobalKey();
  int _eventCount = 0;
  bool _selfCheckRevealed = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final owner = ref.read(userIdProvider)!;
    _controller = SolveController(
      api: ref.read(apiClientProvider),
      store: ref.read(keyValueStoreProvider),
      userId: owner,
      isCurrentUser: () => mounted && ref.read(userIdProvider) == owner,
      args: widget.args,
    );
    _controller.addListener(_onControllerChanged);
    unawaited(_controller.start());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 切到后台、被系统回收之前：立刻存到本机，不等定时器
    if (state != AppLifecycleState.resumed) unawaited(_controller.flushNow());
  }

  void _onControllerChanged() {
    final count = _controller.events.length;
    if (count > _eventCount) {
      _eventCount = count;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || !_scroll.hasClients) return;
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      });
    }
    final cardShown =
        _controller.phase == SolvePhase.submitted &&
        isSubjectiveMode(_controller.question?.answerMode) &&
        !_controller.selfCheckBusy &&
        (_controller.selfCheck != null || _controller.selfCheckError != null);
    if (cardShown && !_selfCheckRevealed) {
      _selfCheckRevealed = true;
      _revealSelfCheck();
    } else if (_controller.phase == SolvePhase.answering) {
      _selfCheckRevealed = false;
    }
    if (_controller.phase == SolvePhase.submitted) {
      ref.invalidate(todayTasksProvider);
      ref.invalidate(reviewsProvider);
      ref.invalidate(progressProvider);
    }
  }

  /// 解答题、实验题提交之后，把自查要点的顶部带到眼前（默认的"滚到最新一条"会停在要点下方）。
  /// 列表是按需建出来的：先跳到末尾，让这张卡片建出来，再把它的顶部对齐到视口顶部。
  void _revealSelfCheck() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.jumpTo(_scroll.position.maxScrollExtent);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final target = _selfCheckKey.currentContext;
        if (!mounted || target == null) return;
        Scrollable.ensureVisible(
          target,
          alignment: 0,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      });
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller.removeListener(_onControllerChanged);
    _scroll.dispose();
    // 先把草稿存到本机，再释放
    final controller = _controller;
    unawaited(controller.flushNow().whenComplete(controller.dispose));
    super.dispose();
  }

  // ------------------------------------------------------------ 动作

  Future<void> _openLatestWorkspace() async {
    await _controller.openLatestWorkspace();
    if (!mounted || !_controller.hasOpenedNewWorkspace) return;
    _eventCount = _controller.events.length;
    _selfCheckRevealed = false;
    // The explicit route selected the old draft. Once the student opens a new
    // workspace, refresh must use its persisted active/local workspace instead.
    if (widget.args.sessionId != null || widget.args.attemptId != null) {
      GoRouter.maybeOf(context)?.replace(
        solveRoute(
          widget.args.questionId,
          origin: widget.args.origin,
          reviewItemId: widget.args.reviewItemId,
          parentSessionId: widget.args.parentSessionId,
        ),
      );
    }
  }

  Future<void> _tutor(TutorActionType action) async {
    var outcome = await _controller.tutor(action);
    if (outcome == TutorOutcome.needsConfirmation && mounted) {
      final ok = await _confirmGiveUp();
      if (ok != true) return;
      outcome = await _controller.tutor(action, confirmEndIndependent: true);
    }
  }

  Future<bool?> _confirmGiveUp() {
    return showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('现在就看解析吗？'),
        content: const Text(
          '你还没有提交答案。看了解析，这一次就不再算“独立作答”了，之后会安排一次不看提示的复测来检验。\n\n'
          '想再试一试，可以先点“给点提示”。',
        ),
        actions: [
          TextButton(
            key: const ValueKey('dialog.giveUp.cancel'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('我再想想'),
          ),
          FilledButton(
            key: const ValueKey('dialog.giveUp.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('看解析'),
          ),
        ],
      ),
    );
  }

  Future<void> _onSuggestion(SuggestedAction suggestion) async {
    switch (suggestion.action) {
      case 'request_hint':
        await _tutor(TutorActionType.requestHint);
      case 'request_standard':
        await _tutor(TutorActionType.requestStandard);
      case 'request_fast':
        await _tutor(TutorActionType.requestFast);
      case 'request_visual':
        await _tutor(TutorActionType.requestVisual);
      case 'retry_attempt':
        await _controller.retry();
      case 'finish':
        await _tutor(TutorActionType.markUnderstood);
      case 'pause':
        if (mounted) context.pop();
      case 'start_variant':
        final id = suggestion.questionId;
        if (id != null && mounted) {
          context.pushReplacement(
            solveRoute(
              id,
              origin: 'variant',
              parentSessionId: _controller.session?.id,
            ),
          );
        }
      case 'review_prerequisite':
        if (!mounted) return;
        await showDialog<void>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('先补一补前置知识'),
            content: Text(
              '${suggestion.label}\n\n已经记下来了。针对前置知识的专项练习还在准备中，现在可以先去“练习”选同一学科的基础题。',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('知道了'),
              ),
              FilledButton(
                onPressed: () {
                  Navigator.pop(context);
                  context.push('/practice');
                },
                child: const Text('去练习'),
              ),
            ],
          ),
        );
    }
  }

  // ------------------------------------------------------------ 界面

  @override
  Widget build(BuildContext context) {
    if (ref.watch(userIdProvider) != _controller.userId) {
      return Scaffold(
        body: EmptyView(
          title: '账号已变更',
          message: '旧草稿保留在原账号的本机空间，请返回首页继续。',
          action: TextButton(
            onPressed: () => context.go('/home'),
            child: const Text('回首页'),
          ),
        ),
      );
    }
    return ListenableBuilder(
      listenable: _controller,
      builder: (context, _) {
        final c = _controller;
        return Scaffold(
          key: const ValueKey('solve.page'),
          appBar: AppBar(
            // 返回键放在 _Title 里：它在没有上一页时会回到首页，AppBar 自带的那个做不到
            automaticallyImplyLeading: false,
            titleSpacing: 0,
            title: _Title(controller: c),
            actions: [
              TextButton(
                key: const ValueKey('workspace.archives'),
                onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => _LocalWorkspaceDialog(controller: c),
                ),
                child: const Text('本机旧稿'),
              ),
              if (c.phase == SolvePhase.answering ||
                  c.phase == SolvePhase.submitted)
                Padding(
                  padding: const EdgeInsets.only(right: 12),
                  child: _SaveChip(controller: c),
                ),
            ],
          ),
          body: switch (c.phase) {
            SolvePhase.loading => const LoadingView(label: '正在准备题目…'),
            SolvePhase.failed => Column(
              children: [
                Expanded(
                  child: ErrorView(
                    error: c.failure!,
                    onRetry: () => unawaited(c.start()),
                  ),
                ),
                if (c.creationBlockedReason != null)
                  TextButton(
                    onPressed: () => unawaited(_openLatestWorkspace()),
                    child: const Text('保留旧稿，另开新版'),
                  ),
              ],
            ),
            _ => _body(context, c),
          },
        );
      },
    );
  }

  Widget _body(BuildContext context, SolveController c) {
    return SafeArea(
      child: Column(
        children: [
          if (c.phase == SolvePhase.readonly)
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text('当前本机输入已保留为未提交内容。下方教学记录属于服务器原作答；本机输入不据此判定。'),
            ),
          if (c.needsTutorRecovery)
            MaterialBanner(
              content: const Text('上次辅导动作尚未确认，请明确恢复。'),
              actions: [
                TextButton(
                  key: const ValueKey('action.recoverTutor'),
                  onPressed: c.tutorBusy
                      ? null
                      : () => unawaited(c.recoverTutor()),
                  child: const Text('恢复原辅导动作'),
                ),
              ],
            ),
          if (c.canRecordSubmittedReview && c.reviewCompletion == null)
            TextButton(
              key: const ValueKey('action.recordSubmittedReview'),
              onPressed: () async {
                final confirmed = await showDialog<bool>(
                  context: context,
                  builder: (context) => AlertDialog(
                    title: const Text('记录已提交复测'),
                    content: const Text('确认记录此会话已经提交的首次复测作答？当前草稿会保留。'),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(context, false),
                        child: const Text('取消'),
                      ),
                      FilledButton(
                        onPressed: () => Navigator.pop(context, true),
                        child: const Text('确认记录'),
                      ),
                    ],
                  ),
                );
                if (confirmed == true) {
                  await c.recordSubmittedReview(explicitConfirmation: true);
                }
              },
              child: const Text('记录已提交复测'),
            ),
          if (c.needsReviewRecovery)
            MaterialBanner(
              content: const Text('上次复测记录尚未确认，当前阶段以最新状态为准。'),
              actions: [
                TextButton(
                  key: const ValueKey('action.recoverReview'),
                  onPressed: c.tutorBusy || c.needsSubmissionRecovery
                      ? null
                      : () => unawaited(c.recoverReviewCompletion()),
                  child: const Text('恢复复测记录'),
                ),
              ],
            ),
          if (c.historicalReviewCompletion != null)
            Text(
              '原复测记录结果：${c.historicalReviewCompletion!.result == ReviewResult.passed ? '已通过' : '未通过'}',
            ),
          if (c.reviewState != null)
            Text(
              '当前复测阶段：${c.reviewState!.stage}/${c.reviewState!.totalStages}',
            ),
          if (c.selfCheckRemoteConflict)
            MaterialBanner(
              content: Text(
                '云端自查与上次确认的内容不同。云端：${c.selfCheck!.marks.map((m) => '${m.pointKey} ${m.level.toJson()}').join('；')}。本机勾选仍保留，请选择。',
              ),
              actions: [
                TextButton(
                  onPressed: () => unawaited(c.chooseRemoteSelfCheck()),
                  child: const Text('使用云端自查'),
                ),
                TextButton(
                  onPressed: () => unawaited(c.keepLocalSelfCheck()),
                  child: const Text('保存本机自查'),
                ),
              ],
            ),
          if (c.needsSubmissionRecovery)
            MaterialBanner(
              content: const Text('原提交结果尚未确认。当前修改保留在本机；恢复会重放原提交。'),
              actions: [
                TextButton(
                  key: const ValueKey('action.recoverSubmission'),
                  onPressed: c.submitting
                      ? null
                      : () => unawaited(c.recoverOriginalSubmission()),
                  child: const Text('恢复原提交，当前修改保留'),
                ),
              ],
            ),
          for (final continuation in c.continuations)
            ListTile(
              title: const Text('未提交续稿（与上次提交分别保存）'),
              trailing: TextButton(
                key: ValueKey('continuation.view.${continuation.id}'),
                onPressed: () => unawaited(
                  showDialog<void>(
                    context: context,
                    builder: (context) => _ContinuationDialog(
                      draft: continuation.draft,
                      canContinue:
                          c.phase == SolvePhase.submitted &&
                          !c.isFinished &&
                          !c.submitting,
                      onContinue: () {
                        Navigator.pop(context);
                        unawaited(c.continueDraft(continuation.id));
                      },
                    ),
                  ),
                ),
                child: const Text('查看与继续续稿'),
              ),
            ),
          _Banners(
            controller: c,
            onRelogin: _relogin,
            onOpenLatest: _openLatestWorkspace,
          ),
          Expanded(
            child: AdaptiveSplit(
              primary: _QuestionPane(
                controller: c,
                scroll: _scroll,
                selfCheckKey: _selfCheckKey,
                onSuggestion: _onSuggestion,
              ),
              secondary: Padding(
                padding: const EdgeInsets.all(8),
                child: ClipRRect(
                  key: const ValueKey('solve.scratchPane'),
                  borderRadius: BorderRadius.circular(16),
                  child: InkCanvas(
                    key: ValueKey(
                      'solve.ink.${c.phase == SolvePhase.answering ? 'write' : 'read'}',
                    ),
                    controller: c.ink,
                    readOnly:
                        c.phase != SolvePhase.answering ||
                        !c.hasVerifiedWorkspace,
                  ),
                ),
              ),
            ),
          ),
          _ActionBar(
            controller: c,
            onTutor: _tutor,
            onConfirmGiveUp: () async {
              final ok = await _confirmGiveUp();
              if (ok == true) {
                await _controller.tutor(
                  TutorActionType.requestStandard,
                  confirmEndIndependent: true,
                );
              }
            },
          ),
        ],
      ),
    );
  }

  Future<void> _relogin() async {
    await ref.read(authProvider.notifier).relogin();
    if (mounted) context.go('/');
  }
}

// ---------------------------------------------------------------- 标题与保存状态

class _Title extends StatelessWidget {
  const _Title({required this.controller});

  final SolveController controller;

  @override
  Widget build(BuildContext context) {
    final q = controller.question;
    final theme = Theme.of(context);
    return Row(
      children: [
        BackButton(
          onPressed: () =>
              context.canPop() ? context.pop() : context.go('/home'),
        ),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                q?.title ?? '作答',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.titleMedium,
              ),
              if (q != null)
                Text(
                  '${subjectName(q.subject)} · ${answerModeName(q.answerMode)} · 难度 ${q.difficulty}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall,
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _SaveChip extends StatelessWidget {
  const _SaveChip({required this.controller});

  final SolveController controller;

  @override
  Widget build(BuildContext context) {
    final (String label, IconData icon, Tone tone) = switch (controller.sync) {
      SaveStatus.saved => (
        '已保存 · 已同步',
        Icons.cloud_done_outlined,
        Tone.success,
      ),
      SaveStatus.dirty => ('正在保存…', Icons.edit_note, Tone.neutral),
      SaveStatus.saving => ('同步中…', Icons.sync, Tone.neutral),
      SaveStatus.offline => (
        '已存在本机 · 未同步',
        Icons.cloud_off_outlined,
        Tone.warning,
      ),
      SaveStatus.conflict => (
        '草稿有冲突',
        Icons.sync_problem_outlined,
        Tone.danger,
      ),
    };
    return Semantics(
      liveRegion: true,
      label: '草稿状态：$label',
      child: ExcludeSemantics(
        child: KeyedSubtree(
          key: const ValueKey('solve.saveStatus'),
          child: InfoChip(label, icon: icon, tone: tone),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- 横幅

class _Banners extends StatelessWidget {
  const _Banners({
    required this.controller,
    required this.onRelogin,
    required this.onOpenLatest,
  });

  final SolveController controller;
  final Future<void> Function() onRelogin;
  final Future<void> Function() onOpenLatest;

  String _summary(AnswerPayload? answer, StrokeDoc? strokes) {
    final parts = <String>[];
    if (answer?.selectedOptions != null &&
        answer!.selectedOptions!.isNotEmpty) {
      parts.add('选了 ${answer.selectedOptions!.join('、')}');
    }
    if (answer?.blanks != null && answer!.blanks!.isNotEmpty) {
      parts.add('填了 ${answer.blanks!.map((b) => b.value).join('；')}');
    }
    final written = answer?.parts
        ?.where((p) => p.text.trim().isNotEmpty)
        .length;
    if (written != null && written > 0) parts.add('写了 $written 问');
    final cells = answer?.cells?.where((c) => c.value.trim().isNotEmpty).length;
    if (cells != null && cells > 0) parts.add('填了 $cells 个格子');
    final count =
        strokes?.pages.fold<int>(0, (sum, p) => sum + p.strokes.length) ?? 0;
    parts.add(count == 0 ? '没有笔迹' : '笔迹 $count 笔');
    return parts.join('，');
  }

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final banners = <Widget>[];
    if (c.selectableCopy != null) {
      banners.add(
        Callout(
          tone: Tone.info,
          child: OutlinedButton(
            key: const ValueKey('copy.openCreated'),
            onPressed: c.recoveryBusy
                ? null
                : () => unawaited(c.openCreatedCopy()),
            child: const Text('打开已创建的副本'),
          ),
        ),
      );
    }

    if (c.creationBlockedReason != null) {
      banners.add(
        Callout(
          tone: Tone.warning,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                c.hasVerifiedWorkspace
                    ? '创建已暂停：${c.creationBlockedReason}。原题面与草稿保留，不会自动转到新版。'
                    : '创建已暂停：${c.creationBlockedReason}。草稿原文保留；缓存题面不能证明旧稿的来源版本。',
              ),
              OutlinedButton(
                key: const ValueKey('creation.openLatest'),
                onPressed: () => unawaited(onOpenLatest()),
                child: const Text('保留旧稿，另开新版'),
              ),
              if (c.canResumeCreation)
                OutlinedButton(
                  onPressed: () => unawaited(c.resumeAuthenticatedCreation()),
                  child: const Text('同一账号恢复后重试'),
                ),
            ],
          ),
        ),
      );
    }

    if (c.authExpired) {
      banners.add(
        Callout(
          tone: Tone.danger,
          child: Row(
            children: [
              const Expanded(child: Text('登录已经失效。没有同步的草稿还保存在这台设备上，重新登录后不会丢。')),
              const SizedBox(width: 8),
              FilledButton(
                key: const ValueKey('banner.relogin'),
                onPressed: onRelogin,
                child: const Text('重新登录'),
              ),
            ],
          ),
        ),
      );
    }
    if (c.sync == SaveStatus.conflict && c.conflictServerDraft != null) {
      final server = c.conflictServerDraft!;
      final local = c.ink.hasInk ? c.ink.toContract() : null;
      banners.add(
        Callout(
          tone: Tone.danger,
          icon: Icons.sync_problem_outlined,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '这份草稿在别处有了更新',
                style: Theme.of(context).textTheme.titleSmall,
              ),
              const SizedBox(height: 4),
              Text('你这边：${_summary(_localAnswer(c), local)}'),
              Text('云端的：${_summary(server.answer, server.strokes)}'),
              const SizedBox(height: 4),
              const Text('两份都还在，没有被覆盖。选一份继续：'),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  FilledButton(
                    key: const ValueKey('banner.keepLocal'),
                    onPressed: c.recoveryBusy
                        ? null
                        : () => unawaited(c.resolveConflictKeepLocal()),
                    child: const Text('保留我的'),
                  ),
                  OutlinedButton(
                    key: const ValueKey('banner.useServer'),
                    onPressed: c.recoveryBusy
                        ? null
                        : () => unawaited(c.resolveConflictUseServer()),
                    child: const Text('用云端的'),
                  ),
                  OutlinedButton(
                    key: const ValueKey('banner.createCopy'),
                    onPressed: c.recoveryBusy
                        ? null
                        : () => unawaited(c.resolveConflictCreateCopy()),
                    child: const Text('创建独立云端副本'),
                  ),
                ],
              ),
            ],
          ),
        ),
      );
    } else if (c.sync == SaveStatus.offline) {
      banners.add(
        Callout(
          tone: Tone.warning,
          icon: Icons.cloud_off_outlined,
          child: Row(
            children: [
              const Expanded(child: Text('网络不通。你写的内容先保存在这台设备上，网络恢复后会自动同步。')),
              const SizedBox(width: 8),
              OutlinedButton(
                key: const ValueKey('banner.retry'),
                onPressed: () => unawaited(c.retryNow()),
                child: const Text('立即重试'),
              ),
            ],
          ),
        ),
      );
    }
    if (c.questionFromCache && c.sync == SaveStatus.offline) {
      banners.add(
        const Callout(
          tone: Tone.info,
          icon: Icons.offline_pin_outlined,
          child: Text('没有网络：显示的是上次保存的题目。云端提示和判分要联网后才能用。'),
        ),
      );
    }
    if (c.recoveryCopies.isNotEmpty && c.phase == SolvePhase.answering) {
      banners.add(
        Callout(
          tone: Tone.info,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('本机留档副本（仅保存在这台设备，不是新的云端作答）。恢复前会保留当前内容。'),
              DropdownButton<int>(
                key: const ValueKey('banner.restoreCopy'),
                isExpanded: true,
                hint: Text('查看并恢复 ${c.recoveryCopies.length} 份本机副本'),
                items: [
                  for (var i = 0; i < c.recoveryCopies.length; i++)
                    DropdownMenuItem(
                      value: i,
                      child: Text(
                        '${i + 1} · ${c.recoveryCopies[i].savedAt.toLocal()} · ${c.recoveryCopies[i].hasContent ? "有作答或笔迹" : "空稿"}',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: c.recoveryBusy
                    ? null
                    : (index) {
                        if (index != null) unawaited(c.restoreCopy(index));
                      },
              ),
            ],
          ),
        ),
      );
    }
    if (c.localSaveFailed) {
      banners.add(
        const Callout(
          tone: Tone.danger,
          child: Text('这台设备保存草稿失败（可能是存储空间不够）。先不要关闭应用，可以点草稿工具栏里的“导出为图片”留一份。'),
        ),
      );
    }
    if (c.actionError != null && !c.authExpired) {
      banners.add(
        Callout(tone: Tone.warning, child: Text(describeError(c.actionError!))),
      );
    }
    if (banners.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 0),
      child: Column(
        children: [
          for (final b in banners)
            Padding(padding: const EdgeInsets.only(bottom: 6), child: b),
        ],
      ),
    );
  }

  AnswerPayload? _localAnswer(SolveController c) {
    if (c.selected.isNotEmpty) {
      return AnswerPayload(selectedOptions: c.selected.toList());
    }
    if (c.blanks.isNotEmpty) {
      return AnswerPayload(
        blanks: [
          for (final e in c.blanks.entries)
            AnswerBlank(key: e.key, value: e.value),
        ],
      );
    }
    if (c.parts.isNotEmpty || c.cells.isNotEmpty) {
      return AnswerPayload(
        parts: c.parts.isEmpty
            ? null
            : [
                for (final e in c.parts.entries)
                  AnswerPart(key: e.key, text: e.value),
              ],
        cells: c.cells.isEmpty
            ? null
            : [
                for (final e in c.cells.entries)
                  if (e.key.split('.').length == 3)
                    AnswerCell(
                      table: e.key.split('.')[0],
                      row: e.key.split('.')[1],
                      col: e.key.split('.')[2],
                      value: e.value,
                    ),
              ],
      );
    }
    return null;
  }
}

// ---------------------------------------------------------------- 题目栏

class _QuestionPane extends StatelessWidget {
  const _QuestionPane({
    required this.controller,
    required this.scroll,
    required this.selfCheckKey,
    required this.onSuggestion,
  });

  final SolveController controller;
  final ScrollController scroll;
  final GlobalKey selfCheckKey;
  final ValueChanged<SuggestedAction> onSuggestion;

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final q = c.question!;
    final theme = Theme.of(context);
    final answering = c.phase == SolvePhase.answering && c.hasVerifiedWorkspace;
    return ListView(
      key: const ValueKey('solve.questionPane'),
      controller: scroll,
      padding: const EdgeInsets.all(kPad),
      children: [
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            InfoChip(
              q.source.label,
              icon: q.source.isEngineeringSample
                  ? Icons.science_outlined
                  : Icons.verified_outlined,
              tone: q.source.isEngineeringSample ? Tone.warning : Tone.success,
            ),
            InfoChip(q.applicability.label, icon: Icons.place_outlined),
            for (final k in q.knowledge)
              InfoChip(k.title, icon: Icons.local_library_outlined),
          ],
        ),
        const SizedBox(height: kGap),
        Section(
          child: MathText(
            q.content.stem,
            style: theme.textTheme.bodyLarge?.copyWith(
              fontSize: 19,
              height: 1.7,
            ),
          ),
        ),
        if (q.content.attachments.isNotEmpty)
          QuestionAttachments(
            key: ValueKey('attachments.${c.userId}.${q.id}.${q.version}'),
            attachments: q.content.attachments,
            load: (mediaId) => c.api.getPublishedQuestionMedia(
              questionId: q.id,
              mediaId: mediaId,
            ),
          ),
        if (q.content.proof != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: ProofStatementBlock(proof: q.content.proof!),
          ),
        if (q.content.safety != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: ExperimentSafetyNotice(safety: q.content.safety!),
          ),
        if (q.judgingNote != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              q.judgingNote!,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ),
        const SizedBox(height: kGap),
        if (c.isRetest && answering)
          const Padding(
            padding: EdgeInsets.only(bottom: kGap),
            child: Callout(
              tone: Tone.info,
              icon: Icons.event_repeat,
              child: Text('这是间隔复测：先不看提示，独立完成。提交之后才能看提示和解析。'),
            ),
          ),
        Section(
          title: answering ? '你的答案' : '你提交的答案',
          child: _answer(context, c, q, enabled: answering),
        ),
        if (isSubjectiveMode(q.answerMode) &&
            c.phase == SolvePhase.submitted) ...[
          const SizedBox(height: kGap),
          SelfCheckCard(key: selfCheckKey, controller: c),
        ],
        if (c.reviewCompletion != null) ...[
          const SizedBox(height: kGap),
          _reviewResult(context, c.reviewCompletion!),
        ] else if (c.reviewError != null) ...[
          const SizedBox(height: kGap),
          const Callout(
            tone: Tone.warning,
            child: Text('这次复测暂时无法确定结果（作答需要确认），复习安排不变。'),
          ),
        ],
        const SizedBox(height: kGap),
        TutorTimeline(
          events: c.events,
          onSuggestion: onSuggestion,
          sessionId: c.eventSessionId,
          questionId: q.id,
          questionVersion:
              c.session?.questionId == q.id &&
                  c.session?.questionVersion == q.version
              ? q.version
              : c.session == null && c.eventSessionId != null
              ? q.version
              : null,
        ),
        const SizedBox(height: 24),
      ],
    );
  }

  Widget _answer(
    BuildContext context,
    SolveController c,
    Question q, {
    required bool enabled,
  }) {
    switch (q.answerMode) {
      case AnswerMode.singleChoice:
      case AnswerMode.multipleChoice:
        return ChoiceInput(
          options: q.content.options,
          multiple: q.answerMode == AnswerMode.multipleChoice,
          selected: c.selected,
          onToggle: c.selectOption,
          enabled: enabled,
        );
      case AnswerMode.fill:
        return FillInput(
          blanks: q.content.blanks,
          values: c.blanks,
          onChanged: c.setBlank,
          enabled: enabled,
        );
      case AnswerMode.written:
        return WrittenInput(
          subquestions: q.content.subquestions,
          values: c.parts,
          onChanged: c.setPart,
          enabled: enabled,
        );
      case AnswerMode.experiment:
        return ExperimentInput(
          tables: q.content.dataTables,
          subquestions: q.content.subquestions,
          cells: c.cells,
          parts: c.parts,
          onCell: c.setCell,
          onPart: c.setPart,
          enabled: enabled,
        );
      case AnswerMode.proof:
        return ProofInput(
          steps: c.steps,
          structure: c.stepsRevision,
          onText: c.setStepText,
          onReason: c.setStepReason,
          onAdd: c.addStep,
          onRemove: c.removeStep,
          onMove: c.moveStep,
          canAdd: c.canAddStep,
          enabled: enabled,
        );
      default:
        return const Callout(
          tone: Tone.info,
          child: Text('这类题目的评分还没有开放。可以在右边的草稿上演算，作答会保存在这台设备上。'),
        );
    }
  }

  Widget _reviewResult(BuildContext context, ReviewCompletion done) {
    final passed = done.result == ReviewResult.passed;
    final next = done.nextDueAt;
    return Callout(
      tone: passed ? Tone.success : Tone.warning,
      icon: passed ? Icons.verified_outlined : Icons.replay,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            passed ? '这次复测通过了' : '这次复测没通过',
            style: Theme.of(context).textTheme.titleSmall,
          ),
          Text(
            passed
                ? (done.reviewItem.status == ReviewStatus.mastered
                      ? '这道题已经连续通过全部复测，记为掌握。'
                      : '进入下一档间隔，之后再测一次。')
                : '回到第一档，明天再测一次。',
          ),
          if (next != null)
            Text('下次复测：${next.toLocal().month}月${next.toLocal().day}日'),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- 底栏

class _ActionBar extends StatelessWidget {
  const _ActionBar({
    required this.controller,
    required this.onTutor,
    required this.onConfirmGiveUp,
  });

  final SolveController controller;
  final Future<void> Function(TutorActionType) onTutor;
  final Future<void> Function() onConfirmGiveUp;

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final q = c.question!;
    final scheme = Theme.of(context).colorScheme;
    final busy = c.tutorBusy || c.submitting;
    final children = <Widget>[];

    if (c.isFinished) {
      children.add(
        FilledButton.icon(
          key: const ValueKey('action.done'),
          onPressed: () =>
              context.canPop() ? context.pop() : context.go('/home'),
          icon: const Icon(Icons.task_alt),
          label: const Text('完成'),
        ),
      );
    } else if (c.phase == SolvePhase.answering) {
      children.add(
        FilledButton.icon(
          key: const ValueKey('action.submit'),
          onPressed: c.canSubmit ? () => unawaited(c.submit()) : null,
          icon: c.submitting
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.send_outlined),
          label: const Text('提交'),
        ),
      );
      if (c.assistanceAllowed) {
        final total = c.session?.hintLevelsTotal ?? q.assists.hintLevels;
        final shown = c.session?.hintLevelRevealed ?? 0;
        children.add(
          OutlinedButton.icon(
            key: const ValueKey('action.hint'),
            onPressed: busy
                ? null
                : () => unawaited(onTutor(TutorActionType.requestHint)),
            icon: const Icon(Icons.tips_and_updates_outlined),
            label: Text(total > 0 ? '给点提示（$shown/$total）' : '给点提示'),
          ),
        );
        if (q.assists.visualAvailable) {
          children.add(
            OutlinedButton.icon(
              key: const ValueKey('action.visual'),
              onPressed: busy
                  ? null
                  : () => unawaited(onTutor(TutorActionType.requestVisual)),
              icon: const Icon(Icons.show_chart),
              label: const Text('看图理解'),
            ),
          );
        }
        children.add(
          TextButton(
            key: const ValueKey('action.giveUp'),
            onPressed: busy ? null : () => unawaited(onConfirmGiveUp()),
            child: const Text('我想直接看解析…'),
          ),
        );
      }
    } else {
      if (q.assists.hasStandardSolution) {
        children.add(
          OutlinedButton.icon(
            key: const ValueKey('action.standard'),
            onPressed: busy
                ? null
                : () => unawaited(onTutor(TutorActionType.requestStandard)),
            icon: const Icon(Icons.menu_book_outlined),
            label: const Text('常规解法'),
          ),
        );
      }
      if (q.assists.hasFastSolution) {
        children.add(
          OutlinedButton.icon(
            key: const ValueKey('action.fast'),
            onPressed: busy
                ? null
                : () => unawaited(onTutor(TutorActionType.requestFast)),
            icon: const Icon(Icons.bolt_outlined),
            label: const Text('快速解法'),
          ),
        );
      }
      if (q.assists.visualAvailable) {
        children.add(
          OutlinedButton.icon(
            key: const ValueKey('action.visual'),
            onPressed: busy
                ? null
                : () => unawaited(onTutor(TutorActionType.requestVisual)),
            icon: const Icon(Icons.show_chart),
            label: const Text('看图理解'),
          ),
        );
      }
      if (!c.isFinished) {
        if (c.continuations.isEmpty) {
          children.add(
            OutlinedButton.icon(
              key: const ValueKey('action.retry'),
              onPressed: busy ? null : () => unawaited(c.retry()),
              icon: const Icon(Icons.replay),
              label: const Text('再试一次'),
            ),
          );
        }
        children.add(
          TextButton(
            key: const ValueKey('action.confused'),
            onPressed: busy
                ? null
                : () => unawaited(onTutor(TutorActionType.markConfused)),
            child: const Text('还是不懂'),
          ),
        );
        children.add(
          FilledButton.icon(
            key: const ValueKey('action.understood'),
            onPressed: busy
                ? null
                : () => unawaited(onTutor(TutorActionType.markUnderstood)),
            icon: const Icon(Icons.check),
            label: const Text('我懂了'),
          ),
        );
      } else {
        children.add(
          FilledButton.icon(
            key: const ValueKey('action.done'),
            onPressed: () =>
                context.canPop() ? context.pop() : context.go('/home'),
            icon: const Icon(Icons.task_alt),
            label: const Text('完成'),
          ),
        );
      }
    }

    return Material(
      color: scheme.surfaceContainerLow,
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: SizedBox(
          width: double.infinity,
          child: Wrap(
            key: const ValueKey('solve.actionBar'),
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: children,
          ),
        ),
      ),
    );
  }
}

class _LocalWorkspaceDialog extends StatefulWidget {
  const _LocalWorkspaceDialog({required this.controller});
  final SolveController controller;
  @override
  State<_LocalWorkspaceDialog> createState() => _LocalWorkspaceDialogState();
}

class _LocalWorkspaceDialogState extends State<_LocalWorkspaceDialog> {
  late final records = widget.controller.readLocalWorkspaces();
  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('本机旧稿（只读）'),
    content: SizedBox(
      width: 720,
      height: 480,
      child: FutureBuilder(
        future: records,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return const Text('记录暂不能读取，原文保留；不会用新版题面猜测旧稿来源。');
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final values = snapshot.data!;
          if (values.isEmpty) return const Text('没有可查看的本机旧稿');
          return ListView(
            children: [
              for (final record in values)
                ExpansionTile(
                  title: Text(record.question?.title ?? '来源版本不明的旧稿'),
                  subtitle: Text(
                    record.question == null
                        ? '题面来源未验证'
                        : '题目版本 ${record.question!.version} · ${record.draft.savedAt.toLocal()}',
                  ),
                  children: [
                    _LocalWorkspaceContent(
                      draft: record.draft,
                      question: record.question,
                    ),
                  ],
                ),
            ],
          );
        },
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('关闭'),
      ),
    ],
  );
}

class _LocalWorkspaceContent extends StatefulWidget {
  const _LocalWorkspaceContent({required this.draft, this.question});
  final LocalDraft draft;
  final Question? question;
  @override
  State<_LocalWorkspaceContent> createState() => _LocalWorkspaceContentState();
}

class _LocalWorkspaceContentState extends State<_LocalWorkspaceContent> {
  late final InkController preview = InkController(onCommit: () {})
    ..loadContract(widget.draft.strokes);
  @override
  void dispose() {
    preview.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final draft = widget.draft, question = widget.question;
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (question != null) ...[
            MathText(question.content.stem),
            if (question.content.proof != null)
              ProofStatementBlock(proof: question.content.proof!),
            if (question.content.safety != null)
              ExperimentSafetyNotice(safety: question.content.safety!),
            if (question.answerMode == AnswerMode.experiment)
              ExperimentInput(
                tables: question.content.dataTables,
                subquestions: question.content.subquestions,
                cells: draft.cells,
                parts: draft.parts,
                onCell: (_, _, _, _) {},
                onPart: (_, _) {},
                enabled: false,
              ),
            if (question.answerMode == AnswerMode.written)
              WrittenInput(
                subquestions: question.content.subquestions,
                values: draft.parts,
                onChanged: (_, _) {},
                enabled: false,
              ),
            if (question.answerMode == AnswerMode.fill)
              FillInput(
                blanks: question.content.blanks,
                values: draft.blanks,
                onChanged: (_, _) {},
                enabled: false,
              ),
            for (final option in question.content.options)
              MathText('${option.key}. ${option.text}'),
          ],
          if (draft.selected.isNotEmpty) Text('选择：${draft.selected.join('、')}'),
          for (final entry in draft.blanks.entries)
            Text('${entry.key}：${entry.value}'),
          for (final entry in draft.parts.entries)
            Text('${entry.key}：${entry.value}'),
          for (final entry in draft.cells.entries)
            Text('${entry.key}：${entry.value}'),
          for (final step in draft.steps)
            Text('${step.text}\n依据：${step.reason}'),
          if (draft.strokes != null)
            SizedBox(
              height: 320,
              child: InkCanvas(controller: preview, readOnly: true),
            ),
        ],
      ),
    );
  }
}

class _ContinuationDialog extends StatefulWidget {
  const _ContinuationDialog({
    required this.draft,
    required this.canContinue,
    required this.onContinue,
  });
  final LocalDraft draft;
  final bool canContinue;
  final VoidCallback onContinue;
  @override
  State<_ContinuationDialog> createState() => _ContinuationDialogState();
}

class _ContinuationDialogState extends State<_ContinuationDialog> {
  late final InkController ink = InkController()
    ..loadContract(widget.draft.strokes);

  String get _answerText => [
    if (widget.draft.selected.isNotEmpty)
      '选项：${widget.draft.selected.join('、')}',
    for (final e in widget.draft.blanks.entries) '${e.key}：${e.value}',
    for (final e in widget.draft.parts.entries) '${e.key}：${e.value}',
    for (final e in widget.draft.cells.entries) '${e.key}：${e.value}',
    for (final e in widget.draft.steps) '${e.text}\n依据：${e.reason}',
  ].join('\n');

  @override
  void dispose() {
    ink.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('未提交续稿'),
    content: SizedBox(
      width: 600,
      height: 400,
      child: Column(
        children: [
          Expanded(
            child: SingleChildScrollView(
              child: Semantics(
                container: true,
                label: _answerText,
                excludeSemantics: true,
                child: SelectableText(_answerText),
              ),
            ),
          ),
          if (widget.draft.strokes != null)
            Expanded(child: InkCanvas(controller: ink, readOnly: true)),
          if (!widget.canContinue) const Text('续稿已保留，可继续查看。'),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('关闭'),
      ),
      if (widget.canContinue)
        FilledButton(
          onPressed: widget.onContinue,
          child: const Text('在原会话继续此稿'),
        ),
    ],
  );
}
