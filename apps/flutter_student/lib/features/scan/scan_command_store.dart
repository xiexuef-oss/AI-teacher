import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/local_serial.dart';
import '../../core/storage.dart';

Map<String, dynamic> _copy(Map v) =>
    Map<String, dynamic>.from(jsonDecode(jsonEncode(v)) as Map);
String _canonical(dynamic v) {
  if (v is Map) {
    final keys = v.keys.cast<String>().toList()..sort();
    return '{${keys.map((k) => '${jsonEncode(k)}:${_canonical(v[k])}').join(',')}}';
  }
  if (v is List) return '[${v.map(_canonical).join(',')}]';
  return jsonEncode(v);
}

String _hash(dynamic v) =>
    sha256.convert(utf8.encode(_canonical(v))).toString();
void _keys(Map v, Set<String> allowed) {
  if (v.keys.any((k) => !allowed.contains(k))) {
    throw const FormatException('Unknown scan data preserved');
  }
}

class ScanCommand {
  ScanCommand._(Map v) : _j = _copy(v);
  final Map<String, dynamic> _j;
  String get key => _j['key'] as String;
  String get workspaceId => _j['workspaceId'] as String;
  String get kind => _j['kind'] as String;
  String get phase => _j['phase'] as String;
  int get editGeneration => _j['editGeneration'] as int;
  int get activeEpoch => _j['activeEpoch'] as int;
  String get path => _j['path'] as String;
  String? get mediaId {
    if (kind == 'content') return path.split('/')[3];
    if (kind == 'create') return body!['media_id'] as String;
    return null;
  }

  String? get scanId => kind == 'confirm' ? path.split('/')[2] : null;
  Map<String, dynamic>? get body =>
      _j['body'] == null ? null : _copy(_j['body'] as Map);
  Map<String, dynamic>? get result =>
      _j['result'] == null ? null : _copy(_j['result'] as Map);
}

class ScanWorkspace {
  ScanWorkspace._(Map v) : _j = _copy(v);
  final Map<String, dynamic> _j;
  String get id => _j['id'] as String;
  String get stem => _j['stem'] as String;
  String get expressions => _j['expressions'] as String;
  int get editGeneration => _j['editGeneration'] as int;
  String? get mediaId => _j['mediaId'] as String?;
  String? get scanId => _j['scanId'] as String?;
  String? get legacyMediaId => _j['legacyMediaId'] as String?;
  String? get legacyScanId => _j['legacyScanId'] as String?;
  Map<String, dynamic>? get observation =>
      _j['observation'] == null ? null : _copy(_j['observation'] as Map);
  List<ScanCommand> get commands => [
    for (final c in _j['commands'] as List) ScanCommand._(c as Map),
  ];
  ScanCommand? get active {
    for (final c in commands) {
      if (['prepared', 'result_known', 'unavailable'].contains(c.phase)) {
        return c;
      }
    }
    return null;
  }

  Map<String, dynamic>? get uploadMetadata {
    for (final c in commands) {
      if (c.kind == 'upload' && c.result != null) return c.result;
    }
    return null;
  }

  Map<String, dynamic>? get confirmation {
    for (final c in commands.reversed) {
      if (c.kind == 'confirm' &&
          c.phase == 'acked' &&
          c.editGeneration == editGeneration) {
        return c.result;
      }
    }
    return null;
  }
}

class ScanBundle {
  ScanBundle._(Map v) : _j = _copy(v);
  final Map<String, dynamic> _j;
  String? get activeWorkspaceId => _j['activeWorkspaceId'] as String?;
  List<ScanWorkspace> get workspaces => [
    for (final w in _j['workspaces'] as List) ScanWorkspace._(w as Map),
  ];
  ScanWorkspace workspace(String id) =>
      workspaces.firstWhere((w) => w.id == id);
}

class ScanWorkspaceStore {
  ScanWorkspaceStore(this.store, this.owner) {
    if (owner.isEmpty || owner.contains('/')) {
      throw ArgumentError('Invalid scan owner');
    }
  }
  final KeyValueStore store;
  final String owner;
  String get key => 'u/$owner/scan_workspace_bundle';
  String get legacyKey => 'scan.${Uri.encodeComponent(owner)}.draft';
  Map<String, dynamic> _empty() => {
    'v': 1,
    'owner': owner,
    'activeWorkspaceId': null,
    'workspaces': <dynamic>[],
  };
  Map<String, dynamic> _workspace(String id) => {
    'id': id,
    'stem': '',
    'expressions': '',
    'editGeneration': 0,
    'observationGeneration': 0,
    'commands': <dynamic>[],
  };
  Map _find(Map bundle, String id) => (bundle['workspaces'] as List)
      .cast<Map>()
      .firstWhere((w) => w['id'] == id);
  Map _command(Map bundle, String key) {
    for (final w in bundle['workspaces'] as List) {
      for (final c in (w as Map)['commands'] as List) {
        if ((c as Map)['key'] == key) return c;
      }
    }
    throw StateError('Unknown scan command');
  }

