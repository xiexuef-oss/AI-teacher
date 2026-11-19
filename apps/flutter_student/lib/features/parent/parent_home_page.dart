import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/data.dart';
import '../../core/errors.dart';
import '../../core/format.dart';
import 'parent_actions.dart';
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
  int _serial = 0;
  bool _same(AuthSession owner) =>
      mounted &&
      ref.read(authProvider).asData?.value.userId == owner.userId &&
      ref.read(authProvider).asData?.value.token == owner.token &&
      ref.read(authProvider).asData?.value.role == owner.role;
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

  Future<void> _ackHistory() async {
    final owner = ref.read(authProvider).requireValue;
    final serial = _serial;
    try {
      await ref.read(parentActionsProvider.notifier).acknowledgeHistory();
      if (!_same(owner) || serial != _serial) return;
      setState(() {
        _linked = false;
        _error = null;
      });
    } catch (error) {
      if (_same(owner)) setState(() => _error = error);
    }
  }

  Future<void> _abandon() async {
    final owner = ref.read(authProvider).requireValue;
    final serial = _serial;
    final choice = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('保留未知记录，使用新邀请码？'),
        content: const Text(
          '旧请求可能已经绑定或稍后完成。这只停止本机重试，不会取消请求或撤销授权。请使用另一个新邀请码；学生仍可查看并撤销实际授权。',
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
    if (choice != true || !_same(owner) || serial != _serial) return;
    try {
      await ref.read(parentActionsProvider.notifier).abandonUnknown();
      if (_same(owner) && serial == _serial) setState(() => _linked = false);
    } catch (error) {
      if (_same(owner)) setState(() => _error = error);
    }
  }

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
    final code = _code.text;
    final owner = ref.read(authProvider).requireValue;
    final serial = _serial;
    if (code.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _linked = false;
    });
    // 同一个邀请码重试时复用同一个键；换了邀请码就是另一个动作
    try {
      final result = await ref
          .read(parentActionsProvider.notifier)
          .redeem(code);
      if (!_same(owner) || result == null) return;
      ref.invalidate(parentStudentsProvider);
      if (_same(owner) && serial == _serial) {
        _code.clear();
        setState(() => _linked = true);
      }
    } catch (error) {
      if (_same(owner)) setState(() => _error = error);
    } finally {
      if (_same(owner)) setState(() => _busy = false);
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
    final command = ref.watch(parentActionsProvider).asData?.value?.active;
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
                        // Keep the editable web semantics bounds on the field,
                        // separate from the surrounding Card's merged content.
                        Semantics(
                          container: true,
                          explicitChildNodes: true,
                          child: TextField(
                            key: const ValueKey('parent.code'),
                            controller: _code,
                            enabled: true,
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
                            onChanged: (_) => setState(() {
                              _serial++;
                              _linked = false;
                            }),
                            onSubmitted: (_) => _link(),
                          ),
                        ),
                        const SizedBox(height: 10),
                        FilledButton(
                          key: const ValueKey('parent.link'),
                          onPressed:
                              _code.text.trim().isEmpty ||
                                  _busy ||
                                  command?.phase == 'result_known'
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
                        if (command?.phase == 'result_known') ...[
                          const Text('已收到原绑定的成功回执；确认历史结果不代表当前仍有授权，无需重输邀请码或联网。'),
                          OutlinedButton(
                            key: const ValueKey('parent.ackResult'),
                            onPressed: _busy ? null : _ackHistory,
                            child: const Text('确认历史结果（不联网）'),
                          ),
                        ],
                        if (command != null &&
                            command.phase != 'result_known') ...[
                          const Text(
                            '有一笔绑定尚未确认。请重新输入原十位邀请码，重试会复用原请求；刷新学生列表不会确认该请求。',
                          ),
                          OutlinedButton(
                            key: const ValueKey('parent.retry'),
                            onPressed: _busy ? null : _link,
                            child: const Text('重输原码并重试'),
                          ),
                          if ([
                            'prepared',
                            'outcome_unavailable',
                          ].contains(command.phase))
                            OutlinedButton(
                              key: const ValueKey('parent.abandon'),
                              onPressed: _busy ? null : _abandon,
                              child: const Text('保留未知记录，使用新邀请码'),
                            ),
                        ],
                        if (_linked) ...[
                          const SizedBox(height: 10),
                          const Callout(
                            key: ValueKey('parent.linked'),
                            tone: Tone.success,
                            announce: true,
                            child: Text('原绑定操作已确认；目前可查看的学生以上方授权列表为准。'),
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
