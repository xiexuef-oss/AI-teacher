import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/providers.dart';

class CloudDraftsPage extends ConsumerStatefulWidget {
  const CloudDraftsPage({super.key, required this.questionId});
  final String questionId;
  @override
  ConsumerState<CloudDraftsPage> createState() => _CloudDraftsPageState();
}

class _CloudDraftsPageState extends ConsumerState<CloudDraftsPage> {
  final items = <QuestionDraftRef>[];
  String? cursor;
  Object? error;
  bool busy = false;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final page = await ref
          .read(apiClientProvider)
          .listQuestionDrafts(
            questionId: widget.questionId,
            cursor: cursor,
            limit: 20,
          );
      if (mounted) {
        setState(() {
          items.addAll(page.items);
          cursor = page.nextCursor;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('云端草稿')),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Text('选择一份草稿后继续。查看列表不会替换这台设备上的内容。'),
        if (error != null) Text('读取失败：$error'),
        if (!busy && items.isEmpty && error == null) const Text('没有云端草稿'),
        for (final item in items)
          ListTile(
            title: Text('草稿 ${item.attemptNo} · 题目版本 ${item.questionVersion}'),
            subtitle: Text(
              item.sessionState == SessionState.done
                  ? '会话已完成，不能继续编辑'
                  : item.copiedFromAttemptId == null
                  ? '原稿 · 修订 ${item.draftRevision}'
                  : '独立副本 · 修订 ${item.draftRevision}',
            ),
            enabled: item.sessionState != SessionState.done,
            onTap: () => context.push(
              Uri(
                path: '/questions/${widget.questionId}/solve',
                queryParameters: {
                  'session': item.sessionId,
                  'attempt': item.attemptId,
                  'origin': item.origin.value,
                  if (item.reviewItemId != null) 'review': item.reviewItemId!,
                },
              ).toString(),
            ),
          ),
        if (busy) const LinearProgressIndicator(),
        if (!busy && (cursor != null || error != null))
          TextButton(
            onPressed: _load,
            child: Text(error != null ? '重试' : '加载更多'),
          ),
      ],
    ),
  );
}
