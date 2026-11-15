import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/labels.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

class PracticeFilters {
  const PracticeFilters({
    this.subject,
    this.mode,
    this.scope = QuestionScope.all,
  });

  final Subject? subject;
  final AnswerMode? mode;
  final QuestionScope scope;

  PracticeFilters copyWith({
    Object? subject = _keep,
    Object? mode = _keep,
    QuestionScope? scope,
  }) => PracticeFilters(
    subject: identical(subject, _keep) ? this.subject : subject as Subject?,
    mode: identical(mode, _keep) ? this.mode : mode as AnswerMode?,
    scope: scope ?? this.scope,
  );
}

const Object _keep = Object();

class PracticeState {
  const PracticeState({
    this.filters = const PracticeFilters(),
    this.items = const [],
    this.nextCursor,
    this.loading = false,
    this.loaded = false,
    this.error,
  });

  final PracticeFilters filters;
  final List<QuestionSummary> items;
  final String? nextCursor;
  final bool loading;
  final bool loaded;
  final Object? error;

  PracticeState copyWith({
    PracticeFilters? filters,
    List<QuestionSummary>? items,
    Object? nextCursor = _keep,
    bool? loading,
    bool? loaded,
    Object? error = _keep,
  }) => PracticeState(
    filters: filters ?? this.filters,
    items: items ?? this.items,
    nextCursor: identical(nextCursor, _keep)
        ? this.nextCursor
        : nextCursor as String?,
    loading: loading ?? this.loading,
    loaded: loaded ?? this.loaded,
    error: identical(error, _keep) ? this.error : error,
  );
}

class PracticeController extends Notifier<PracticeState> {
  /// 每次筛选变化都会让之前还没回来的请求作废。
  int _generation = 0;

  @override
  PracticeState build() => const PracticeState();

  Future<void> refresh() => _load(reset: true);

  Future<void> loadMore() async {
    if (state.nextCursor == null || state.loading) return;
    await _load(reset: false);
  }

  Future<void> setFilters(PracticeFilters filters) {
    state = state.copyWith(filters: filters);
    return refresh();
  }

  Future<void> _load({required bool reset}) async {
    final generation = ++_generation;
    state = state.copyWith(
      loading: true,
      error: null,
      items: reset ? const [] : null,
      nextCursor: reset ? null : _keep,
    );
    try {
      await ref.read(authProvider.future);
      final f = state.filters;
      final page = await ref
          .read(apiClientProvider)
          .listQuestions(
            subject: f.subject,
            answerMode: f.mode,
            scope: f.scope == QuestionScope.all ? null : f.scope,
            cursor: reset ? null : state.nextCursor,
            limit: 20,
          );
      if (generation != _generation) return;
      state = state.copyWith(
        items: reset ? page.items : [...state.items, ...page.items],
        nextCursor: page.nextCursor,
        loading: false,
        loaded: true,
      );
    } catch (error) {
      if (generation != _generation) return;
      state = state.copyWith(loading: false, error: error);
    }
  }
}

final practiceProvider =
    NotifierProvider.autoDispose<PracticeController, PracticeState>(
      PracticeController.new,
    );

/// P06 练习：按科目、题型、适用范围选题。
class PracticePage extends ConsumerStatefulWidget {
  const PracticePage({super.key});

  @override
  ConsumerState<PracticePage> createState() => _PracticePageState();
}

