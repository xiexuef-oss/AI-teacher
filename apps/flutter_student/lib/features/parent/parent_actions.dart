import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/providers.dart';
import '../../core/idempotency.dart';
import 'parent_command_store.dart';

final parentActionsProvider =
    AsyncNotifierProvider<ParentActions, ParentCommandBundle?>(
      ParentActions.new,
    );

/// Commands belong to the initiating owner and role; plaintext codes never enter state.
class ParentActions extends AsyncNotifier<ParentCommandBundle?> {
  AuthSession? _auth;
  ParentCommandStore? _store;
  int _epoch = 0;
  bool active(AuthSession auth, int epoch) {
    if (!ref.mounted) return false;
    final now = ref.read(authProvider).asData?.value;
    return epoch == _epoch &&
        now?.userId == auth.userId &&
        now?.token == auth.token &&
        now?.role == auth.role;
  }

  TutorApiClient client(AuthSession auth) => TutorApiClient(
    ApiCore(
      baseUrl: ref.read(apiBaseUrlProvider),
      transport: ref.read(apiTransportProvider),
      tokenProvider: () => auth.token,
    ),
  );
  @override
  Future<ParentCommandBundle?> build() async {
    final epoch = ++_epoch;
    final auth = await ref.watch(authProvider.future);
    if (!active(auth, epoch)) return null;
    _auth = auth;
    final store = ParentCommandStore(
      ref.read(keyValueStoreProvider),
      auth.userId,
      auth.role.value,
    );
    _store = store;
    final bundle = await store.read();
    return active(auth, epoch) ? bundle : null;
  }

  Future<void> publish(
    AuthSession auth,
    int epoch,
    ParentCommandStore store,
  ) async {
    final bundle = await store.read();
    if (active(auth, epoch)) state = AsyncData(bundle);
  }

  void check(AuthSession auth, int epoch) {
    if (!active(auth, epoch)) throw StateError('身份已变化，请重新打开页面');
  }

  Future<void> refresh() async {
    final auth = _auth!;
    final epoch = _epoch;
    final store = _store!;
    check(auth, epoch);
    final ticket = await store.beginRefresh();
    check(auth, epoch);
    final Object current;
    if (auth.role == LocalRole.student) {
      current = await client(auth).listParentLinks();
    } else {
      current = await client(auth).listParentStudents();
    }
    check(auth, epoch);
    await store.rememberCurrent(current, generation: ticket);
    await publish(auth, epoch, store);
  }

  Future<Object?> create(int revision) async {
    final auth = _auth!;
    final epoch = _epoch;
    final store = _store!;
    check(auth, epoch);
    final command = await store.prepareCreate(
      ParentInviteCreate(expectedParentInviteRevision: revision),
      key: newIdempotencyKey('parent-invite'),
      activeEpoch: epoch,
    );
    check(auth, epoch);
    await publish(auth, epoch, store);
    check(auth, epoch);
    return send(auth, epoch, store, command);
  }

  Future<Object?> revoke(ParentLink link) async {
    final auth = _auth!;
    final epoch = _epoch;
    final store = _store!;
    check(auth, epoch);
    if (link.authorizationRevision == null) throw StateError('授权版本未知，请联网刷新');
    final command = await store.prepareRevoke(
      link.id,
      ParentLinkRevoke(
        expectedAuthorizationRevision: link.authorizationRevision!,
      ),
      key: newIdempotencyKey('parent-revoke'),
      activeEpoch: epoch,
    );
    check(auth, epoch);
    await publish(auth, epoch, store);
    check(auth, epoch);
    return send(auth, epoch, store, command);
  }

  Future<Object?> redeem(String input) async {
    final auth = _auth!;
    final epoch = _epoch;
    final store = _store!;
    check(auth, epoch);
    final canonical = normalizeParentInviteCode(input);
    if (canonical == null) throw StateError('请输入有效的十位邀请码');
    final body = ParentInviteRedeem(code: canonical);
    final existing = (await store.read())?.active;
    check(auth, epoch);
    final command =
        existing ??
        await store.prepareRedeem(
          body,
          key: newIdempotencyKey('parent-redeem'),
          activeEpoch: epoch,
        );
    final original = await store.redeemBody(command.key, body);
    check(auth, epoch);
    await publish(auth, epoch, store);
    check(auth, epoch);
    return send(auth, epoch, store, command, redeemBody: original);
  }

