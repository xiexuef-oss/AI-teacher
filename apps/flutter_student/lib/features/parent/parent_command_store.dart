import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/local_serial.dart';
import '../../core/storage.dart';

Map<String, dynamic> _copy(Map value) =>
    Map<String, dynamic>.from(jsonDecode(jsonEncode(value)) as Map);
String _canonical(dynamic value) {
  if (value is Map) {
    final keys = value.keys.cast<String>().toList()..sort();
    return '{${keys.map((k) => '${jsonEncode(k)}:${_canonical(value[k])}').join(',')}}';
  }
  if (value is List) return '[${value.map(_canonical).join(',')}]';
  return jsonEncode(value);
}

/// Matches Python re's Unicode whitespace; Dart's default \s differs.
String? normalizeParentInviteCode(String input) {
  final code = input
      .replaceAll(
        RegExp(
          r'[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000-]',
        ),
        '',
      )
      .toUpperCase();
  return RegExp(r'^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{10}$').hasMatch(code)
      ? code
      : null;
}

class ParentCommand {
  ParentCommand._(Map value) : _json = _copy(value);
  final Map<String, dynamic> _json;
  String get key => _json['key'] as String;
  String get kind => _json['kind'] as String;
  String get phase => _json['phase'] as String;
  String get retryDisposition => _json['retryDisposition'] as String;
  String get path => _json['path'] as String;
  String? get linkId => kind == 'revoke' ? path.split('/')[3] : null;
  bool get deliveryUnavailable => _json['deliveryUnavailable'] == true;
  int get generation => _json['generation'] as int;
  int get activeEpoch => _json['activeEpoch'] as int;
  String? get code => _json['code'] as String?;
  Map<String, dynamic>? get body =>
      _json['body'] == null ? null : _copy(_json['body'] as Map);
  Map<String, dynamic>? get result =>
      _json['result'] == null ? null : _copy(_json['result'] as Map);
  Map<String, dynamic>? get conflict =>
      _json['conflict'] == null ? null : _copy(_json['conflict'] as Map);
  bool get isActive =>
      retryDisposition == 'active' &&
      [
        'prepared',
        'result_known',
        'conflict',
        'outcome_unavailable',
      ].contains(phase);
}

class ParentCommandBundle {
  ParentCommandBundle._(Map value) : _json = _copy(value);
  final Map<String, dynamic> _json;
  int get generation => _json['generation'] as int;
  Map<String, dynamic>? get current =>
      _json['current'] == null ? null : _copy(_json['current'] as Map);
  List<ParentCommand> get commands => [
    for (final c in _json['commands'] as List) ParentCommand._(c as Map),
  ];
  ParentCommand? get active {
    for (final c in commands) {
      if (c.isActive) return c;
    }
    return null;
  }
}

/// One owner+role bundle; HTTP and cleartext codes never enter this store.
/// Callers retain input/token/API identity in memory and guard UI by auth epoch.
class ParentCommandStore {
  ParentCommandStore(this.store, this.owner, this.role) {
    if (owner.isEmpty ||
        owner.contains('/') ||
        !['student', 'parent'].contains(role)) {
      throw ArgumentError('Invalid parent command scope');
    }
  }
  final KeyValueStore store;
  final String owner, role;
  String get key => 'u/$owner/parent_authorization_bundle/$role';
  Map<String, dynamic> _empty() => {
    'v': 1,
    'owner': owner,
    'role': role,
    'generation': 0,
    'refreshGeneration': 0,
    'current': null,
    'commands': <dynamic>[],
  };

  Map<String, dynamic> _current(Object value) {
    if (role == 'student' && value is ParentLinks) return value.toJson();
    if (role == 'parent' && value is ParentStudents) return value.toJson();
    throw ArgumentError('Wrong current summary role');
  }

  Map<String, dynamic> _body(String kind, Map value) {
    Map<String, dynamic> generated;
    if (kind == 'create') {
      if (value['expected_parent_invite_revision'] is! int ||
          value['expected_parent_invite_revision'] < 0) {
        throw const FormatException('Invalid invite source revision');
      }
      generated = ParentInviteCreate.fromJson(_copy(value)).toJson();
    } else if (kind == 'revoke') {
      if (value['expected_authorization_revision'] is! int ||
          value['expected_authorization_revision'] < 1) {
        throw const FormatException('Invalid authorization source revision');
      }
      generated = ParentLinkRevoke.fromJson(_copy(value)).toJson();
    } else {
      throw const FormatException('Unknown command body');
    }
    if (_canonical(generated) != _canonical(value)) {
      throw const FormatException('Unsupported command body');
    }
    return generated;
  }

