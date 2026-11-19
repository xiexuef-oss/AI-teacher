import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/errors.dart';
import '../../core/idempotency.dart';
import '../../core/local_serial.dart';
import '../../core/providers.dart';
import '../../core/widgets.dart';
import 'school_material_candidate_editor.dart';

final schoolMaterialPickerProvider = Provider<Future<XFile?> Function()>(
  (_) =>
      () => openFile(
        acceptedTypeGroups: const [
          XTypeGroup(
            label: 'PDF, JPEG, PNG',
            extensions: ['pdf', 'jpeg', 'jpg', 'png'],
            mimeTypes: ['application/pdf', 'image/jpeg', 'image/png'],
            uniformTypeIdentifiers: [
              'com.adobe.pdf',
              'public.jpeg',
              'public.png',
            ],
          ),
        ],
      ),
);

enum _CorrectionChoice { save, useCloud }

class SchoolMaterialSection extends ConsumerStatefulWidget {
  const SchoolMaterialSection({required this.ownerId, super.key});

  final String ownerId;

  @override
  ConsumerState<SchoolMaterialSection> createState() =>
      _SchoolMaterialSectionState();
}

class _SchoolMaterialSectionState extends ConsumerState<SchoolMaterialSection> {
  Map<String, dynamic> _record = {};
  List<SchoolMaterialPage> _pages = [];
  SchoolMaterialCandidates? _candidates;
  String? _message;
  String? _jobStatus;
  bool _busy = true;

