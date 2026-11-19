import 'dart:convert';

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

Map<String, dynamic> _persistedProfile(Map value) {
  final fields = _copy(value);
  // These fields are recomputed by the service from current configuration.
  fields.remove('notices');
  fields.remove('exam_scheme_code');
  fields.remove('onboarding_completed');
  return fields;
}

/// Local editable fields, deliberately independent of a server revision.
class ProfileEdit {
  ProfileEdit(Map<String, dynamic> fields) : _fields = _copy(fields) {
    _fields.remove('expected_revision');
    const allowed = {
      'region_code',
      'subjects',
      'grade',
      'exam_year',
      'curriculum_version',
      'display_name',
      'learning_settings',
      'learning_budget_edit',
    };
    if (_fields.keys.any((key) => !allowed.contains(key))) {
      throw ArgumentError('Unknown profile edit field');
    }
  }
  final Map<String, dynamic> _fields;
  Map<String, dynamic> toJson() => _copy(_fields);
}

class ProfileCommand {
  ProfileCommand._(Map value) : _json = _copy(value);
  final Map<String, dynamic> _json;
  String get idempotencyKey => _json['idempotencyKey'] as String;
  String get phase => _json['phase'] as String;
  int get editGeneration => _json['editGeneration'] as int;
  int get activeEpoch => _json['activeEpoch'] as int;
  String? get code => _json['code'] as String?;
  ProfileUpdate get body => ProfileUpdate.fromJson(_copy(_json['body'] as Map));
  StudentProfile? get result => _json['result'] == null
      ? null
      : StudentProfile.fromJson(_copy(_json['result'] as Map));
}

class ProfileBundle {
  ProfileBundle._(Map value) : _json = _copy(value);
  final Map<String, dynamic> _json;
  StudentProfile? get cloud => _json['cloud'] == null
      ? null
      : StudentProfile.fromJson(_copy(_json['cloud'] as Map));
  Map<String, dynamic>? get legacyProfile => _json['legacyProfile'] == null
      ? null
      : _copy(_json['legacyProfile'] as Map);
  int? get revision => (_json['cloud'] as Map?)?['revision'] as int?;
  Map<String, dynamic>? get edit =>
      _json['edit'] == null ? null : _copy(_json['edit'] as Map);
  int get editGeneration => _json['editGeneration'] as int;
  int? get editBaseRevision => _json['editBaseRevision'] as int?;
  bool get editConflict =>
      edit != null && revision != null && editBaseRevision != revision;
  List<ProfileCommand> get commands => [
    for (final item in _json['commands'] as List) ProfileCommand._(item as Map),
  ];
  ProfileCommand? get pending {
    for (final item in commands) {
      if (['prepared', 'result_known', 'conflict'].contains(item.phase)) {
        return item;
      }
    }
    return null;
  }
}

/// One owner/profile bundle is authoritative. No network work enters LocalSerial.
/// Failed writes propagate; callers must retain their in-memory form input.
class ProfileJournalStore {
  ProfileJournalStore(this.store, this.owner) {
    if (owner.isEmpty || owner.contains('/')) {
      throw ArgumentError('Invalid owner');
    }
  }
  final KeyValueStore store;
  final String owner;
  String get key => 'u/$owner/profile_bundle';
  Map<String, dynamic> _empty() => {
    'v': 1,
    'owner': owner,
    'editGeneration': 0,
    'editBaseRevision': null,
    'edit': null,
    'cloud': null,
    'legacyProfile': null,
    'commands': <dynamic>[],
  };

  void _profile(Map value) {
    if (value['user_id'] != owner ||
        value['revision'] is! int ||
        (value['revision'] as int) < 0) {
      throw const FormatException(
        'Unknown profile owner or revision preserved',
      );
    }
    StudentProfile.fromJson(_copy(value));
  }