  void _keys(Map value, Set<String> allowed) {
    if (value.keys.any((k) => !allowed.contains(k))) {
      throw const FormatException('Unknown data preserved');
    }
  }

  Map<String, dynamic> _result(String kind, Object value) {
    if (kind == 'create' && value is ParentInvite) {
      return {
        'id': value.id,
        'created_at': value.createdAt.toUtc().toIso8601String(),
        'expires_at': value.expiresAt.toUtc().toIso8601String(),
        if (value.parentInviteRevision != null)
          'parent_invite_revision': value.parentInviteRevision,
      };
    }
    if (kind == 'revoke' && value is ParentLink) return value.toJson();
    if (kind == 'redeem' && value is ParentStudent) return value.toJson();
    throw ArgumentError('Unexpected command result');
  }

  void _validateResult(String kind, Map value) {
    Map<String, dynamic> parsed;
    if (kind == 'create') {
      _keys(value, {
        'id',
        'created_at',
        'expires_at',
        'parent_invite_revision',
      });
      if (value['id'] is! String) {
        throw const FormatException('Missing invite ID');
      }
      DateTime.parse(value['created_at'] as String);
      DateTime.parse(value['expires_at'] as String);
      if (value['parent_invite_revision'] != null &&
          (value['parent_invite_revision'] is! int ||
              value['parent_invite_revision'] < 0)) {
        throw const FormatException('Unknown receipt revision');
      }
      return;
    } else if (kind == 'revoke') {
      parsed = ParentLink.fromJson(_copy(value)).toJson();
    } else {
      parsed = ParentStudent.fromJson(_copy(value)).toJson();
    }
    if (_canonical(parsed) != _canonical(value)) {
      throw const FormatException('Unknown receipt fields preserved');
    }
  }

  Future<Map<String, dynamic>?> _read() async {
    final raw = await store.read(key);
    if (raw == null) return null;
    try {
      final value = _copy(jsonDecode(raw) as Map);
      _keys(value, {
        'v',
        'owner',
        'role',
        'generation',
        'refreshGeneration',
        'current',
        'commands',
      });
      if (value['v'] != 1 ||
          value['owner'] != owner ||
          value['role'] != role ||
          value['generation'] is! int ||
          value['generation'] < 0 ||
          value['refreshGeneration'] is! int ||
          value['refreshGeneration'] < 0 ||
          value['commands'] is! List) {
        throw const FormatException('Unknown bundle');
      }
      if (value['current'] != null) {
        final current = value['current'] as Map;
        final parsed = role == 'student'
            ? ParentLinks.fromJson(_copy(current))
            : ParentStudents.fromJson(_copy(current));
        if (_canonical(_current(parsed)) != _canonical(current)) {
          throw const FormatException('Unknown current');
        }
      }
      final seen = <String>{};
      var active = 0;
      for (final item in value['commands'] as List) {
        final c = item as Map;
        _keys(c, {
          'key',
          'kind',
          'path',
          'generation',
          'activeEpoch',
          'phase',
          'retryDisposition',
          'body',
          'salt',
          'fingerprint',
          'result',
          'code',
          'deliveryUnavailable',
          'conflict',
        });
        if (c['key'] is! String ||
            !seen.add(c['key'] as String) ||
            c['generation'] is! int ||
            c['generation'] < 1 ||
            c['activeEpoch'] is! int ||
            c['activeEpoch'] < 0 ||
            ![
              'prepared',
              'result_known',
              'acked',
              'rejected',
              'conflict',
              'resolved',
              'outcome_unavailable',
            ].contains(c['phase']) ||
            !['active', 'abandoned_unknown'].contains(c['retryDisposition'])) {
          throw const FormatException('Unknown command');
        }
        final kind = c['kind'];
        if (role == 'student' &&
                kind == 'create' &&
                c['path'] == '/me/parent-invites' ||
            role == 'student' &&
                kind == 'revoke' &&
                c['path'] is String &&
                RegExp(r'^/me/parent-links/[A-Za-z0-9._:-]+/revoke$')
                    .hasMatch(c['path'] as String)) {
          _body(kind as String, c['body'] as Map);
          if (c.containsKey('salt') || c.containsKey('fingerprint')) {
            throw const FormatException('Wrong command credential');
          }
        } else if (role == 'parent' &&
            kind == 'redeem' &&
            c['path'] == '/parents/links') {
          if (c.containsKey('body') ||
              c['salt'] is! String ||
              base64Decode(c['salt'] as String).length != 32 ||
              c['fingerprint'] is! String ||
              !RegExp(r'^[a-f0-9]{64}$').hasMatch(c['fingerprint'] as String)) {
            throw const FormatException('Unsupported redeem preserved');
          }
        } else {
          throw const FormatException('Wrong command role/path');
        }
        if (c['result'] != null) {
          _validateResult(kind as String, c['result'] as Map);
        }
        if (c['conflict'] != null) {
          final conflict = c['conflict'] as Map;
          final parsed = kind == 'create'
              ? ParentLinks.fromJson(_copy(conflict)).toJson()
              : kind == 'revoke'
              ? ParentLink.fromJson(_copy(conflict)).toJson()
              : null;
          if (parsed == null || _canonical(parsed) != _canonical(conflict)) {
            throw const FormatException('Unsupported conflict summary');
          }
        }
        if (['result_known', 'acked'].contains(c['phase']) &&
            c['result'] == null) {
          throw const FormatException('Missing result');
        }
        if (ParentCommand._(c).isActive) active++;
      }
      if (active > 1) throw const FormatException('Multiple active commands');
      return value;
    } catch (_) {
      throw const FormatException('Unknown or damaged parent bundle preserved');
    }
  }