  Map<String, dynamic> _body(String kind, Map v) => switch (kind) {
    'upload' => MediaUploadRequest.fromJson(_copy(v)).toJson(),
    'create' => ScanCreate.fromJson(_copy(v)).toJson(),
    'confirm' => ScanConfirm.fromJson(_copy(v)).toJson(),
    _ => throw const FormatException('Unsupported scan body'),
  };
  Map<String, dynamic> _result(String kind, Map v) => switch (kind) {
    'upload' => MediaUpload.fromJson(_copy(v)).toJson(),
    'content' => MediaAssetInfo.fromJson(_copy(v)).toJson(),
    'create' => Scan.fromJson(_copy(v)).toJson(),
    'confirm' => ScanConfirmation.fromJson(_copy(v)).toJson(),
    _ => throw const FormatException('Unsupported scan result'),
  };
  Future<Map<String, dynamic>?> _read() async {
    final raw = await store.read(key);
    if (raw == null) {
      final legacy = await store.read(legacyKey);
      if (legacy == null) return null;
      try {
        final old = _copy(jsonDecode(legacy) as Map);
        _keys(old, {
          'version',
          'stem',
          'expressions',
          'scan_id',
          'media_id',
          'had_image',
          'picker_pending',
          'keys',
        });
        if (old['version'] != 1 ||
            old['stem'] is! String ||
            old['expressions'] is! String ||
            old['had_image'] is! bool ||
            old['picker_pending'] is! bool ||
            old['keys'] is! Map ||
            (old['keys'] as Map).entries.any(
              (e) => e.key is! String || e.value is! String,
            ) ||
            (old['scan_id'] != null && old['scan_id'] is! String) ||
            (old['media_id'] != null && old['media_id'] is! String)) {
          throw const FormatException('Invalid legacy');
        }
        final hash = sha256.convert(utf8.encode(legacy)).toString();
        final w = _workspace('legacy-${hash.substring(0, 16)}')
          ..addAll({
            'stem': old['stem'],
            'expressions': old['expressions'],
            'legacyScanId': old['scan_id'],
            'legacyMediaId': old['media_id'],
            'legacyKey': legacyKey,
            'legacyHash': hash,
          });
        return _empty()
          ..['activeWorkspaceId'] = w['id']
          ..['workspaces'] = [w];
      } catch (_) {
        throw const FormatException('Unknown legacy scan preserved');
      }
    }
    try {
      final b = _copy(jsonDecode(raw) as Map);
      _keys(b, {'v', 'owner', 'activeWorkspaceId', 'workspaces'});
      if (b['v'] != 1 || b['owner'] != owner || b['workspaces'] is! List) {
        throw const FormatException('Invalid scope');
      }
      final ids = <String>{}, commandKeys = <String>{};
      for (final item in b['workspaces'] as List) {
        final w = item as Map;
        _keys(w, {
          'id',
          'stem',
          'expressions',
          'editGeneration',
          'observationGeneration',
          'commands',
          'mediaId',
          'scanId',
          'observation',
          'legacyScanId',
          'legacyMediaId',
          'legacyKey',
          'legacyHash',
        });
        if (w['id'] is! String ||
            !ids.add(w['id'] as String) ||
            w['stem'] is! String ||
            w['expressions'] is! String ||
            w['editGeneration'] is! int ||
            w['observationGeneration'] is! int ||
            w['commands'] is! List) {
          throw const FormatException('Invalid workspace');
        }
        var active = 0;
        for (final c in w['commands'] as List) {
          final j = c as Map;
          _keys(j, {
            'key',
            'workspaceId',
            'kind',
            'phase',
            'path',
            'editGeneration',
            'activeEpoch',
            'body',
            'sha256',
            'sizeBytes',
            'wireFingerprint',
            'result',
            'code',
          });
          if (j['workspaceId'] != w['id'] ||
              j['key'] is! String ||
              !commandKeys.add(j['key'] as String) ||
              j['editGeneration'] is! int ||
              j['activeEpoch'] is! int ||
              ![
                'prepared',
                'result_known',
                'acked',
                'unavailable',
                'rejected',
              ].contains(j['phase'])) {
            throw const FormatException('Invalid command');
          }
          if (j['kind'] == 'content') {
            if (j.containsKey('body') ||
                j['sha256'] is! String ||
                j['sizeBytes'] is! int ||
                j['wireFingerprint'] is! String) {
              throw const FormatException('Invalid image reference');
            }
          } else if (_canonical(_body(j['kind'] as String, j['body'] as Map)) !=
              _canonical(j['body'])) {
            throw const FormatException('Unknown body');
          }
          if (j['result'] != null &&
              _canonical(_result(j['kind'] as String, j['result'] as Map)) !=
                  _canonical(j['result'])) {
            throw const FormatException('Unknown receipt');
          }
          if (['result_known', 'acked'].contains(j['phase']) &&
              j['result'] == null) {
            throw const FormatException('Missing receipt');
          }
          if ([
            'prepared',
            'result_known',
            'unavailable',
          ].contains(j['phase'])) {
            active++;
          }
        }
        final commands = (w['commands'] as List).cast<Map>();
        final uploads = commands.where(
          (c) => c['kind'] == 'upload' && c['result'] != null,
        );
        final creates = commands.where(
          (c) => c['kind'] == 'create' && c['result'] != null,
        );
        if (w['mediaId'] != null &&
            (uploads.isEmpty ||
                (uploads.last['result'] as Map)['media_id'] != w['mediaId'])) {
          throw const FormatException('Unbound media ID');
        }
        if (w['scanId'] != null &&
            (creates.isEmpty ||
                (creates.last['result'] as Map)['id'] != w['scanId'])) {
          throw const FormatException('Unbound scan ID');
        }
        if (w['observation'] != null) {
          final observation = w['observation'] as Map;
          if (observation['id'] != (w['scanId'] ?? w['legacyScanId']) ||
              _canonical(Scan.fromJson(_copy(observation)).toJson()) !=
                  _canonical(observation)) {
            throw const FormatException('Wrong observed scan');
          }
        }
        for (final c in commands) {
          final expectedPath = switch (c['kind']) {
            'upload' => '/scans/uploads',
            'content' => '/scans/uploads/${w['mediaId']}/content',
            'create' => '/scans',
            'confirm' =>
              '/scans/${w['scanId'] ?? (w['observation'] as Map?)?['id']}/confirm',
            _ => null,
          };
          if (expectedPath == null || c['path'] != expectedPath) {
            throw const FormatException('Wrong command resource path');
          }
        }
        if (active > 1) {
          throw const FormatException('Multiple pending commands');
        }
      }
      if (b['activeWorkspaceId'] != null &&
          !ids.contains(b['activeWorkspaceId'])) {
        throw const FormatException('Unknown active workspace');
      }
      return b;
    } catch (_) {
      throw const FormatException('Unknown scan bundle preserved');
    }
  }