  Future<Map<String, dynamic>?> _read() async {
    final raw = await store.read(key);
    if (raw == null) {
      final legacy = await store.read('u/$owner/profile');
      if (legacy == null) return null;
      final value = _copy(jsonDecode(legacy) as Map);
      if (value['user_id'] != owner) {
        throw const FormatException('Wrong legacy owner');
      }
      // Even a legacy projection containing revision is not authoritative.
      return _empty()..['legacyProfile'] = value;
    }
    try {
      final value = _copy(jsonDecode(raw) as Map);
      if (value['v'] != 1 ||
          value['owner'] != owner ||
          value['editGeneration'] is! int ||
          value['editGeneration'] < 0 ||
          value['commands'] is! List) {
        throw const FormatException('Unknown bundle');
      }
      if (value['cloud'] != null) _profile(value['cloud'] as Map);
      if (value['editBaseRevision'] != null &&
          (value['editBaseRevision'] is! int ||
              value['editBaseRevision'] < 0)) {
        throw const FormatException('Unknown edit source preserved');
      }
      if (value['edit'] != null) ProfileEdit(_copy(value['edit'] as Map));
      if (value['legacyProfile'] != null &&
          (value['legacyProfile'] as Map)['user_id'] != owner) {
        throw const FormatException('Wrong legacy owner');
      }
      final keys = <String>{};
      var pending = 0;
      for (final item in value['commands'] as List) {
        final c = item as Map;
        if (c['idempotencyKey'] is! String ||
            (c['idempotencyKey'] as String).isEmpty ||
            !keys.add(c['idempotencyKey'] as String) ||
            c['editGeneration'] is! int ||
            c['activeEpoch'] is! int ||
            ![
              'prepared',
              'result_known',
              'acked',
              'rejected',
              'conflict',
              'resolved',
            ].contains(c['phase'])) {
          throw const FormatException('Unknown command');
        }
        final body = _copy(c['body'] as Map);
        if (body['expected_revision'] is! int ||
            body['expected_revision'] < 0) {
          throw const FormatException('Unknown command revision');
        }
        if (_canonical(ProfileUpdate.fromJson(body).toJson()) !=
            _canonical(body)) {
          throw const FormatException('Unsupported command body preserved');
        }
        if (c['result'] != null) _profile(c['result'] as Map);
        if (['result_known', 'acked'].contains(c['phase']) &&
            c['result'] == null) {
          throw const FormatException('Missing receipt');
        }
        if (['prepared', 'result_known', 'conflict'].contains(c['phase'])) {
          pending++;
        }
      }
      if (pending > 1) {
        throw const FormatException('Multiple pending profile writes');
      }
      return value;
    } catch (_) {
      throw const FormatException(
        'Unknown or damaged profile bundle preserved',
      );
    }
  }

  Future<ProfileBundle?> read() => LocalSerial.run(store, key, () async {
    final value = await _read();
    return value == null ? null : ProfileBundle._(value);
  });

