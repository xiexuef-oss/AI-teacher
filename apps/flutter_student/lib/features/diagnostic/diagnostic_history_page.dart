import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/labels.dart';
import '../../core/math_text.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

final diagnosticHistoryProvider = FutureProvider.autoDispose
    .family<DiagnosticHistoryPage, String?>((ref, cursor) async {
      final owner = await ref.watch(studentSessionProvider.future);
      final api = TutorApiClient(
        ApiCore(
          baseUrl: ref.read(apiBaseUrlProvider),
          transport: ref.read(apiTransportProvider),
          tokenProvider: () => owner.token,
        ),
      );
      return api.listDiagnosticHistory(cursor: cursor, limit: 20);
    });

class DiagnosticHistoryScreen extends ConsumerWidget {
  const DiagnosticHistoryScreen({super.key, this.cursor});
  final String? cursor;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final page = ref.watch(diagnosticHistoryProvider(cursor));
    return Scaffold(
      key: const ValueKey('diagnostic.history'),
      appBar: AppBar(
        title: const Text('历史摸底'),
        actions: [
          IconButton(
            tooltip: '刷新历史摸底',
            onPressed: () => ref.invalidate(diagnosticHistoryProvider(cursor)),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: page.when(
          skipLoadingOnRefresh: false,
          skipLoadingOnReload: false,
          loading: () => const LoadingView(),
          error: (error, _) => ErrorView(
            error: error,
            onRetry: () => ref.invalidate(diagnosticHistoryProvider(cursor)),
          ),
          data: (history) => Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 900),
              child: ListView(
                padding: const EdgeInsets.all(kPad),
                children: [
                  const Text(
                    '历史列表需要联网。展开后可回看已有会话；未开始的题目不会在这里新建作答。全部云端计划可在“我的”导出服务端学习记录。',
                  ),
                  if (history.items.isEmpty)
                    const Padding(
                      padding: EdgeInsets.all(kPad),
                      child: Text('这一页没有摸底记录'),
                    ),
                  for (final run in history.items)
                    Card(
                      child: ExpansionTile(
                        key: ValueKey('diagnostic.history.${run.id}'),
                        title: Text(
                          '${subjectName(run.subject)} · ${run.status == 'completed'
                              ? '已完成'
                              : run.status == 'abandoned'
                              ? '已结束'
                              : '进行中'} · 已提交 ${run.summary.submitted}/3 题',
                        ),
                        subtitle: Text(
                          '${run.createdAt.toLocal()} · ${regionName(run.scope.regionCode)} · ${run.scope.grade == null ? '年级暂不清楚' : gradeName(run.scope.grade!)}',
                        ),
                        childrenPadding: const EdgeInsets.all(kPad),
                        expandedCrossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '本轮独立正确 ${run.summary.independentCorrect}，独立不正确 ${run.summary.independentIncorrect}，借助提示 ${run.summary.assisted}，未确认 ${run.summary.unconfirmed}。不推算掌握度或分数。',
                          ),
                          for (final item in run.items)
                            Padding(
                              padding: const EdgeInsets.symmetric(
                                vertical: kGap,
                              ),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  MathText(
                                    '${item.position}. ${item.question.title}',
                                  ),
                                  Text(item.question.source.label),
                                  if (item.sessionId == null)
                                    const Text('尚未开始')
                                  else
                                    TextButton(
                                      key: ValueKey(
                                        'diagnostic.history.open.${run.id}.${item.position}',
                                      ),
                                      onPressed: () async {
                                        final owner = ref
                                            .read(authProvider)
                                            .asData
                                            ?.value;
                                        await context.push(
                                          Uri(
                                            path:
                                                '/questions/${item.question.id}/solve',
                                            queryParameters: {
                                              'origin': 'practice',
                                              'session': item.sessionId!,
                                            },
                                          ).toString(),
                                        );
                                        if (context.mounted &&
                                            identical(
                                              owner,
                                              ref
                                                  .read(authProvider)
                                                  .asData
                                                  ?.value,
                                            )) {
                                          ref.invalidate(
                                            diagnosticHistoryProvider(cursor),
                                          );
                                        }
                                      },
                                      child: Text(
                                        item.submission == null
                                            ? '继续已有作答'
                                            : '回看首份作答',
                                      ),
                                    ),
                                ],
                              ),
                            ),
                        ],
                      ),
                    ),
                  if (history.nextCursor != null)
                    FilledButton(
                      key: const ValueKey('diagnostic.history.next'),
                      onPressed: () => context.push(
                        Uri(
                          path: '/diagnostic/history',
                          queryParameters: {'cursor': history.nextCursor!},
                        ).toString(),
                      ),
                      child: const Text('下一页摸底记录'),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
