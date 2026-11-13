import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

/// P10 家长首页：学生明确授权之后，家长只看到按周汇总的趋势（PRD P0 第 8 条、US-06）。
///
/// 这里的家长是本地身份 Mock，不是真实账号——监护授权方案（Q-03）还没有冻结。
/// 页面上不出现任何学生的题目、作答、草稿或笔迹，也不出现每次练习的时间。
class ParentHomePage extends ConsumerStatefulWidget {
  const ParentHomePage({super.key});

  @override
  ConsumerState<ParentHomePage> createState() => _ParentHomePageState();
}

class _ParentHomePageState extends ConsumerState<ParentHomePage> {
  final TextEditingController _code = TextEditingController();
  final PendingKeys _keys = PendingKeys();
  bool _busy = false;
  bool _linked = false;
  bool _switching = false;
  Object? _error;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _link() async {
    final code = _code.text.trim();
    if (code.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _linked = false;
    });
    // 同一个邀请码重试时复用同一个键；换了邀请码就是另一个动作
    final action = 'redeem:$code';
    try {
      await ref
          .read(apiClientProvider)
          .redeemParentInvite(
            body: ParentInviteRedeem(code: code),
            idempotencyKey: _keys.keyFor(action, label: 'redeem'),
          );
      _keys.done(action);
      ref.invalidate(parentStudentsProvider);
      if (mounted) {
        _code.clear();
        setState(() => _linked = true);
      }
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _switchToStudent() async {
    final router = GoRouter.of(context);
    setState(() {
      _switching = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).switchTo(LocalRole.student);
      // 状态换掉之后这个页面就被换走了，所以用事先拿好的路由跳转
      router.go('/');
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
    final students = ref.watch(parentStudentsProvider);
    final error = _error;
    final alreadyLinked =
        error is ApiException && error.code == 'already_linked';

    return Scaffold(
      key: const ValueKey('parent.home'),
      appBar: AppBar(title: const Text('家长')),
      body: SafeArea(
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(kPad),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Callout(
                    tone: Tone.info,
                    child: Text(
                      '你能看到的只有学生授权给你的、按周汇总的趋势：练习了几天、做了几份、各项比例。'
                      '看不到题目、作答内容、草稿和笔迹。学生可以随时撤销授权，撤销后马上就看不到了。\n'
                      '这是原型阶段的本机演示：没有真实的账号，也没有监护人核验。',
                    ),
                  ),
                  const SizedBox(height: kPad),
                  Section(
                    title: '已授权的学生',
                    child: students.when(
                      loading: () => const Padding(
                        padding: EdgeInsets.all(kPad),
                        child: LoadingView(),
                      ),
                      error: (error, _) => ErrorView(
                        error: error,
                        onRetry: () => ref.invalidate(parentStudentsProvider),
                      ),
                      data: (data) => data.items.isEmpty
                          ? const _NoStudents()
                          : Column(
                              children: [
                                for (final student in data.items)
                                  _StudentTile(student: student),
                              ],
                            ),
                    ),
                  ),
                  const SizedBox(height: kGap),
                  Section(
                    title: '输入学生给你的邀请码',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '邀请码由学生在自己的「我的」页生成，十位，一次有效，24 小时内用。'
                          '输入时空格、短横线和大小写都不影响。',
                          style: theme.textTheme.bodySmall,
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          key: const ValueKey('parent.code'),
                          controller: _code,
                          enabled: !_busy,
                          autocorrect: false,
                          enableSuggestions: false,
                          textCapitalization: TextCapitalization.characters,
                          textInputAction: TextInputAction.done,
                          inputFormatters: [
                            LengthLimitingTextInputFormatter(40),
                          ],
                          decoration: const InputDecoration(
                            labelText: '邀请码',
                            hintText: 'XXXXX-XXXXX',
                          ),
                          onChanged: (_) => setState(() {}),
                          onSubmitted: (_) => _link(),
                        ),
                        const SizedBox(height: 10),
                        FilledButton(
                          key: const ValueKey('parent.link'),
                          onPressed: _code.text.trim().isEmpty || _busy
                              ? null
                              : _link,
                          child: _busy
                              ? const SizedBox(
                                  width: 20,
                                  height: 20,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Text('绑定'),
                        ),
                        if (_linked) ...[
                          const SizedBox(height: 10),
                          const Callout(
                            key: ValueKey('parent.linked'),
                            tone: Tone.success,
                            announce: true,
                            child: Text('已经绑定。现在可以看这位学生每周的汇总了。'),
                          ),
                        ],
                        if (error != null) ...[
                          const SizedBox(height: 10),
                          Callout(
                            tone: alreadyLinked ? Tone.info : Tone.danger,
                            announce: true,
                            child: Text(describeError(error)),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: kGap),
                  Section(
                    title: '本机演示',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '原型阶段没有真实登录：这台设备上可以在学生和家长两个演示身份之间切换，'
                          '切回去还是原来的那一个。',
                          style: theme.textTheme.bodySmall,
                        ),
                        const SizedBox(height: 10),
                        OutlinedButton.icon(
                          key: const ValueKey('parent.switchToStudent'),
                          onPressed: _switching ? null : _switchToStudent,
                          icon: const Icon(Icons.swap_horiz),
                          label: const Text('切换到学生身份'),
                        ),
                      ],
                    ),
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

class _NoStudents extends StatelessWidget {
  const _NoStudents();

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const ValueKey('parent.empty'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('还没有学生授权给你。', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 6),
        const Text(
          '请学生在自己的「我的」页打开「家长查看」，点「生成邀请码」，'
          '把十位邀请码告诉你，再填在下面。没有学生的授权，这里不会出现任何学生的数据。',
        ),
      ],
    );
  }
}

class _StudentTile extends StatelessWidget {
  const _StudentTile({required this.student});

  final ParentStudent student;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        key: ValueKey('parent.student.${student.studentId}'),
        child: ListTile(
          onTap: () => context.push('/parent/weekly/${student.studentId}'),
          leading: const Icon(Icons.person_outline),
          title: Text(
            student.displayName ?? '学生 ${shortId(student.studentId)}',
          ),
          subtitle: Text('${monthDay(student.linkedAt)}授权 · 看每周汇总'),
          trailing: const Icon(Icons.chevron_right),
        ),
      ),
    );
  }
}
