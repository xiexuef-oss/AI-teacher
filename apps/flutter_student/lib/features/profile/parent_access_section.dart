import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/errors.dart';
import '../../core/format.dart';
import '../parent/parent_actions.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

/// "我的"页里的"家长查看"：学生自己决定家长能不能看周报（PRD §3、US-06）。
///
/// 授权是学生主动生成一个一次性的邀请码、告诉家长，家长输入之后才建立；随时可以撤销，撤销马上生效。
/// 这是原型阶段的授权方式，不代表监护人核验（Q-03 还没有冻结）。
class ParentAccessSection extends ConsumerStatefulWidget {
  const ParentAccessSection({super.key});

  @override
  ConsumerState<ParentAccessSection> createState() =>
      _ParentAccessSectionState();
}

class _ParentAccessSectionState extends ConsumerState<ParentAccessSection> {
  bool _same(AuthSession owner) {
    final current = ref.read(authProvider).asData?.value;
    return mounted &&
        current?.userId == owner.userId &&
        current?.token == owner.token &&
        current?.role == owner.role;
  }

  @override
  void initState() {
    super.initState();
    Future.microtask(() async {
      AuthSession? owner;
      try {
        owner = await ref.read(authProvider.future);
        if (!mounted) return;
        await ref.read(parentActionsProvider.future);
        if (_same(owner!)) {
          await ref.read(parentActionsProvider.notifier).refresh();
        }
      } catch (error) {
        if (owner != null && _same(owner)) setState(() => _error = error);
      }
    });
  }

  Future<void> _recover({String? historyKey}) async {
    final owner = ref.read(authProvider).requireValue;
    setState(() => _busy = true);
    try {
      final actions = ref.read(parentActionsProvider.notifier);
      final result = historyKey == null
          ? await actions.retry()
          : await actions.replayInvite(historyKey);
      if (!_same(owner)) return;
      ref.invalidate(parentLinksProvider);
      if (result is ParentInvite && mounted) {
        await showDialog<void>(
          context: context,
          builder: (_) => _InviteDialog(invite: result),
        );
      }
    } catch (error) {
      if (_same(owner)) setState(() => _error = error);
    } finally {
      if (_same(owner)) setState(() => _busy = false);
    }
  }

  Future<void> _finishConflict() async {
    final owner = ref.read(authProvider).requireValue;
    try {
      await ref.read(parentActionsProvider.notifier).finishConflict();
      if (!_same(owner)) return;
      ref.invalidate(parentLinksProvider);
    } catch (error) {
      if (mounted) setState(() => _error = error);
    }
  }