  Future<ParentCommandBundle?> read() => LocalSerial.run(store, key, () async {
    final value = await _read();
    return value == null ? null : ParentCommandBundle._(value);
  });

  Map<String, dynamic> _exportLink(Map<String, dynamic> value) {
    final link = ParentLink.fromJson(value);
    return {
      'id': link.id,
      'authorization_revision': link.authorizationRevision,
      'consent_at': link.consentAt.toUtc().toIso8601String(),
      'linked_at': link.linkedAt.toUtc().toIso8601String(),
      'revoked_at': link.revokedAt?.toUtc().toIso8601String(),
    };
  }

  Map<String, dynamic> _exportLinks(Map<String, dynamic> value) {
    final links = ParentLinks.fromJson(value);
    return {
      'parent_invite_revision': links.parentInviteRevision,
      'pending_invite': links.pendingInvite?.toJson(),
      'links': [for (final link in links.links) _exportLink(link.toJson())],
    };
  }

  Future<Map<String, dynamic>?> exportStudentSnapshot() async {
    if (role != 'student') {
      throw StateError('Student authorization export only');
    }
    final bundle = await read();
    if (bundle == null) return null;
    return {
      'generation': bundle.generation,
      'current': bundle.current == null ? null : _exportLinks(bundle.current!),
      'commands': [
        for (final c in bundle.commands)
          {
            'key': c.key,
            'kind': c.kind,
            'link_id': c.linkId,
            'phase': c.phase,
            'retry_disposition': c.retryDisposition,
            'generation': c.generation,
            'body': _body(c.kind, c.body!),
            'result': c.result == null
                ? null
                : c.kind == 'create'
                ? {
                    for (final name in [
                      'id',
                      'created_at',
                      'expires_at',
                      'parent_invite_revision',
                    ])
                      if (c.result!.containsKey(name)) name: c.result![name],
                  }
                : _exportLink(c.result!),
            'conflict': c.conflict == null
                ? null
                : c.kind == 'create'
                ? _exportLinks(c.conflict!)
                : _exportLink(c.conflict!),
            'error_code': c.code,
            'delivery_unavailable': c.deliveryUnavailable,
          },
      ],
    };
  }

  Future<T> _change<T>(T Function(Map<String, dynamic>) action) =>
      LocalSerial.run(store, key, () async {
        final value = await _read() ?? _empty();
        final result = action(value);
        await store.write(key, jsonEncode(value));
        return result;
      });
  Future<int> beginRefresh() => _change((value) {
    value['refreshGeneration'] = (value['refreshGeneration'] as int) + 1;
    return value['refreshGeneration'] as int;
  });
  Future<void> rememberCurrent(Object summary, {required int generation}) =>
      _change<void>((value) {
        if (generation != value['refreshGeneration']) return;
        value['current'] = _current(summary);
      });

