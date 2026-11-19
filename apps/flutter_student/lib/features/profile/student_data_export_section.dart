import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:file_saver/file_saver.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/file_export.dart';
import '../../core/providers.dart';
import '../scan/scan_command_store.dart';
import '../solve/draft_store.dart';
import 'local_recovery_export.dart';

enum _ExportSource { drafts, server, scans, media, recovery }

Future<String> _saveExport(Uint8List bytes, {required _ExportSource source}) =>
    saveDataFile(
      bytes,
      name:
          '${switch (source) {
            _ExportSource.server => 'learning-records',
            _ExportSource.drafts => 'practice-drafts',
            _ExportSource.scans => 'scan-records',
            _ExportSource.media => 'media-files',
            _ExportSource.recovery => 'recovery-records',
          }}-${DateTime.now().microsecondsSinceEpoch}',
      extension: source == _ExportSource.media ? 'zip' : 'json',
      mimeType: source == _ExportSource.media ? MimeType.zip : MimeType.json,
    );

class StudentDataExportSection extends ConsumerStatefulWidget {
  const StudentDataExportSection({super.key, this.save, bool server = false})
    : _source = server ? _ExportSource.server : _ExportSource.drafts;
  const StudentDataExportSection.scans({super.key, this.save})
    : _source = _ExportSource.scans;
  const StudentDataExportSection.media({super.key, this.save})
    : _source = _ExportSource.media;
  const StudentDataExportSection.recovery({super.key, this.save})
    : _source = _ExportSource.recovery;
  final Future<String> Function(Uint8List)? save;
  final _ExportSource _source;

  @override
  ConsumerState<StudentDataExportSection> createState() =>
      _StudentDataExportSectionState();
}