  Future<Object?> retry({String? code}) async {
    final auth = _auth!;
    final epoch = _epoch;
    final store = _store!;
    check(auth, epoch);
    final command = (await store.read())?.active;
    check(auth, epoch);
    if (command == null || command.phase == 'conflict') {
      throw StateError('请先明确结束旧冲突');
    }
    if (command.kind == 'redeem') return redeem(code ?? '');
    return send(auth, epoch, store, command);
  }

  Future<Object?> replayInvite(String key) async {
    final auth = _auth!;
    final epoch = _epoch;
    final store = _store!;
    check(auth, epoch);
    final bundle = await store.read();
    check(auth, epoch);
    final command = bundle!.commands.firstWhere(
      (c) => c.key == key && c.kind == 'create',
    );
    return send(auth, epoch, store, command);
  }

  Future<void> acknowledgeHistory() async {
    final auth = _auth!;
    final epoch = _epoch;
    final store = _store!;
    check(auth, epoch);
    final command = state.asData?.value?.active;
    if (command == null || command.result == null) {
      throw StateError('没有可确认的历史结果');
    }
    await store.acknowledgeStoredResult(command.key);
    await publish(auth, epoch, store);
  }

  Future<void> finishConflict() async {
    final auth = _auth!;
    final epoch = _epoch;
    final store = _store!;
    check(auth, epoch);
    final bundle = state.asData?.value;
    final command = bundle?.active;
    if (command == null) return;
    await store.resolveConflict(command.key, generation: bundle!.generation);
    await publish(auth, epoch, store);
    if (active(auth, epoch)) await refresh();
  }

  Future<void> abandonUnknown() async {
    final auth = _auth!;
    final epoch = _epoch;
    final store = _store!;
    check(auth, epoch);
    final bundle = state.asData?.value;
    final command = bundle?.active;
    if (command == null) return;
    await store.abandonUnknown(command.key, generation: bundle!.generation);
    await publish(auth, epoch, store);
  }

  Future<Object?> send(
    AuthSession auth,
    int epoch,
    ParentCommandStore store,
    ParentCommand command, {
    ParentInviteRedeem? redeemBody,
  }) async {
    check(auth, epoch);
    Object result;
    try {
      switch (command.kind) {
        case 'create':
          result = await client(auth).createParentInvite(
            body: ParentInviteCreate.fromJson(command.body!),
            idempotencyKey: command.key,
          );
        case 'revoke':
          result = await client(auth).revokeParentLink(
            linkId: command.linkId!,
            body: ParentLinkRevoke.fromJson(command.body!),
            idempotencyKey: command.key,
          );
        case 'redeem':
          if (redeemBody == null) throw StateError('请重新输入原邀请码');
          result = await client(
            auth,
          ).redeemParentInvite(body: redeemBody, idempotencyKey: command.key);
        default:
          throw StateError('未知操作已保留');
      }
    } on ApiException catch (error) {
      if ([400, 404, 409, 422].contains(error.statusCode)) {
        Object? conflict;
        final links = error.details['server_parent_links'];
        final link = error.details['server_link'];
        if (command.kind == 'create' && links is Map<String, dynamic>) {
          conflict = ParentLinks.fromJson(links);
        }
        if (command.kind == 'revoke' && link is Map<String, dynamic>) {
          conflict = ParentLink.fromJson(link);
        }
        await store.reject(command.key, code: error.code, conflict: conflict);
        await publish(auth, epoch, store);
      }
      // Never expose raw error details which could contain a redeem code.
      throw ApiException(
        statusCode: error.statusCode,
        code: error.code,
        message: '操作未确认，请查看当前状态并重试原操作',
      );
    }
    await store.recordResult(command.key, result);
    await store.acknowledge(command.key);
    await publish(auth, epoch, store);
    if (!active(auth, epoch)) return null;
    // A new read updates only current, never the original command's CAS/body.
    try {
      await refresh();
    } on ApiException {
      if (result is ParentInvite) return null;
    }
    if (!active(auth, epoch)) return null;
    if (result is ParentInvite) {
      final current = state.asData?.value?.current;
      final pending = current?['pending_invite'] as Map?;
      if (!result.expiresAt.isAfter(ref.read(clockProvider)()) ||
          result.parentInviteRevision == null ||
          current?['parent_invite_revision'] != result.parentInviteRevision ||
          pending?['id'] != result.id) {
        return null;
      }
    }
    // Historical receipts do not replace the separately fetched current view.
    return result;
  }
}