  Future<void> _abandon() async {
    final owner = ref.read(authProvider).requireValue;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('保留未知记录，另起新操作？'),
        content: const Text(
          '旧请求可能已经完成或稍后完成。停止本机重试不会取消旧请求；重新生成可能让另一端的邀请码失效。请先查看当前授权。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('返回'),
          ),
          FilledButton(
            key: const ValueKey('parent.abandon.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('保留记录并继续'),
          ),
        ],
      ),
    );
    if (confirmed != true || !_same(owner)) return;
    try {
      await ref.read(parentActionsProvider.notifier).abandonUnknown();
    } catch (error) {
      if (_same(owner)) setState(() => _error = error);
    }
  }

  Future<void> _ackHistory() async {
    final owner = ref.read(authProvider).requireValue;
    try {
      await ref.read(parentActionsProvider.notifier).acknowledgeHistory();
      if (!_same(owner)) return;
      setState(() => _error = null);
    } catch (error) {
      if (_same(owner)) setState(() => _error = error);
    }
  }

  bool _busy = false;
  bool _switching = false;
  Object? _error;

  Future<void> _createInvite() async {
    final owner = ref.read(authProvider).requireValue;
    final revision = ref
        .read(parentLinksProvider)
        .asData
        ?.value
        .parentInviteRevision;
    if (revision == null) {
      setState(() => _error = StateError('邀请版本未知，请联网刷新'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final invite = await ref
          .read(parentActionsProvider.notifier)
          .create(revision);
      if (!_same(owner)) return;
      ref.invalidate(parentLinksProvider);
      if (invite is! ParentInvite) {
        setState(
          () => _error = StateError('原操作已确认，但原码当前无法安全展示。请查看当前授权后明确生成新码。'),
        );
        return;
      }
      if (!mounted) return;
      setState(() => _busy = false);
      // 邀请码只留内存；关闭后可向服务端请求重显仍有效的原码
      await showDialog<void>(
        context: context,
        builder: (context) => _InviteDialog(invite: invite),
      );
    } catch (error) {
      if (_same(owner)) {
        setState(() {
          _error = error;
          _busy = false;
        });
      }
    } finally {
      if (_same(owner)) setState(() => _busy = false);
    }
  }

  Future<void> _revoke(ParentLink link) async {
    final owner = ref.read(authProvider).requireValue;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('撤销这位家长的授权？'),
        content: const Text('撤销后，这位家长立刻就看不到你的周报了。以后想再给，需要重新生成邀请码。'),
        actions: [
          TextButton(
            key: const ValueKey('dialog.revoke.cancel'),
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            key: const ValueKey('dialog.revoke.confirm'),
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('撤销授权'),
          ),
        ],
      ),
    );
    if (confirmed != true || !_same(owner)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(parentActionsProvider.notifier).revoke(link);
      if (!_same(owner)) return;
      ref.invalidate(parentLinksProvider);
    } catch (error) {
      if (_same(owner)) setState(() => _error = error);
    } finally {
      if (_same(owner)) setState(() => _busy = false);
    }
  }

  Future<void> _switchToParent() async {
    final router = GoRouter.of(context);
    setState(() {
      _switching = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).switchTo(LocalRole.parent);
      // 状态换掉之后"我的"页就被换走了，所以用事先拿好的路由跳转
      router.go('/parent');
    } catch (error) {
      if (mounted) {
        setState(() {
          _error = error;
          _switching = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final links = ref.watch(parentLinksProvider);
    final journal = ref.watch(parentActionsProvider).asData?.value;
    final command = journal?.active;
    final history = journal?.commands
        .where((c) => c.kind == 'create' && c.result != null)
        .lastOrNull;
    return Section(
      key: const ValueKey('parent.access'),
      title: '家长查看',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '家长只能看到你授权的、按周汇总的趋势：练习了几天、做了几份、各项比例。'
            '看不到题目、作答内容、草稿和笔迹。你可以随时撤销授权，撤销后家长马上就看不到了。',
          ),
          const SizedBox(height: 10),
          links.when(
            loading: () => const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: LoadingView(),
            ),
            error: (error, _) => ErrorView(
              error: error,
              onRetry: () => ref.invalidate(parentLinksProvider),
            ),
            data: (data) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (data.links.isEmpty)
                  Text('还没有授权任何家长。', style: theme.textTheme.bodyMedium)
                else
                  for (final link in data.links) _linkRow(context, link),
                if (data.pendingInvite != null) ...[
                  const SizedBox(height: 8),
                  Callout(
                    key: const ValueKey('parent.pending'),
                    tone: Tone.neutral,
                    icon: Icons.schedule,
                    child: Text(
                      '有一个还没用掉的邀请码，${formatWhen(data.pendingInvite!.expiresAt, ref.watch(clockProvider)())}前有效。'
                      '邀请码不会存储在本机；可向服务端请求重显仍有效的原码，失效后再明确生成新码。',
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (command == null && history != null) ...[
            const Text('上次生成操作已确认；历史结果不代表邀请码仍有效。邀请码不会存储在本机。'),
            if (history.deliveryUnavailable)
              const Text('原码已无法恢复，请查看当前状态后明确生成新码。')
            else
              OutlinedButton(
                key: const ValueKey('parent.replayInvite'),
                onPressed: _busy
                    ? null
                    : () => _recover(historyKey: history.key),
                child: const Text('向服务端请求重显原码'),
              ),
          ],
          if (command?.phase == 'result_known') ...[
            const Text('原操作已成功，本机仅记录历史回执；这不代表当前授权或邀请码仍有效。'),
            OutlinedButton(
              key: ValueKey(
                command!.deliveryUnavailable
                    ? 'parent.finishKnown'
                    : 'parent.ackResult',
              ),
              onPressed: _busy ? null : _ackHistory,
              child: Text(
                command.deliveryUnavailable ? '保留已生成记录，返回后重新生成' : '确认历史结果（不联网）',
              ),
            ),
          ],
          if (command != null) ...[
            Text(
              command.phase == 'conflict'
                  ? '原操作的版本已变化，请查看当前授权。结束旧操作后，重新确认才能发起新操作。'
                  : '有一笔操作尚未确认。刷新当前授权不会确认历史请求，请重试原操作。',
            ),
            OutlinedButton(
              key: const ValueKey('parent.retry'),
              onPressed: _busy || command.phase == 'conflict' ? null : _recover,
              child: const Text('重试原操作'),
            ),
            if (command.phase == 'conflict')
              Text(
                '原版本：${command.body?['expected_parent_invite_revision'] ?? command.body?['expected_authorization_revision']}；云端版本：${command.conflict?['parent_invite_revision'] ?? command.conflict?['authorization_revision'] ?? '未知，请联网查看'}。结束旧冲突后必须重新确认操作。',
              ),
            if (command.phase == 'conflict')
              OutlinedButton(
                key: const ValueKey('parent.finishConflict'),
                onPressed: _busy ? null : _finishConflict,
                child: const Text('结束旧冲突，查看当前授权'),
              ),
          ],
          if (command != null &&
              ['prepared', 'outcome_unavailable'].contains(command.phase))
            OutlinedButton(
              key: const ValueKey('parent.abandon'),
              onPressed: _busy ? null : _abandon,
              child: const Text('保留未知记录，另起新操作'),
            ),
          OutlinedButton(
            key: const ValueKey('parent.refresh'),
            onPressed: _busy
                ? null
                : () async {
                    try {
                      await ref.read(parentActionsProvider.notifier).refresh();
                      ref.invalidate(parentLinksProvider);
                    } catch (error) {
                      if (mounted) setState(() => _error = error);
                    }
                  },
            child: const Text('刷新当前授权'),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Callout(
              tone: Tone.danger,
              announce: true,
              child: Text(describeError(_error!)),
            ),
          ],
          const SizedBox(height: 12),
          Wrap(
            spacing: kGap,
            runSpacing: kGap,
            children: [
              FilledButton.icon(
                key: const ValueKey('parent.invite'),
                onPressed: _busy || command != null ? null : _createInvite,
                icon: const Icon(Icons.person_add_alt_1_outlined),
                label: const Text('生成邀请码'),
              ),
              OutlinedButton.icon(
                key: const ValueKey('profile.switchToParent'),
                onPressed: _switching ? null : _switchToParent,
                icon: const Icon(Icons.swap_horiz),
                label: const Text('切换到家长身份（本机演示）'),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '原型阶段的授权方式：你生成邀请码、告诉家长，家长输入之后才建立。'
            '这不是监护人核验，也没有真实的家长账号。',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }

  Widget _linkRow(BuildContext context, ParentLink link) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        key: ValueKey('parent.link.${link.id}'),
        child: ListTile(
          leading: const Icon(Icons.family_restroom_outlined),
          title: Text(link.parentLabel ?? '家长 ${shortId(link.parentId)}'),
          subtitle: Text('${monthDay(link.consentAt)}授权，可以看每周汇总'),
          trailing: OutlinedButton(
            key: ValueKey('parent.revoke.${link.id}'),
            onPressed:
                _busy ||
                    ref.watch(parentActionsProvider).asData?.value?.active !=
                        null
                ? null
                : () => _revoke(link),
            child: const Text('撤销'),
          ),
        ),
      ),
    );
  }
}

/// 把邀请码展示给学生：五位一组，方便念给家长听。
class _InviteDialog extends ConsumerWidget {
  const _InviteDialog({required this.invite});

  final ParentInvite invite;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final code = invite.code;
    final grouped = code.length > 5
        ? '${code.substring(0, 5)} ${code.substring(5)}'
        : code;
    return AlertDialog(
      title: const Text('邀请码'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('把这个邀请码告诉家长，让家长在家长页输入。'),
            const SizedBox(height: 12),
            Center(
              child: Text(
                grouped,
                key: const ValueKey('parent.invite.code'),
                style: theme.textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  letterSpacing: 2,
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              '${formatWhen(invite.expiresAt, ref.watch(clockProvider)())}前有效，只能用一次；'
              '用过或者过期就失效了。',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 4),
            Text('重新生成会让这一个失效。', style: theme.textTheme.bodySmall),
            const SizedBox(height: 4),
            Text(
              '关掉后本机不保存原码；可以向服务端请求重显仍有效的原码。',
              style: theme.textTheme.bodySmall,
            ),
          ],
        ),
      ),
      actions: [
        FilledButton(
          key: const ValueKey('parent.invite.close'),
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('我知道了'),
        ),
      ],
    );
  }
}