  Future<ScanBundle?> read() => LocalSerial.run(store, key, () async {
    final b = await _read();
    return b == null ? null : ScanBundle._(b);
  });

  Future<Map<String, dynamic>> exportSnapshot() async {
    final bundle = await read();
    return {
      'format_version': 1,
      'scope': 'local_scan_records',
      'owner_id': owner,
      'active_workspace_id': bundle?.activeWorkspaceId,
      'workspaces': [
        for (final w in bundle?.workspaces ?? <ScanWorkspace>[])
          {
            'id': w.id,
            'stem_text': w.stem,
            'expression_text': w.expressions,
            'edit_generation': w.editGeneration,
            'media_id': w.mediaId,
            'scan_id': w.scanId,
            'legacy_media_id': w.legacyMediaId,
            'legacy_scan_id': w.legacyScanId,
            'observation': w.observation == null
                ? null
                : Scan.fromJson(w.observation!).toJson(),
            'commands': [
              for (final c in w.commands)
                {
                  'key': c.key,
                  'kind': c.kind,
                  'phase': c.phase,
                  'path': c.path,
                  'edit_generation': c.editGeneration,
                  'body': c.body == null ? null : _body(c.kind, c.body!),
                  'result': c.result == null
                      ? null
                      : (_result(c.kind, c.result!)..remove('upload_url')),
                  'code': c._j['code'] as String?,
                  'image_sha256': c._j['sha256'] as String?,
                  'image_size_bytes': c._j['sizeBytes'] as int?,
                },
            ],
          },
      ],
    };
  }