  String get _storageKey => 'u/${widget.ownerId}/school-material-latest';
  String? get _job => _record['job'] as String?;
  bool get _canCancel =>
      const {'queued', 'running', 'retry_wait'}.contains(_jobStatus);
  bool get _active => mounted && ref.read(userIdProvider) == widget.ownerId;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    try {
      final raw = await ref.read(keyValueStoreProvider).read(_storageKey);
      if (_active && raw != null) {
        _record = jsonDecode(raw) as Map<String, dynamic>;
        if (_record['cancelled'] == true) {
          _jobStatus = 'cancelled';
          _message = '任务已取消。';
        }
      }
    } catch (error) {
      if (_active) _message = describeError(error);
    } finally {
      if (_active) setState(() => _busy = false);
    }
  }

  Future<void> _save(Map<String, dynamic> record) async {
    if (!_active) return;
    await ref
        .read(keyValueStoreProvider)
        .write(_storageKey, jsonEncode(record));
    if (_active) _record = record;
  }

  Future<void> _run(Future<void> Function(TutorApiClient) action) async {
    if (_busy || !_active) return;
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      await action(ref.read(apiClientProvider));
    } catch (error) {
      if (_active) _message = describeError(error);
    } finally {
      if (_active) setState(() => _busy = false);
    }
  }

  Future<void> _pick(TutorApiClient api) async {
    final file = await ref.read(schoolMaterialPickerProvider)();
    if (file == null || !_active) return;
    final mime = switch (file.name.split('.').last.toLowerCase()) {
      'pdf' => 'application/pdf',
      'png' => 'image/png',
      'jpg' || 'jpeg' => 'image/jpeg',
      _ => null,
    };
    if (mime == null) {
      _message = '请选择 PDF、JPEG 或 PNG 文件。';
      return;
    }
    final length = await file.length();
    if (length < 1 || length > 16 * 1024 * 1024) {
      if (_active) _message = '请选择非空且不超过 16 MB 的文件。';
      return;
    }
    final bytes = await file.readAsBytes();
    if (!_active) return;
    if (bytes.length != length) {
      _message = '文件已变化，请重新选择。';
      return;
    }
    final digest = sha256.convert(bytes).toString();
    final expiry = DateTime.tryParse(_record['expires'] as String? ?? '');
    if (_record['digest'] != digest ||
        _record['mime'] != mime ||
        const {'cancelled', 'failed'}.contains(_jobStatus) ||
        (expiry != null && !expiry.isAfter(ref.read(clockProvider)()))) {
      _pages = [];
      _candidates = null;
      _jobStatus = null;
      await _save({
        'digest': digest,
        'mime': mime,
        'key': newIdempotencyKey('school-material'),
      });
    }
    if (!_active) return;
    if (_job != null) {
      await _refresh(api);
      return;
    }
    final key = _record['key'] as String;
    var media = _record['media'] as String?;
    if (media == null) {
      final upload = await api.createSchoolMaterialUpload(
        body: SchoolMaterialUploadRequest(
          mime: mime,
          sizeBytes: length,
          sha256: digest,
        ),
        idempotencyKey: '$key-reserve',
      );
      if (!_active) return;
      media = upload.mediaId;
      await _save({
        ..._record,
        'media': media,
        'expires': upload.expiresAt.toIso8601String(),
      });
    }
    if (!_active) return;
    if (_record['uploaded'] != true) {
      final source = await api.uploadSchoolMaterialContent(
        mediaId: media,
        body: MediaBlobUpload(contentBase64: base64Encode(bytes)),
        idempotencyKey: '$key-upload',
      );
      if (!_active) return;
      if (source.mediaId != media || source.sha256 != digest) {
        _message = '上传回执与所选文件不一致。';
        return;
      }
      await _save({..._record, 'uploaded': true});
    }
    if (!_active) return;
    final job = await api.submitSchoolMaterial(
      body: SchoolMaterialSubmitRequest(mediaId: media),
      idempotencyKey: '$key-submit',
    );
    if (!_active) return;
    await _save({..._record, 'job': job.id});
    if (_active) {
      _jobStatus = job.status;
      _message = '已提交，可刷新处理结果。';
    }
  }

  Future<void> _refresh(TutorApiClient api) async {
    final job = _job;
    if (job == null) return;
    _pages = [];
    _candidates = null;
    final status = await api.getLearningJob(jobId: job);
    if (!_active) return;
    _jobStatus = status.status;
    if (status.status == 'succeeded') {
      final result = await api.listSchoolMaterialPages(jobId: job);
      if (_active) _pages = result.pages;
    } else {
      _message = switch (status.status) {
        'failed' => '材料处理失败。可重新选择原件提交。',
        'cancelled' => '任务已取消。',
        'retry_wait' => '等待重试。',
        _ => '正在处理，请稍后刷新。',
      };
    }
  }

  Future<void> _cancel(TutorApiClient api) async {
    final job = _job!;
    try {
      final status = await api.cancelLearningJob(
        jobId: job,
        idempotencyKey: '${_record['key']}-cancel',
      );
      if (!_active) return;
      if (status.id != job || status.status != 'cancelled') {
        throw StateError('取消回执与材料任务不一致。');
      }
      await _save({..._record, 'cancelled': true});
      if (!_active) return;
      _jobStatus = 'cancelled';
      _message = '任务已取消。';
    } on ApiException catch (error) {
      if (error.code != 'learning_job_finished') rethrow;
      if (_active) await _refresh(api);
    }
  }

  Future<void> _loadCandidates(TutorApiClient api) async {
    _candidates = null;
    final result = await api.listSchoolMaterialCandidates(jobId: _job!);
    if (_active) _candidates = result;
  }

  Future<void> _preview(TutorApiClient api, int page) async {
    final result = await api.getSchoolMaterialPagePreview(
      jobId: _job!,
      pageNumber: '$page',
    );
    if (!mounted || !_active) return;
    if (result.mime != 'image/png') {
      throw const FormatException('原件预览格式无效。');
    }
    final image = MemoryImage(base64Decode(result.contentBase64));
    try {
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('原件第 $page 页'),
          content: SizedBox(
            width: 560,
            height: 420,
            child: InteractiveViewer(
              child: Image(image: image, fit: BoxFit.contain),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('关闭'),
            ),
          ],
        ),
      );
    } finally {
      await image.evict();
    }
  }

  Future<void> _correct(TutorApiClient api, SchoolMaterialPage page) async {
    final job = _job!;
    final number = page.pageNumber;
    final store = ref.read(keyValueStoreProvider);
    final storageKey = '$_storageKey/corrections/$job/$number';
    final raw = await store.read(storageKey);
    if (!_active) return;
    final previous = raw == null
        ? null
        : jsonDecode(raw) as Map<String, dynamic>;
    final cloudRevision = page.revision ?? 0;
    var text = previous?['text'] as String? ?? page.text;
    var base = previous?['base'] as int? ?? cloudRevision;
    var key =
        previous?['key'] as String? ?? newIdempotencyKey('school-correction');
    Future<void> persist() {
      final snapshot = jsonEncode({'text': text, 'base': base, 'key': key});
      return LocalSerial.run(
        store,
        storageKey,
        () => store.write(storageKey, snapshot),
      );
    }

    Object? writeError;
    if (!mounted) return;
    final choice = await showDialog<_CorrectionChoice>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: Text('校正第 $number 页'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (base != cloudRevision) ...[
                  const Text('云端版本已更新。请核对后选择。'),
                  SelectableText(page.text),
                  TextButton(
                    onPressed: () =>
                        Navigator.pop(context, _CorrectionChoice.useCloud),
                    child: const Text('采用云端版本'),
                  ),
                  TextButton(
                    onPressed: () {
                      update(() {
                        base = cloudRevision;
                        key = newIdempotencyKey('school-correction');
                      });
                      persist().catchError((Object error) {
                        if (context.mounted) update(() => writeError = error);
                      });
                    },
                    child: const Text('保留本机转写'),
                  ),
                ],
                TextFormField(
                  initialValue: text,
                  maxLength: 16000,
                  minLines: 3,
                  maxLines: 8,
                  onChanged: (value) {
                    update(() {
                      text = value;
                      key = newIdempotencyKey('school-correction');
                    });
                    persist().catchError((Object error) {
                      if (context.mounted) update(() => writeError = error);
                    });
                  },
                ),
                if (writeError case final error?) Text(describeError(error)),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('关闭'),
            ),
            FilledButton(
              onPressed: text.trim().isEmpty
                  ? null
                  : () => Navigator.pop(context, _CorrectionChoice.save),
              child: Text(base == cloudRevision ? '保存校正' : '重试原提交'),
            ),
          ],
        ),
      ),
    );
    if (choice == null || !_active) return;
    if (choice == _CorrectionChoice.useCloud) {
      await LocalSerial.run(store, storageKey, () => store.delete(storageKey));
      return;
    }
    await persist();
    if (!_active) return;
    try {
      final receipt = await api.correctSchoolMaterialPage(
        jobId: job,
        pageNumber: '$number',
        body: SchoolMaterialPageCorrection(expectedRevision: base, text: text),
        idempotencyKey: key,
      );
      if (receipt.pageNumber != number || receipt.revision != base + 1) {
        throw StateError('校正回执与提交版本不一致。');
      }
      await LocalSerial.run(store, storageKey, () => store.delete(storageKey));
      if (_active) await _refresh(api);
    } on ApiException catch (error) {
      if (error.code != 'school_material_revision_conflict') rethrow;
      if (_active) {
        await _refresh(api);
        _message = '页面已更新，本机转写已保留。';
      }
    }
  }

  @override
  Widget build(BuildContext context) => Section(
    title: '学校材料',
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('上传前请遮盖无关姓名、班级等个人信息。'),
        Wrap(
          spacing: 8,
          children: [
            OutlinedButton(
              key: const ValueKey('schoolMaterial.pick'),
              onPressed: _busy ? null : () => _run(_pick),
              child: const Text('选择并提交文件'),
            ),
            if (_job != null)
              OutlinedButton(
                key: const ValueKey('schoolMaterial.refresh'),
                onPressed: _busy ? null : () => _run(_refresh),
                child: const Text('刷新材料结果'),
              ),
            if (_pages.isNotEmpty)
              OutlinedButton(
                onPressed: _busy ? null : () => _run(_loadCandidates),
                child: const Text('查看分题候选'),
              ),
            if (_canCancel)
              OutlinedButton(
                onPressed: _busy ? null : () => _run(_cancel),
                child: const Text('取消材料处理'),
              ),
          ],
        ),
        if (_busy) const LinearProgressIndicator(),
        if (_message case final message?) Text(message),
        if (_record['key'] != null && _job == null && !_busy)
          const Text('可重选同一原件继续提交。'),
        for (final page in _pages) ...[
          Text(
            '第 ${page.pageNumber} 页${page.needsOcr ? ' · 待 OCR' : ' · 待核对'}',
          ),
          if (page.text.isNotEmpty) SelectableText(page.text),
          Wrap(
            children: [
              TextButton(
                onPressed: _busy
                    ? null
                    : () => _run((api) => _preview(api, page.pageNumber)),
                child: Text('预览原件第 ${page.pageNumber} 页'),
              ),
              TextButton(
                onPressed: _busy
                    ? null
                    : () => _run((api) => _correct(api, page)),
                child: Text('校正第 ${page.pageNumber} 页'),
              ),
            ],
          ),
        ],
        if (_candidates case final result?) ...[
          Text(result.items.isEmpty ? '没有可核对的分题候选。' : '分题候选（待核对）'),
          for (final item in result.items)
            ExpansionTile(
              title: Text(
                item.locations
                    .map((location) {
                      final line = location.block;
                      return '第 ${location.page} 页${line == null ? '' : '第 $line 行'}';
                    })
                    .join('、'),
              ),
              children: [
                if (item.text.isNotEmpty) SelectableText(item.text),
                for (final warning in item.warnings) Text(warning),
              ],
            ),
          if (result.confirmedItems case final confirmed?) ...[
            const Text('已确认分题'),
            for (final item in confirmed) SelectableText(item.text),
          ] else if (result.sourceRevision case final revision?)
            if (result.items.isNotEmpty)
              SchoolMaterialCandidateEditor(
                key: ValueKey('$_job/$revision'),
                owner: widget.ownerId,
                job: _job!,
                revision: revision,
                candidates: result.items,
                onConfirmed: () => _run(_loadCandidates),
              ),
        ],
      ],
    ),
  );
}