  Future<Map<String, dynamic>?> exportSnapshot() async {
    final bundle = await read();
    if (bundle == null) return null;
    return {
      'cloud': bundle.cloud?.toJson(),
      'legacy_profile': bundle.legacyProfile == null
          ? null
          : StudentProfile.fromJson(bundle.legacyProfile!).toJson(),
      'edit': bundle.edit == null ? null : ProfileEdit(bundle.edit!).toJson(),
      'edit_generation': bundle.editGeneration,
      'edit_base_revision': bundle.editBaseRevision,
      'commands': [
        for (final c in bundle.commands)
          {
            'key': c.idempotencyKey,
            'phase': c.phase,
            'edit_generation': c.editGeneration,
            'body': c.body.toJson(),
            'result': c.result?.toJson(),
            'error_code': c.code,
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

  void _merge(Map<String, dynamic> value, StudentProfile profile) {
    final next = profile.toJson();
    _profile(next);
    final old = value['cloud'] as Map?;
    if (old == null || next['revision'] > old['revision']) {
      value['cloud'] = next;
    } else if (next['revision'] == old['revision'] &&
        _canonical(_persistedProfile(next)) !=
            _canonical(_persistedProfile(old))) {
      throw StateError('Different profiles share a revision');
    }
  }

  Future<ProfileBundle> edit(ProfileEdit edit) => _change((value) {
    if (value['edit'] == null) {
      value['editBaseRevision'] = (value['cloud'] as Map?)?['revision'];
    }
    value['edit'] = edit.toJson();
    value['editGeneration'] = (value['editGeneration'] as int) + 1;
    return ProfileBundle._(value);
  });

  Future<void> rememberCloud(StudentProfile profile) => _change<void>((value) {
    _merge(value, profile);
  });

  Future<ProfileCommand> prepare(
    ProfileUpdate update, {
    required String idempotencyKey,
    required int activeEpoch,
  }) => _change((value) {
    final body = update.toJson();
    final commands = value['commands'] as List;
    for (final raw in commands) {
      final existing = raw as Map;
      if (existing['idempotencyKey'] == idempotencyKey) {
        if (_canonical(existing['body']) != _canonical(body)) {
          throw StateError('Idempotency key body mismatch');
        }
        return ProfileCommand._(existing);
      }
    }
    if (idempotencyKey.isEmpty ||
        activeEpoch < 0 ||
        commands.any(
          (c) => [
            'prepared',
            'result_known',
            'conflict',
          ].contains((c as Map)['phase']),
        )) {
      throw StateError('Unresolved profile command');
    }
    final revision = (value['cloud'] as Map?)?['revision'];
    if (revision == null ||
        value['editBaseRevision'] != revision ||
        body['expected_revision'] != revision ||
        value['edit'] == null ||
        _canonical(ProfileEdit(body).toJson()) != _canonical(value['edit'])) {
      throw StateError(
        'Prepare requires persisted edit and confirmed revision',
      );
    }
    final command = {
      'idempotencyKey': idempotencyKey,
      'body': body,
      'editGeneration': value['editGeneration'],
      'activeEpoch': activeEpoch,
      'phase': 'prepared',
    };
    commands.add(command);
    return ProfileCommand._(command);
  });

  Map _command(Map value, String key) {
    for (final item in value['commands'] as List) {
      if ((item as Map)['idempotencyKey'] == key) return item;
    }
    throw StateError('Unknown profile command');
  }

  Future<void> recordResult(String key, StudentProfile result) =>
      _change<void>((value) {
        final c = _command(value, key);
        if (!['prepared', 'result_known', 'acked'].contains(c['phase'])) {
          throw StateError('Command already rejected');
        }
        _profile(result.toJson());
        if (result.toJson()['revision'] !=
            (c['body'] as Map)['expected_revision'] + 1) {
          throw StateError('Receipt revision mismatch');
        }
        if (c['result'] != null &&
            _canonical(c['result']) != _canonical(result.toJson())) {
          throw StateError('Receipt mismatch');
        }
        final currentRevision = (value['cloud'] as Map?)?['revision'];
        if (value['edit'] != null &&
            value['editGeneration'] != c['editGeneration'] &&
            value['editBaseRevision'] ==
                (c['body'] as Map)['expected_revision'] &&
            (currentRevision == null || currentRevision <= result.revision)) {
          value['editBaseRevision'] = result.revision;
        }
        _merge(value, result);
        c['result'] = result.toJson();
        if (c['phase'] != 'acked') c['phase'] = 'result_known';
      });

  Future<void> acknowledge(String key) => _change<void>((value) {
    final c = _command(value, key);
    if (!['result_known', 'acked'].contains(c['phase'])) {
      throw StateError('No receipt');
    }
    c['phase'] = 'acked';
    if (c['editGeneration'] == value['editGeneration']) value['edit'] = null;
  });

  Future<void> reject(
    String key, {
    required String code,
    StudentProfile? cloud,
  }) => _change<void>((value) {
    final c = _command(value, key);
    if (c['phase'] != 'prepared') throw StateError('Command already completed');
    if (cloud != null) _merge(value, cloud);
    c['code'] = code;
    c['phase'] = code == 'profile_revision_conflict' ? 'conflict' : 'rejected';
  });

  /// Only call after the student explicitly chooses which side to retain.
  Future<void> resolveConflict(
    String key, {
    required int editGeneration,
    bool useCloud = false,
  }) => _change<void>((value) {
    if (value['editGeneration'] != editGeneration) {
      throw StateError('Profile edit changed during conflict choice');
    }
    final c = _command(value, key);
    if (c['phase'] != 'conflict' ||
        value['cloud'] == null ||
        (value['cloud'] as Map)['revision'] <=
            (c['body'] as Map)['expected_revision']) {
      throw StateError('No confirmed conflict sides');
    }
    c['phase'] = 'resolved';
    value['editBaseRevision'] = (value['cloud'] as Map)['revision'];
    if (useCloud) value['edit'] = null;
  });

  Future<void> resolveEditConflict({
    required int editGeneration,
    bool useCloud = false,
  }) => _change<void>((value) {
    if (value['editGeneration'] != editGeneration ||
        !ProfileBundle._(value).editConflict ||
        ProfileBundle._(value).pending != null) {
      throw StateError('No unchanged local edit conflict');
    }
    value['editBaseRevision'] = (value['cloud'] as Map)['revision'];
    if (useCloud) value['edit'] = null;
  });
}