  Future<T> _change<T>(T Function(Map<String, dynamic>) action) =>
      LocalSerial.run(store, key, () async {
        final b = await _read() ?? _empty();
        final result = action(b);
        await store.write(key, jsonEncode(b));
        return result;
      });
  Future<ScanWorkspace> createWorkspace(String id) => _change((b) {
    if (!RegExp(r'^[A-Za-z0-9._:-]+$').hasMatch(id) ||
        (b['workspaces'] as List).any((w) => (w as Map)['id'] == id)) {
      throw StateError('Invalid or reused local workspace');
    }
    final w = _workspace(id);
    (b['workspaces'] as List).add(w);
    b['activeWorkspaceId'] = id;
    return ScanWorkspace._(w);
  });
  Future<ScanWorkspace> edit(
    String id, {
    required String stem,
    required String expressions,
  }) => _change((b) {
    final w = _find(b, id);
    w['stem'] = stem;
    w['expressions'] = expressions;
    w['editGeneration'] = (w['editGeneration'] as int) + 1;
    return ScanWorkspace._(w);
  });
  Future<ScanCommand> prepare(
    String id,
    String kind,
    Object generatedBody, {
    required String key,
    required int activeEpoch,
  }) => _change((b) {
    final w = _find(b, id);
    final body = switch (generatedBody) {
      MediaUploadRequest v => v.toJson(),
      MediaBlobUpload v => v.toJson(),
      ScanCreate v => v.toJson(),
      ScanConfirm v => v.toJson(),
      _ => throw ArgumentError('Generated scan body required'),
    };
    final expectedType = kind == 'upload'
        ? generatedBody is MediaUploadRequest
        : kind == 'content'
        ? generatedBody is MediaBlobUpload
        : kind == 'create'
        ? generatedBody is ScanCreate
        : kind == 'confirm' && generatedBody is ScanConfirm;
    if (!expectedType ||
        !RegExp(r'^[A-Za-z0-9._:-]{8,128}$').hasMatch(key) ||
        activeEpoch < 0) {
      throw ArgumentError('Invalid scan command');
    }
    final path = switch (kind) {
      'upload' => '/scans/uploads',
      'content' => '/scans/uploads/${w['mediaId']}/content',
      'create' => '/scans',
      'confirm' =>
        '/scans/${w['scanId'] ?? (w['observation'] as Map?)?['id']}/confirm',
      _ => throw ArgumentError('Invalid action'),
    };
    for (final other in b['workspaces'] as List) {
      for (final raw in (other as Map)['commands'] as List) {
        final c = raw as Map;
        if (c['key'] == key) {
          if (c['workspaceId'] != id ||
              c['kind'] != kind ||
              c['path'] != path ||
              (kind == 'content'
                  ? c['wireFingerprint'] != _hash(body)
                  : _canonical(c['body']) != _canonical(body))) {
            throw StateError('Key/body mismatch');
          }
          return ScanCommand._(c);
        }
      }
    }
    if (ScanWorkspace._(w).active != null) {
      throw StateError('Pending scan command');
    }
    if (kind == 'content' && w['mediaId'] == null ||
        kind == 'create' &&
            (body['media_id'] != w['mediaId'] ||
                !(w['commands'] as List).any(
                  (c) => (c as Map)['kind'] == 'content' && c['result'] != null,
                )) ||
        kind == 'confirm' && w['scanId'] == null && w['observation'] == null) {
      throw StateError('Missing confirmed prerequisite');
    }
    if (kind == 'confirm') {
      final expected = ScanConfirm(
        stemText: w['stem'] as String,
        expressions: (w['expressions'] as String).trim().isEmpty
            ? []
            : [
                ScanExpression(
                  spanId: 'manual',
                  latex: w['expressions'] as String,
                ),
              ],
      );
      if (_canonical(expected.toJson()) != _canonical(body)) {
        throw StateError('Confirm requires the current persisted edit');
      }
    }
    final c = <String, dynamic>{
      'key': key,
      'workspaceId': id,
      'kind': kind,
      'path': path,
      'phase': 'prepared',
      'activeEpoch': activeEpoch,
      'editGeneration': w['editGeneration'],
    };
    if (kind == 'content') {
      final bytes = base64Decode(
        (generatedBody as MediaBlobUpload).contentBase64,
      );
      if (base64Encode(bytes) != generatedBody.contentBase64) {
        throw StateError('Noncanonical image body');
      }
      final metadata =
          (w['commands'] as List).cast<Map>().firstWhere(
                (c) => c['kind'] == 'upload',
              )['body']
              as Map;
      if (metadata['sha256'] != sha256.convert(bytes).toString() ||
          metadata['size_bytes'] != bytes.length) {
        throw StateError('Reselect original image');
      }
      c.addAll({
        'sha256': sha256.convert(bytes).toString(),
        'sizeBytes': bytes.length,
        'wireFingerprint': _hash(body),
      });
    } else {
      c['body'] = _body(kind, body);
    }
    (w['commands'] as List).add(c);
    return ScanCommand._(c);
  });
  Future<MediaBlobUpload> contentBody(String key, MediaBlobUpload input) =>
      LocalSerial.run(store, this.key, () async {
        final b = await _read();
        if (b == null) throw StateError('Missing command');
        final c = _command(b, key);
        final bytes = base64Decode(input.contentBase64);
        if (c['kind'] != 'content' ||
            c['wireFingerprint'] != _hash(input.toJson()) ||
            c['sha256'] != sha256.convert(bytes).toString() ||
            c['sizeBytes'] != bytes.length) {
          throw StateError('Reselect original image');
        }
        return input;
      });
  Future<void> recordResult(String key, Object response) => _change<void>((b) {
    final c = _command(b, key), w = _find(b, c['workspaceId'] as String);
    if (![
      'prepared',
      'unavailable',
      'result_known',
      'acked',
    ].contains(c['phase'])) {
      throw StateError('Rejected command');
    }
    final result = switch (response) {
      MediaUpload v => v.toJson(),
      MediaAssetInfo v => v.toJson(),
      Scan v => v.toJson(),
      ScanConfirmation v => v.toJson(),
      _ => throw ArgumentError('Generated scan response required'),
    };
    if (_canonical(_result(c['kind'] as String, result)) !=
        _canonical(result)) {
      throw StateError('Wrong response');
    }
    if (c['result'] != null && _canonical(c['result']) != _canonical(result)) {
      throw StateError('Changed receipt');
    }
    if (c['kind'] == 'upload') w['mediaId'] = result['media_id'];
    if (c['kind'] == 'content' &&
        (result['media_id'] != w['mediaId'] ||
            result['sha256'] != c['sha256'] ||
            result['size_bytes'] != c['sizeBytes'])) {
      throw StateError('Wrong content receipt');
    }
    if (c['kind'] == 'create') w['scanId'] = result['id'];
    if (c['kind'] == 'confirm' &&
        (result['scan'] as Map)['id'] != (c['path'] as String).split('/')[2]) {
      throw StateError('Wrong scan receipt');
    }
    c['result'] = result;
    if (c['phase'] != 'acked') c['phase'] = 'result_known';
  });
  Future<void> acknowledgeStoredResult(String key) => _change<void>((b) {
    final c = _command(b, key);
    if (c['result'] == null ||
        !['result_known', 'acked'].contains(c['phase'])) {
      throw StateError('No known result');
    }
    c['phase'] = 'acked';
  });
  Future<void> markUnavailable(String key) => _change<void>((b) {
    final c = _command(b, key);
    if (c['result'] == null) c['phase'] = 'unavailable';
  });
  Future<void> reject(String key, {required String code}) => _change<void>((b) {
    final c = _command(b, key);
    if (c['phase'] != 'prepared') throw StateError('Known or completed result');
    if (!RegExp(r'^[a-z_]{1,64}$').hasMatch(code)) {
      throw ArgumentError('Invalid error symbol');
    }
    c['phase'] = 'rejected';
    c['code'] = code;
  });
  Future<int> beginObservation(String id) => _change((b) {
    final w = _find(b, id);
    w['observationGeneration'] = (w['observationGeneration'] as int) + 1;
    return w['observationGeneration'] as int;
  });
  Future<void> observe(String id, Scan scan, {required int generation}) =>
      _change<void>((b) {
        final w = _find(b, id);
        if (w['observationGeneration'] != generation) return;
        if (scan.id != (w['scanId'] ?? w['legacyScanId'])) {
          throw StateError('Wrong observed scan');
        }
        w['observation'] = scan.toJson();
      });
}