class _PracticePageState extends ConsumerState<PracticePage> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(practiceProvider.notifier).refresh());
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(practiceProvider);
    final controller = ref.read(practiceProvider.notifier);
    return Scaffold(
      key: const ValueKey('practice.page'),
      appBar: AppBar(
        title: const Text('练习'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: OutlinedButton.icon(
              key: const ValueKey('practice.review'),
              onPressed: () => context.push('/review'),
              icon: const Icon(Icons.event_repeat),
              label: const Text('错题复习'),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 900),
            child: Column(
              children: [
                _Filters(
                  filters: state.filters,
                  onChanged: controller.setFilters,
                ),
                Expanded(
                  child: _List(state: state, controller: controller),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Filters extends StatelessWidget {
  const _Filters({required this.filters, required this.onChanged});

  final PracticeFilters filters;
  final ValueChanged<PracticeFilters> onChanged;

  @override
  Widget build(BuildContext context) {
    Widget row(String label, List<Widget> chips) => Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          SizedBox(
            width: 52,
            child: Text(label, style: Theme.of(context).textTheme.bodyMedium),
          ),
          Expanded(child: Wrap(spacing: 8, runSpacing: 4, children: chips)),
        ],
      ),
    );

    return Padding(
      padding: const EdgeInsets.fromLTRB(kPad, 8, kPad, 4),
      child: Column(
        children: [
          row('科目', [
            ChoiceChip(
              key: const ValueKey('filter.subject.all'),
              label: const Text('全部'),
              selected: filters.subject == null,
              onSelected: (_) => onChanged(filters.copyWith(subject: null)),
            ),
            for (final s in [Subject.math, Subject.physics, Subject.chemistry])
              ChoiceChip(
                key: ValueKey('filter.subject.${s.value}'),
                label: Text(subjectName(s)),
                selected: filters.subject == s,
                onSelected: (_) => onChanged(filters.copyWith(subject: s)),
              ),
          ]),
          row('题型', [
            ChoiceChip(
              key: const ValueKey('filter.mode.all'),
              label: const Text('全部'),
              selected: filters.mode == null,
              onSelected: (_) => onChanged(filters.copyWith(mode: null)),
            ),
            for (final m in [
              AnswerMode.singleChoice,
              AnswerMode.multipleChoice,
              AnswerMode.fill,
              AnswerMode.written,
              AnswerMode.experiment,
              AnswerMode.proof,
            ])
              ChoiceChip(
                key: ValueKey('filter.mode.${m.value}'),
                label: Text(answerModeName(m)),
                selected: filters.mode == m,
                onSelected: (_) => onChanged(filters.copyWith(mode: m)),
              ),
          ]),
          row('范围', [
            for (final (scope, label) in [
              (QuestionScope.all, '全部'),
              (QuestionScope.region, '地区适用'),
              (QuestionScope.general, '全国通用基础题'),
            ])
              ChoiceChip(
                key: ValueKey('filter.scope.${scope.value}'),
                label: Text(label),
                selected: filters.scope == scope,
                onSelected: (_) => onChanged(filters.copyWith(scope: scope)),
              ),
          ]),
        ],
      ),
    );
  }
}

class _List extends StatelessWidget {
  const _List({required this.state, required this.controller});

  final PracticeState state;
  final PracticeController controller;

  @override
  Widget build(BuildContext context) {
    if (state.error != null && state.items.isEmpty) {
      return ErrorView(error: state.error!, onRetry: controller.refresh);
    }
    if (!state.loaded && state.loading) {
      return const LoadingView(label: '正在找题…');
    }
    if (state.loaded && state.items.isEmpty) {
      return const EmptyView(
        title: '没有符合条件的题',
        message: '换一个筛选条件试试。没有授权的高考真题不会拿别的题顶替，所以“真题”类的筛选目前是空的。',
        icon: Icons.search_off,
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.all(kPad),
      itemCount: state.items.length + 1,
      separatorBuilder: (_, _) => const SizedBox(height: kGap),
      itemBuilder: (context, index) {
        if (index == state.items.length) {
          if (state.nextCursor == null) return const SizedBox(height: 24);
          return Center(
            child: state.loading
                ? const Padding(
                    padding: EdgeInsets.all(12),
                    child: CircularProgressIndicator(),
                  )
                : OutlinedButton(
                    key: const ValueKey('practice.more'),
                    onPressed: controller.loadMore,
                    child: const Text('加载更多'),
                  ),
          );
        }
        return _QuestionTile(question: state.items[index]);
      },
    );
  }
}

class _QuestionTile extends StatelessWidget {
  const _QuestionTile({required this.question});

  final QuestionSummary question;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      key: ValueKey('question.${question.id}'),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => context.push(solveRoute(question.id)),
        child: Padding(
          padding: const EdgeInsets.all(kPad),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  InfoChip(subjectName(question.subject)),
                  InfoChip(answerModeName(question.answerMode)),
                  InfoChip(
                    '难度 ${question.difficulty}',
                    icon: Icons.signal_cellular_alt,
                  ),
                  InfoChip(
                    question.applicability.label,
                    icon: Icons.place_outlined,
                    tone:
                        question.applicability.scope ==
                            ApplicabilityScope.region
                        ? Tone.info
                        : Tone.neutral,
                  ),
                  if (question.variantOf != null)
                    const InfoChip('变式', icon: Icons.shuffle),
                ],
              ),
              const SizedBox(height: 8),
              Text(question.title, style: theme.textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(
                question.source.label,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
