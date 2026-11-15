import 'package:flutter/material.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/format.dart';
import '../../core/math_text.dart';
import '../../core/widgets.dart';
import '../visual/visual_view.dart';

/// 辅导时间线：按 seq 顺序展示判定、提示、解析、图解、提示语和降级说明。
///
/// 每条事件都标明来源——审核内容、AI 生成（带模型名）或规则——学生可以知道哪些话是 AI 说的。
/// 不认识的事件类型显示一条中性的占位，不会报错。
class TutorTimeline extends StatelessWidget {
  const TutorTimeline({
    super.key,
    required this.events,
    required this.onSuggestion,
    this.now,
  });

  final List<TutorEvent> events;
  final ValueChanged<SuggestedAction> onSuggestion;
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    if (events.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final event in events)
          Padding(
            key: ValueKey('event.${event.seqNo}'),
            padding: const EdgeInsets.only(bottom: 12),
            child: _EventCard(
              event: event,
              onSuggestion: onSuggestion,
              now: now ?? DateTime.now(),
            ),
          ),
      ],
    );
  }
}

class _EventCard extends StatelessWidget {
  const _EventCard({
    required this.event,
    required this.onSuggestion,
    required this.now,
  });

  final TutorEvent event;
  final ValueChanged<SuggestedAction> onSuggestion;
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    switch (event.type) {
      case TutorEventType.diagnosis:
        return _diagnosis(context, event.diagnosis);
      case TutorEventType.hint:
        return _hint(context, event.hint);
      case TutorEventType.standard:
        return _standard(context, event.standard);
      case TutorEventType.fast:
        return _fast(context, event.fast);
      case TutorEventType.visual:
        return _visual(context, event.visual);
      case TutorEventType.ask:
        return _ask(context, event.ask);
      case TutorEventType.notice:
        return _notice(context, event.notice);
      case TutorEventType.uncertainty:
        return _uncertainty(context, event.uncertainty);
      case TutorEventType.fallback:
        return _fallback(context, event.fallback);
      case TutorEventType.$unknown:
        return const Callout(
          tone: Tone.neutral,
          child: Text('这里有一条这个版本的应用还不能显示的内容。更新应用后可以看到。'),
        );
    }
  }

  // ---- 来源标注 ----

  Widget _source(BuildContext context) {
    final meta = event.meta;
    final (String label, IconData icon, Tone tone) = switch (meta.source) {
      TutorEventSource.reviewedContent => (
        '审核内容',
        Icons.verified_outlined,
        Tone.success,
      ),
      TutorEventSource.model => (
        'AI 生成${meta.modelId == null ? '' : '（${meta.modelId}）'}',
        Icons.auto_awesome_outlined,
        Tone.info,
      ),
      TutorEventSource.ruleEngine => (
        '系统规则',
        Icons.rule_folder_outlined,
        Tone.neutral,
      ),
      TutorEventSource.$unknown => ('来源未知', Icons.help_outline, Tone.neutral),
    };
    return InfoChip(label, icon: icon, tone: tone);
  }

  Widget _card(
    BuildContext context, {
    required String title,
    required IconData icon,
    required List<Widget> children,
    bool showSource = true,
  }) {
    final theme = Theme.of(context);
    return Section(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 20, color: theme.colorScheme.primary),
              const SizedBox(width: 8),
              Expanded(child: Text(title, style: theme.textTheme.titleSmall)),
              if (showSource) _source(context),
            ],
          ),
          const SizedBox(height: 10),
          ...children,
        ],
      ),
    );
  }

  Widget _suggestions(List<SuggestedAction> suggestions) {
    if (suggestions.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final s in suggestions)
            OutlinedButton(
              key: ValueKey('suggestion.${s.action}'),
              onPressed: () => onSuggestion(s),
              child: Text(s.label),
            ),
        ],
      ),
    );
  }

  // ---- 各类事件 ----

  Widget _diagnosis(BuildContext context, DiagnosisPayload p) {
    final theme = Theme.of(context);
    final (String title, IconData icon) = switch (p.outcome) {
      'correct' => ('答对了', Icons.check_circle_outline),
      'partially_correct' => ('答对了一部分', Icons.rule),
      _ => ('这次没答对', Icons.lightbulb_outline),
    };
    return _card(
      context,
      title: title,
      icon: icon,
      children: [
        MathText(p.summary, style: theme.textTheme.bodyLarge),
        for (final item in p.feedback.where((f) => f.code != 'correct'))
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.arrow_right,
                  size: 22,
                  color: theme.colorScheme.outline,
                ),
                Expanded(
                  child: MathText(
                    item.target == 'overall'
                        ? item.message
                        : '${item.target}：${item.message}',
                    style: theme.textTheme.bodyMedium,
                  ),
                ),
              ],
            ),
          ),
        if (p.knowledge.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final k in p.knowledge)
                  InfoChip(k.title, icon: Icons.local_library_outlined),
              ],
            ),
          ),
        const SizedBox(height: 8),
        Text(
          '这是练习反馈，不是官方阅卷分数。',
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        _suggestions(p.suggestions),
      ],
      showSource: false,
    );
  }

  Widget _hint(BuildContext context, HintPayload p) {
    final theme = Theme.of(context);
    final title = switch (p.style) {
      'rephrase' => '换种讲法',
      'example' => '举个例子',
      _ => '提示 第 ${p.level}/${p.totalLevels} 层',
    };
    return _card(
      context,
      title: title,
      icon: Icons.tips_and_updates_outlined,
      children: [
        if (p.concept != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: InfoChip(
              '这一轮只讲：${p.concept}',
              icon: Icons.center_focus_strong_outlined,
            ),
          ),
        MathText(p.text, style: theme.textTheme.bodyLarge),
      ],
    );
  }

  Widget _steps(BuildContext context, List<SolutionStep> steps) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < steps.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                CircleAvatar(
                  radius: 12,
                  backgroundColor: theme.colorScheme.primaryContainer,
                  child: Text(
                    '${i + 1}',
                    style: TextStyle(
                      fontSize: 12,
                      color: theme.colorScheme.onPrimaryContainer,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: MathText(
                    steps[i].text,
                    style: theme.textTheme.bodyLarge,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _standard(BuildContext context, StandardPayload p) {
    final theme = Theme.of(context);
    return _card(
      context,
      title: p.title,
      icon: Icons.menu_book_outlined,
      children: [
        _steps(context, p.steps),
        const SizedBox(height: 4),
        Callout(
          tone: Tone.success,
          icon: Icons.flag_outlined,
          child: Row(
            children: [
              Text('答案：', style: theme.textTheme.titleSmall),
              Expanded(
                child: MathText(
                  p.finalAnswer,
                  style: theme.textTheme.bodyLarge,
                ),
              ),
            ],
          ),
        ),
        if (p.optionAnalysis.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('逐项分析', style: theme.textTheme.titleSmall),
          const SizedBox(height: 6),
          for (final item in p.optionAnalysis)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  InfoChip(
                    '${item.key} ${item.verdict == 'correct' ? '对' : '错'}',
                    tone: item.verdict == 'correct'
                        ? Tone.success
                        : Tone.neutral,
                    icon: item.verdict == 'correct' ? Icons.check : Icons.close,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: MathText(
                      item.text,
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                ],
              ),
            ),
        ],
        if (p.keyPoints.isNotEmpty) ...[
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final point in p.keyPoints)
                InfoChip(point, icon: Icons.push_pin_outlined),
            ],
          ),
        ],
      ],
    );
  }

  Widget _fast(BuildContext context, FastPayload p) {
    final theme = Theme.of(context);
    return _card(
      context,
      title: p.title,
      icon: Icons.bolt_outlined,
      children: [
        const Callout(
          tone: Tone.warning,
          icon: Icons.rule,
          child: Text('快速解法只在满足条件时才能用。先看适用条件，再用。'),
        ),
        const SizedBox(height: 10),
        Text('适用条件', style: theme.textTheme.titleSmall),
        const SizedBox(height: 4),
        for (final condition in p.conditions)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.check, size: 18),
                const SizedBox(width: 6),
                Expanded(
                  child: MathText(condition, style: theme.textTheme.bodyMedium),
                ),
              ],
            ),
          ),
        const SizedBox(height: 8),
        _steps(context, p.steps),
        Callout(
          tone: Tone.success,
          icon: Icons.flag_outlined,
          child: Row(
            children: [
              Text('答案：', style: theme.textTheme.titleSmall),
              Expanded(
                child: MathText(
                  p.finalAnswer,
                  style: theme.textTheme.bodyLarge,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 10),
        Callout(
          tone: Tone.danger,
          icon: Icons.block,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('不适用的情形', style: theme.textTheme.titleSmall),
              const SizedBox(height: 2),
              MathText(p.boundary, style: theme.textTheme.bodyMedium),
            ],
          ),
        ),
      ],
    );
  }

  Widget _visual(BuildContext context, VisualPayload p) {
    return _card(
      context,
      title: '看图理解',
      icon: Icons.show_chart,
      children: [
        VisualView(
          key: ValueKey('visual.${event.seqNo}'),
          templateId: p.templateId,
          params: p.params,
          caption: p.caption,
          staticFallback: p.staticFallback,
        ),
      ],
    );
  }

  Widget _ask(BuildContext context, AskPayload p) {
    return _card(
      context,
      title: '接下来',
      icon: Icons.forum_outlined,
      children: [
        MathText(p.prompt, style: Theme.of(context).textTheme.bodyLarge),
        _suggestions(p.suggestions),
      ],
    );
  }

  Widget _notice(BuildContext context, NoticePayload p) {
    final theme = Theme.of(context);
    final (Tone tone, IconData icon) = switch (p.code) {
      'review_scheduled' => (Tone.info, Icons.event_repeat),
      'needs_human_help' => (Tone.warning, Icons.support_agent),
      'session_completed' => (Tone.success, Icons.task_alt),
      _ => (Tone.neutral, Icons.info_outline),
    };
    return Callout(
      tone: tone,
      icon: icon,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          MathText(p.text, style: theme.textTheme.bodyMedium),
          if (p.dueAt != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '复测时间：${formatWhen(p.dueAt!, now)}',
                style: theme.textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _uncertainty(BuildContext context, UncertaintyPayload p) {
    if (p.reasonCode == 'subjective_self_check') {
      // 解答题本来就不自动评分：不是"没能判定"，也不是等什么人来确认，而是请学生自己对照要点检查
      return Callout(
        tone: Tone.info,
        icon: Icons.fact_check_outlined,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('这道题不自动评分', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 2),
            Text(p.text),
            const SizedBox(height: 4),
            Text(
              '这次不算对，也不算错，不会计入正确率。',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      );
    }
    return Callout(
      tone: Tone.warning,
      icon: Icons.help_outline,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('待确认', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 2),
          Text(p.text),
          const SizedBox(height: 4),
          Text(
            '这次不算对，也不算错，不会计入正确率。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }

  Widget _fallback(BuildContext context, FallbackPayload p) {
    return Callout(
      tone: Tone.warning,
      icon: Icons.cloud_off_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(p.text),
          if (p.suggestions.isNotEmpty) _suggestions(p.suggestions),
        ],
      ),
    );
  }
}