class _StudentDataExportSectionState
    extends ConsumerState<StudentDataExportSection> {
  bool _busy = false;
  AuthSession? _owner;
  String? _status;
  String get _key => switch (widget._source) {
    _ExportSource.server => 'profile.exportLearningRecords',
    _ExportSource.drafts => 'profile.exportDrafts',
    _ExportSource.scans => 'profile.exportScans',
    _ExportSource.media => 'profile.exportMedia',
    _ExportSource.recovery => 'profile.exportRecovery',
  };

  bool _current(AuthSession owner) =>
      mounted && identical(ref.read(authProvider).asData?.value, owner);

  void _showStatus(AuthSession owner, String status) {
    if (_current(owner)) setState(() => _status = status);
  }

  Future<Uint8List?> _mediaArchive(AuthSession owner) async {
    final result = await ref.read(apiClientProvider).getStudentMediaExport();
    if (!_current(owner)) return null;
    if (result.ownerId != owner.userId ||
        result.formatVersion != 1 ||
        result.scope != 'server_current_student_media' ||
        result.historyComplete ||
        result.consistentSnapshot ||
        result.objectsCount < 0 ||
        result.objectsCount > 1000 ||
        result.filesCount < 0 ||
        result.filesCount > result.objectsCount ||
        result.sizeBytes < 1 ||
        result.sizeBytes > 16 * 1024 * 1024 ||
        result.archiveBase64.length > 22369624) {
      throw StateError('Invalid media export');
    }
    if (result.objectsCount == 0) {
      _showStatus(owner, '当前没有仍有效的学生用途媒体；这不代表从未上传过图片。');
      return null;
    }
    final bytes = base64Decode(result.archiveBase64);
    if (bytes.length != result.sizeBytes ||
        sha256.convert(bytes).toString() != result.sha256 ||
        bytes.length < 4 ||
        bytes[0] != 0x50 ||
        bytes[1] != 0x4b ||
        bytes[2] != 0x03 ||
        bytes[3] != 0x04) {
      throw StateError('Invalid media archive');
    }
    return bytes;
  }

  Future<void> _deliver(AuthSession owner, Uint8List bytes) async {
    if (!_current(owner)) return;
    // ponytail: in-memory export capped at 32 MiB; stream larger backups later.
    if (bytes.length > 32 * 1024 * 1024) throw StateError('Export too large');
    _showStatus(
      owner,
      await (widget.save?.call(bytes) ??
          _saveExport(bytes, source: widget._source)),
    );
  }

  Future<void> _export() async {
    final owner = ref.read(authProvider).asData?.value;
    if (_busy || owner == null || owner.role != LocalRole.student) return;
    setState(() {
      _busy = true;
      _owner = owner;
      _status = switch (widget._source) {
        _ExportSource.server => '正在读取服务端学习记录…',
        _ExportSource.drafts => '正在读取本机草稿…',
        _ExportSource.scans => '正在读取本机拍题记录…',
        _ExportSource.media => '正在读取当前可访问的媒体…',
        _ExportSource.recovery => '正在读取本机恢复记录…',
      };
    });
    try {
      if (widget._source == _ExportSource.media) {
        final bytes = await _mediaArchive(owner);
        if (bytes != null) {
          await _deliver(owner, bytes);
        }
        return;
      }
      final Map<String, dynamic> payload;
      if (widget._source == _ExportSource.server) {
        final result = await ref
            .read(apiClientProvider)
            .getStudentLearningExport();
        if (!_current(owner)) return;
        if (result.profile.userId != owner.userId) {
          throw StateError('Export owner mismatch');
        }
        payload = result.toJson();
      } else if (widget._source == _ExportSource.recovery) {
        final snapshot = await exportLocalRecoveryRecords(
          ref.read(keyValueStoreProvider),
          owner.userId,
        );
        if (!_current(owner)) return;
        if (snapshot['profile'] == null &&
            snapshot['authorization'] == null &&
            (snapshot['resources'] as List).isEmpty &&
            (snapshot['practice'] as List).isEmpty &&
            (snapshot['question_cache'] as List).isEmpty) {
          _showStatus(owner, '此学生在本机没有现存恢复记录；不代表从未修改或授权。');
          return;
        }
        payload = {
          ...snapshot,
          'exported_at': ref.read(clockProvider)().toUtc().toIso8601String(),
        };
      } else if (widget._source == _ExportSource.scans) {
        final snapshot = await ScanWorkspaceStore(
          ref.read(keyValueStoreProvider),
          owner.userId,
        ).exportSnapshot();
        if (!_current(owner)) return;
        if ((snapshot['workspaces'] as List).isEmpty) {
          _showStatus(owner, '这个学生身份在这台设备上没有已保存的拍题记录。');
          return;
        }
        payload = {
          ...snapshot,
          'exported_at': ref.read(clockProvider)().toUtc().toIso8601String(),
        };
      } else {
        final drafts = await DraftStore(
          ref.read(keyValueStoreProvider),
          owner.userId,
        ).readExportDrafts();
        if (!_current(owner)) return;
        if (drafts.isEmpty) {
          _showStatus(owner, '这个学生身份在这台设备上没有已保存的练习草稿。');
          return;
        }
        payload = {
          'format_version': 1,
          'scope': 'local_exercise_drafts',
          'owner_id': owner.userId,
          'exported_at': ref.read(clockProvider)().toUtc().toIso8601String(),
          'drafts': [for (final draft in drafts) draft.toJson()],
        };
      }
      final bytes = Uint8List.fromList(utf8.encode(jsonEncode(payload)));
      await _deliver(owner, bytes);
    } catch (_) {
      _showStatus(owner, switch (widget._source) {
        _ExportSource.server => '导出失败，服务端和本机记录未改动，请联网后重试。',
        _ExportSource.drafts => '导出失败，原草稿未改动。可以重试，或逐题导出为图片。',
        _ExportSource.scans => '导出失败，原拍题记录未改动。可以重试。',
        _ExportSource.media => '导出失败，原媒体未改动。请联网重试，并确认媒体存储已启用。',
        _ExportSource.recovery => '导出失败，原恢复记录未改动。可以重试。',
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final owner = ref.watch(authProvider).asData?.value;
    if (owner == null || owner.role != LocalRole.student) {
      return const SizedBox.shrink();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 8),
        Text(switch (widget._source) {
          _ExportSource.server => '需联网：导出已同步的本人资料、会话、作答、笔迹、自查、复测、摸底计划，以及现存授权和邀请记录（历史不完整，不含邀请码或家长资料）。旧文件未含授权字段不代表从未授权。也含当前服务端身份可关联的模型用量和预算估算，非账单或完整调用历史。文件可包含现存拍题文字和状态，不含原图或已清理历史；未提供拍题字段不代表从未拍题。不含本机未同步内容和媒体文件；本机摸底记录在摸底页另行导出。JSON暂不支持导入应用。',
          _ExportSource.drafts =>
            '仅导出此学生在本机保存的练习作答、笔迹和副本，不含登录信息或云端完整记录。JSON文件可查看，暂不支持导入应用。',
          _ExportSource.scans => '可离线：导出此学生在本机保存的拍题文字、表达式和现存恢复信息，包含未同步内容。不含原图、上传地址、登录信息或云端完整历史。JSON文件可查看，暂不支持导入或自动重试。',
          _ExportSource.media => '需联网：保存本人当前可访问的拍题和手写媒体ZIP，附带范围和状态清单。未上传或尚待确认的对象只列状态；不含过期、删除、审核用途或本机未上传原图。不含完整历史；导出期间新增的媒体可能不在其中。',
          _ExportSource.recovery => '可离线：导出本人在本机的资料修改、练习、辅导、复测和授权操作的恢复记录及现存回执，包含尚未发送的提交、后续修改及本机题面缓存。不含邀请码、家长身份、登录信息或原图；记录读取时间可能不同，不代表完整历史。练习草稿、拍题和摸底记录另行导出。JSON可查看，暂不支持导入或自动重试。',
        }),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          key: ValueKey(_key),
          onPressed: _busy ? null : _export,
          icon: const Icon(Icons.download_outlined),
          label: Text(
            _busy
                ? '正在导出…'
                : switch (widget._source) {
                    _ExportSource.server => '导出服务端学习记录',
                    _ExportSource.drafts => '导出本机练习草稿',
                    _ExportSource.scans => '导出本机拍题记录',
                    _ExportSource.media => '下载当前媒体ZIP',
                    _ExportSource.recovery => '导出本机恢复记录',
                  },
          ),
        ),
        if (identical(_owner, owner) && _status != null)
          Text(
            _status!,
            key: ValueKey('$_key.status'),
            semanticsLabel: _status,
          ),
      ],
    );
  }
}