  String _fingerprint(String salt, String code) => sha256
      .convert(
        utf8.encode(
          _canonical({
            'domain': 'parent-redeem/v1',
            'salt': salt,
            'owner': owner,
            'role': role,
            'method': 'POST',
            'path': '/parents/links',
            'body': ParentInviteRedeem(code: code).toJson(),
          }),
        ),
      )
      .toString();

  Future<ParentCommand> prepareCreate(
    ParentInviteCreate body, {
    required String key,
    required int activeEpoch,
  }) =>
      _prepare('create', '/me/parent-invites', body.toJson(), key, activeEpoch);
  Future<ParentCommand> prepareRevoke(
    String linkId,
    ParentLinkRevoke body, {
    required String key,
    required int activeEpoch,
  }) {
    if (!RegExp(r'^[A-Za-z0-9._:-]+$').hasMatch(linkId)) {
      throw ArgumentError('Invalid link ID');
    }
    return _prepare(
      'revoke',
      '/me/parent-links/$linkId/revoke',
      body.toJson(),
      key,
      activeEpoch,
    );
  }

  Future<ParentCommand> prepareRedeem(
    ParentInviteRedeem body, {
    required String key,
    required int activeEpoch,
  }) => _prepare('redeem', '/parents/links', body.toJson(), key, activeEpoch);

  Future<ParentCommand> _prepare(
    String kind,
    String path,
    Map<String, dynamic> input,
    String commandKey,
    int epoch,
  ) => _change((value) {
    if (!RegExp(r'^[A-Za-z0-9._:-]{8,128}$').hasMatch(commandKey) ||
        epoch < 0 ||
        (kind == 'redeem' ? role != 'parent' : role != 'student')) {
      throw ArgumentError('Invalid command scope');
    }
    final code = kind == 'redeem'
        ? normalizeParentInviteCode(input['code'] as String)
        : null;
    if (kind == 'redeem' && code == null) {
      throw const FormatException('Invalid invite code');
    }
    final body = kind == 'redeem' ? null : _body(kind, input);
    for (final item in value['commands'] as List) {
      final c = item as Map;
      final sameInput = kind == 'redeem' && c['kind'] == 'redeem'
          ? _fingerprint(c['salt'] as String, code!) == c['fingerprint']
          : c['kind'] == kind &&
                c['path'] == path &&
                _canonical(c['body']) == _canonical(body);
      if (c['key'] == commandKey) {
        if (!sameInput) throw StateError('Command key/body mismatch');
        return ParentCommand._(c);
      }
      if (kind == 'redeem' &&
          sameInput &&
          c['retryDisposition'] == 'abandoned_unknown') {
        throw StateError('Use original command to recover the same code');
      }
    }
    if (ParentCommandBundle._(value).active != null) {
      throw StateError('Unresolved active command');
    }
    final current = value['current'] as Map?;
    if (kind == 'create' &&
        (current == null ||
            current['parent_invite_revision'] == null ||
            current['parent_invite_revision'] !=
                body!['expected_parent_invite_revision'])) {
      throw StateError('Unknown or changed invitation source');
    }
    if (kind == 'revoke') {
      Map? link;
      for (final item in current?['links'] as List? ?? []) {
        if ((item as Map)['id'] == path.split('/')[3]) link = item;
      }
      if (link == null ||
          link['authorization_revision'] == null ||
          link['revoked_at'] != null ||
          link['authorization_revision'] !=
              body!['expected_authorization_revision']) {
        throw StateError('Unknown or changed authorization source');
      }
    }
    value['generation'] = (value['generation'] as int) + 1;
    final c = <String, dynamic>{
      'key': commandKey,
      'kind': kind,
      'path': path,
      'generation': value['generation'],
      'activeEpoch': epoch,
      'phase': 'prepared',
      'retryDisposition': 'active',
    };
    if (body != null) {
      c['body'] = body;
    } else {
      final random = Random.secure();
      final salt = base64Encode(
        List<int>.generate(32, (_) => random.nextInt(256)),
      );
      c['salt'] = salt;
      c['fingerprint'] = _fingerprint(salt, code!);
    }
    (value['commands'] as List).add(c);
    return ParentCommand._(c);
  });

  Map _command(Map value, String key) {
    for (final item in value['commands'] as List) {
      if ((item as Map)['key'] == key) return item;
    }
    throw StateError('Unknown parent command');
  }

