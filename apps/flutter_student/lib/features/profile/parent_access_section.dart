import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/errors.dart';
import '../../core/format.dart';
import '../../core/idempotency.dart';
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
  final PendingKeys _keys = PendingKeys();
  bool _busy = false;
  bool _switching = false;
  Object? _error;

  Future<void> _createInvite() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final invite = await ref
          .read(apiClientProvider)
          .createParentInvite(idempotencyKey: _keys.keyFor('invite'));
      _keys.done('invite');
      ref.invalidate(parentLinksProvider);
      if (!mounted) return;
      setState(() => _busy = false);
      // 邀请码的明文只在这个弹窗里出现一次，服务端也只在这次响应里给；关掉之后哪里都找不回来
      await showDialog<void>(
        context: context,
        builder: (context) => _InviteDialog(invite: invite),
      );
    } catch (error) {
      if (mounted) {
        setState(() {
          _error = error;
          _busy = false;
        });
      }
    }
  }

  Future<void> _revoke(ParentLink link) async {
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
    if (confirmed != true || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final action = 'revoke:${link.id}';
    try {
      await ref
          .read(apiClientProvider)
          .revokeParentLink(
            linkId: link.id,
            idempotencyKey: _keys.keyFor(action, label: 'revoke'),
          );
      _keys.done(action);
      ref.invalidate(parentLinksProvider);
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
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
                      '邀请码只在生成的那一刻显示一次，忘了就重新生成一个。',
                    ),
                  ),
                ],
              ],
            ),
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
                onPressed: _busy ? null : _createInvite,
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
            onPressed: _busy ? null : () => _revoke(link),
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
            Text('关掉这个窗口之后就看不到邀请码了。', style: theme.textTheme.bodySmall),
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
