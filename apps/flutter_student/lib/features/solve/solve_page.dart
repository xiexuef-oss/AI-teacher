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
import 'ink/ink_canvas.dart';
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
    _controller = SolveController(
      api: ref.read(apiClientProvider),
      store: ref.read(keyValueStoreProvider),
      userId: ref.read(userIdProvider)!,
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
            SolvePhase.failed => ErrorView(
              error: c.failure!,
              onRetry: () => unawaited(c.start()),
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
          _Banners(controller: c, onRelogin: _relogin),
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
                    controller: c.ink,
                    readOnly: c.phase == SolvePhase.submitted,
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
  const _Banners({required this.controller, required this.onRelogin});

  final SolveController controller;
  final Future<void> Function() onRelogin;

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
                    onPressed: () => unawaited(c.resolveConflictKeepLocal()),
                    child: const Text('保留我的'),
                  ),
                  OutlinedButton(
                    key: const ValueKey('banner.useServer'),
                    onPressed: () => unawaited(c.resolveConflictUseServer()),
                    child: const Text('用云端的'),
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
    if (c.questionFromCache) {
      banners.add(
        const Callout(
          tone: Tone.info,
          icon: Icons.offline_pin_outlined,
          child: Text('没有网络：显示的是上次保存的题目。云端提示和判分要联网后才能用。'),
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
    final answering = c.phase == SolvePhase.answering;
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
        TutorTimeline(events: c.events, onSuggestion: onSuggestion),
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

    if (c.phase == SolvePhase.answering) {
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
        children.add(
          OutlinedButton.icon(
            key: const ValueKey('action.retry'),
            onPressed: busy ? null : () => unawaited(c.retry()),
            icon: const Icon(Icons.replay),
            label: const Text('再试一次'),
          ),
        );
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