  Future<ParentInviteRedeem> redeemBody(String key, ParentInviteRedeem input) =>
      LocalSerial.run(store, this.key, () async {
        final value = await _read();
        if (value == null) throw StateError('Missing redeem command');
        final c = _command(value, key);
        final code = normalizeParentInviteCode(input.code);
        if (c['kind'] != 'redeem' ||
            code == null ||
            _fingerprint(c['salt'] as String, code) != c['fingerprint']) {
          throw StateError('Re-enter the original invitation code');
        }
        return ParentInviteRedeem(code: code);
      });

  Future<void> recordResult(String key, Object response) => _change<void>((
    value,
  ) {
    final c = _command(value, key);
    if (![
      'prepared',
      'result_known',
      'acked',
      'outcome_unavailable',
    ].contains(c['phase'])) {
      throw StateError('Command already rejected');
    }
    final result = _result(c['kind'] as String, response);
    _validateResult(c['kind'] as String, result);
    if (c['kind'] == 'create' &&
        result['parent_invite_revision'] != null &&
        result['parent_invite_revision'] !=
            (c['body'] as Map)['expected_parent_invite_revision'] + 1) {
      throw StateError('Receipt version mismatch');
    }
    if (c['kind'] == 'revoke' &&
        (result['id'] != (c['path'] as String).split('/')[3] ||
            result['authorization_revision'] != null &&
                result['authorization_revision'] !=
                    (c['body'] as Map)['expected_authorization_revision'] +
                        1)) {
      throw StateError('Receipt link/version mismatch');
    }
    if (c['result'] != null && _canonical(c['result']) != _canonical(result)) {
      throw StateError('Receipt mismatch');
    }
    c['result'] = result;
    if (c['phase'] != 'acked') c['phase'] = 'result_known';
  });

  /// Confirms only a validated, persisted historical success. Requires neither
  /// an invitation code nor HTTP; a current GET never supplies this evidence.
  /// Confirming a create result does not promise that its code remains usable.
  Future<void> acknowledgeStoredResult(String key) => acknowledge(key);

  Future<void> acknowledge(String key) => _change<void>((value) {
    final c = _command(value, key);
    if (c['result'] == null ||
        !['result_known', 'acked'].contains(c['phase'])) {
      throw StateError('No successful receipt');
    }
    c['phase'] = 'acked';
  });
  Future<void> reject(
    String key, {
    required String code,
    Object? conflict,
  }) => _change<void>((value) {
    final c = _command(value, key);
    // Store only fixed symbolic errors, never error payloads that may echo codes.
    const known = {
      'invite_invalid',
      'already_linked',
      'validation_error',
      'parent_invite_revision_conflict',
      'authorization_revision_conflict',
      'invite_response_expired',
    };
    if (!known.contains(code)) throw ArgumentError('Unknown rejection code');
    if (code == 'invite_response_expired') {
      if (c['kind'] != 'create') throw StateError('Wrong sensitive replay');
      c['deliveryUnavailable'] = true;
      if (c['result'] == null) c['phase'] = 'outcome_unavailable';
      return;
    }
    if (c['phase'] != 'prepared') throw StateError('Command already completed');
    c['code'] = code;
    if (conflict != null) {
      if (c['kind'] == 'create' && conflict is ParentLinks) {
        c['conflict'] = conflict.toJson();
      } else if (c['kind'] == 'revoke' &&
          conflict is ParentLink &&
          conflict.id == (c['path'] as String).split('/')[3]) {
        c['conflict'] = conflict.toJson();
      } else {
        throw ArgumentError('Unexpected conflict summary');
      }
    }
    c['phase'] = code.endsWith('_revision_conflict') ? 'conflict' : 'rejected';
  });
  Future<void> abandonUnknown(String key, {required int generation}) =>
      _change<void>((value) {
        final c = _command(value, key);
        if (c['generation'] != generation ||
            !['prepared', 'outcome_unavailable'].contains(c['phase'])) {
          throw StateError('Command changed');
        }
        c['retryDisposition'] = 'abandoned_unknown';
      });

  /// Explicitly closes a conflict after the user compares the current sides.
  Future<void> resolveConflict(String key, {required int generation}) =>
      _change<void>((value) {
        final c = _command(value, key);
        if (c['generation'] != generation || c['phase'] != 'conflict') {
          throw StateError('Conflict changed');
        }
        c['phase'] = 'resolved';
      });
}
