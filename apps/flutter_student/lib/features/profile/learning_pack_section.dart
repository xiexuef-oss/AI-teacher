import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:file_saver/file_saver.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/errors.dart';
import '../../core/file_export.dart';
import '../../core/idempotency.dart';
import '../../core/local_serial.dart';
import '../../core/providers.dart';
import '../../core/widgets.dart';
import '../scan/scan_page.dart' show scanImagePickerProvider;
import '../scan/scan_image.dart';
import 'paper_qr.dart';
import 'paper_live_scanner.dart';

final paperQrReaderProvider = Provider((ref) => readPaperQrs);

class LearningPackSection extends ConsumerStatefulWidget {
  const LearningPackSection({required this.ownerId, super.key});

  final String ownerId;

  @override
  ConsumerState<LearningPackSection> createState() =>
      _LearningPackSectionState();
}

class _LearningPackSectionState extends ConsumerState<LearningPackSection> {
  final _minutes = TextEditingController(text: '0');
  final _code = TextEditingController();
  final _transcript = TextEditingController();
  LearningPackItem? _item;
  String? _returnKey;
  bool _returned = false;
  String? _completedOn;
  String? _independence;
  List<String> _photoIds = [];
  static const _independenceLabels = {
    'unknown': '不确定',
    'independent': '独立完成',
    'assisted': '使用过帮助',
  };
  int? _correctionBase;
  int _transcriptRevision = 0;
  String? _job;
  LearningJobStatus? _jobStatus;
  bool get _canOpenPack =>
      _jobStatus?.id != _job || _jobStatus?.packResult == 'published';
  bool get _canCancel =>
      _jobStatus?.id == _job &&
      const {'queued', 'running', 'retry_wait'}.contains(_jobStatus?.status);
  List<String> _history = [];
  String? _historyCursor;
  String? _pendingKey;
  int? _pendingMinutes;
  String? _message;
  bool _busy = true;
  String get _storageKey => 'learning-pack.latest.${widget.ownerId}';
  bool get _active => mounted && ref.read(userIdProvider) == widget.ownerId;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    try {
      final raw = await ref.read(keyValueStoreProvider).read(_storageKey);
      if (!_active || raw == null) return;
      final record = jsonDecode(raw) as Map<String, dynamic>;
      _history = {
        ...?((record['history'] as List?)?.whereType<String>()),
        if (record['job'] case final String id) id,
      }.toList();
      _job = _history.lastOrNull;
      _pendingKey = record['key'] as String?;
      _pendingMinutes = record['minutes'] as int?;
      if (_pendingMinutes case final minutes?) _minutes.text = '$minutes';
    } catch (error) {
      if (_active) _message = describeError(error);
    } finally {
      if (_active) setState(() => _busy = false);
    }
  }

  Future<void> _run(Future<String> Function(TutorApiClient) action) async {
    if (_busy || !_active) return;
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      final result = await action(ref.read(apiClientProvider));
      if (_active) _message = result;
    } catch (error) {
      if (_active) _message = describeError(error);
    } finally {
      if (_active) setState(() => _busy = false);
    }
  }

  Future<String> _generate(TutorApiClient api) async {
    final minutes = _pendingMinutes ?? int.tryParse(_minutes.text);
    if (minutes == null || minutes < 0 || minutes > 10080) {
      return '请输入 0 至 10080 分钟。';
    }
    final store = ref.read(keyValueStoreProvider);
    final storageKey = _storageKey;
    final key = _pendingKey ?? newIdempotencyKey('paper-pack');
    await store.write(
      storageKey,
      jsonEncode({'history': _history, 'key': key, 'minutes': minutes}),
    );
    if (!_active) return '';
    _pendingKey = key;
    _pendingMinutes = minutes;
    final job = await api.createLearningPack(
      body: LearningPackRequest(schoolMinutes: minutes),
      idempotencyKey: key,
    );
    final history = [..._history.where((id) => id != job.id), job.id];
    await store.write(storageKey, jsonEncode({'history': history}));
    if (!_active) return '';
    _job = job.id;
    _jobStatus = job;
    _history = history;
    _code.clear();
    _item = null;
    _pendingKey = null;
    _pendingMinutes = null;
    return '已提交，稍后可刷新任务状态。';
  }

  Future<String> _refresh(TutorApiClient api) async {
    final job = await api.getLearningJob(jobId: _job!);
    if (_active) _jobStatus = job;
    final status = switch (job.status) {
      'queued' => '排队中',
      'running' => '正在处理',
      'retry_wait' => '等待重试',
      'succeeded' => switch (job.packResult) {
        'published' => '学习包已生成，可以下载学生版。',
        'awaiting_return' => '同题已有纸包等待回收，本次未生成新包。',
        'insufficient_budget' => '剩余学习时间不足，本次未生成纸包。',
        'no_printable_item' => '暂时没有适合打印的题目。',
        _ => '处理结束。',
      },
      'cancelled' => '已取消',
      _ => '处理未完成',
    };
    return [
      status,
      for (final review in job.reviews ?? const <PaperReviewPlanItem>[])
        '${review.title}：原定 ${review.originalDueOn}，'
            '${review.suggestedOn == null ? '暂无建议日期' : '建议 ${review.suggestedOn}'}'
            '${switch (review.deferredReason) {
              'no_learning_day' => '（未设置可用学习日）',
              'insufficient_budget' => '（剩余时间不足）',
              'awaiting_return' => '（等待旧包回收）',
              'no_printable_item' => '（没有适合打印的题目）',
              'overdue_budget_cap' => '（已达逾期复测时间上限）',
              _ => '',
            }}',
    ].join('\n');
  }

  Future<String> _cancel(TutorApiClient api) async {
    final id = _job!;
    try {
      final result = await api.cancelLearningJob(
        jobId: id,
        idempotencyKey: 'paper-pack-cancel-$id',
      );
      if (result.id != id || result.status != 'cancelled') {
        throw StateError('取消回执与纸包任务不一致。');
      }
      if (_active) _jobStatus = result;
      return '已取消';
    } on ApiException catch (error) {
      if (error.code != 'learning_job_finished' || !_active) rethrow;
      return _refresh(api);
    }
  }

  Future<String> _showReviewSchedule(TutorApiClient api) async {
    final schedule = await api.getPaperReviewSchedule();
    if (!mounted || !_active) return '';
    if (schedule.items.isEmpty) return '目前没有纸笔复测建议。';
    await showDialog<void>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('纸笔复测建议'),
        children: [
          for (final item in schedule.items)
            ListTile(
              title: Text(item.title),
              subtitle: Text(
                '${item.dueOn}${item.estimatedAnchor ? '（按回收日期估算）' : ''}',
              ),
            ),
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
    return '';
  }

  Future<String> _syncHistory(TutorApiClient api, {bool more = false}) async {
    final store = ref.read(keyValueStoreProvider);
    final storageKey = _storageKey;
    final page = await api.listLearningPacks(
      after: more ? _historyCursor : null,
    );
    if (!_active) return '';
    final history = {...page.ids, ..._history}.toList();
    await store.write(
      storageKey,
      jsonEncode({
        'history': history,
        if (_pendingKey != null) 'key': _pendingKey,
        if (_pendingMinutes != null) 'minutes': _pendingMinutes,
      }),
    );
    if (!_active) return '';
    _history = history;
    _job ??= history.lastOrNull;
    _historyCursor = page.nextCursor;
    return page.ids.isEmpty ? '没有更多已发布纸包。' : '已同步 ${page.ids.length} 个纸包。';
  }

  Future<String> _download(TutorApiClient api, {bool solutions = false}) async {
    final id = _job!;
    final pdf = solutions
        ? await api.downloadLearningPackSolutionPdf(jobId: id)
        : await api.downloadLearningPackStudentPdf(jobId: id);
    if (!_active) return '';
    if (pdf.contentBase64.length > 22369624) throw const FormatException();
    final bytes = base64Decode(pdf.contentBase64);
    if (bytes.length < 4 ||
        ascii.decode(bytes.sublist(0, 4), allowInvalid: true) != '%PDF' ||
        sha256.convert(bytes).toString() != pdf.sha256) {
      return 'PDF 校验失败，请重新下载。';
    }
    return saveDataFile(
      bytes,
      name:
          'learning-pack-$id-v${pdf.revision}-${solutions ? 'solutions' : 'student'}',
      extension: 'pdf',
      mimeType: MimeType.pdf,
    );
  }

  Future<String> _resolve(TutorApiClient api) async {
    final code = _code.text;
    if (!RegExp(r'^[0-9]{3}$').hasMatch(code)) return '请输入纸包上的三位短码。';
    final item = await api.resolveLearningPackItem(jobId: _job!, code: code);
    return _openItem(item);
  }

  Future<String> _pickItem(TutorApiClient api) async {
    final pack = await api.listLearningPackItems(jobId: _job!);
    if (!mounted || !_active) return '';
    final item = await showDialog<LearningPackItem>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('按印刷顺序选题'),
        children: [
          for (final item in pack.items)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, item),
              child: Text('${item.code} 号题 · 第 ${item.revision} 版'),
            ),
        ],
      ),
    );
    return item == null ? '' : _openItem(item);
  }

  Future<String> _liveQr(TutorApiClient api) async {
    final job = _job!;
    final token = await ref.read(paperLiveScannerProvider)(context);
    if (!_active || token == null) return '';
    return _openItem(
      await api.resolveLearningPackPage(jobId: job, token: token),
    );
  }

  Future<String> _scanQr(TutorApiClient api, ImageSource source) async {
    final job = _job!;
    final photo = await ref
        .read(scanImagePickerProvider)
        .pickImage(source: source, requestFullMetadata: false);
    if (photo == null || !_active) return '';
    if (await photo.length() > 16 * 1024 * 1024) return '照片过大，请靠近二维码重拍。';
    final readQr = ref.read(paperQrReaderProvider);
    final tokens = await readQr(await photo.readAsBytes());
    if (!_active) return '';
    if (tokens.isEmpty) return '未读到纸包二维码。请靠近重拍、输入短码或手动选题。';
    if (tokens.length != 1) return '照片中有多个纸包二维码，请只拍当前作答页。';
    return _openItem(
      await api.resolveLearningPackPage(jobId: job, token: tokens.single),
    );
  }

  Future<String> _openItem(LearningPackItem item) async {
    if (!_active) return '';
    final store = ref.read(keyValueStoreProvider);
    final key = _draftKey(item.code);
    final raw = await LocalSerial.run(store, key, () => store.read(key));
    if (!_active) return '';
    final draft = raw == null ? null : jsonDecode(raw) as Map<String, dynamic>;
    LearningPackReturnRecord? cloud;
    if (draft == null) {
      try {
        cloud = await ref
            .read(apiClientProvider)
            .getLearningPackReturn(jobId: _job!, code: item.code);
      } catch (error) {
        if (!isNotFoundError(error) && !isNetworkError(error)) rethrow;
      }
    }
    if (!_active) return '';
    if (cloud != null &&
        (cloud.item.code != item.code ||
            cloud.item.revision != item.revision ||
            cloud.item.questionVersionId != item.questionVersionId)) {
      throw const FormatException();
    }
    _item = item;
    _transcript.text = cloud?.transcript ?? draft?['text'] as String? ?? '';
    _returnKey = draft?['key'] as String?;
    _returned = cloud != null || draft?['returned'] == true;
    _completedOn = draft?['completed_on'] as String?;
    _independence = draft?['independence'] as String?;
    _photoIds = (draft?['photo_ids'] as List?)?.cast<String>() ?? [];
    _correctionBase = draft?['correction_base'] as int?;
    _transcriptRevision =
        cloud?.transcriptRevision ?? draft?['revision'] as int? ?? 0;
    return '已定位第 ${item.revision} 版纸包的 ${item.code} 号题。';
  }

  Future<String> _abandon(TutorApiClient api) async {
    final id = _job!;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('结束独立作答？'),
        content: const Text('确认后开放解析，这份纸包将停止接收新的作答。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('继续作答'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('结束作答'),
          ),
        ],
      ),
    );
    if (confirmed != true || !_active) return '';
    await api.abandonLearningPack(
      jobId: id,
      idempotencyKey: 'paper-abandon-$id',
    );
    if (_active) _item = null;
    return '已结束独立作答，可以下载解析版。';
  }

  String _draftKey(String code) => '$_storageKey.$_job.$code';

  Map<String, Object> get _returnDetails => {
    'completed_on': ?_completedOn,
    'independence': ?_independence,
    if (_photoIds.isNotEmpty) 'photo_ids': List<String>.of(_photoIds),
  };

  Future<String> _addReturnPhoto(TutorApiClient api, ImageSource source) async {
    final item = _item!;
    final job = _job!;
    if (_photoIds.length >= 10) return '每道题最多添加 10 张照片。';
    final photo = await ref
        .read(scanImagePickerProvider)
        .pickImage(source: source, requestFullMetadata: false);
    if (photo == null || !_active) return '';
    if (await photo.length() > 5 * 1024 * 1024) return '每张照片最大 5 MiB。';
    final bytes = await photo.readAsBytes();
    if (!_active) return '';
    final info = inspectScanImage(bytes);
    final tokens = await ref.read(paperQrReaderProvider)(bytes);
    if (!mounted || !_active) return '';
    if (tokens.length > 1) return '照片中有多个纸包二维码，请只拍当前作答页。';
    if (tokens.isNotEmpty) {
      final LearningPackItem located;
      try {
        located = await api.resolveLearningPackPage(
          jobId: job,
          token: tokens.single,
        );
      } on ApiException catch (error) {
        if (!isNotFoundError(error)) rethrow;
        return '照片二维码不属于当前纸包，未添加这页。';
      }
      if (located.code != item.code ||
          located.revision != item.revision ||
          located.questionVersionId != item.questionVersionId) {
        return '照片二维码对应另一道题，未添加这页。';
      }
    } else {
      if (!mounted || !_active) return '';
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('确认作答页归属'),
          content: Text('照片未读到二维码。请确认它属于当前纸包的 ${item.code} 号题。'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('确认并添加'),
            ),
          ],
        ),
      );
      if (confirmed != true) return '';
    }
    if (!_active) return '';
    final digest = sha256.convert(bytes).toString();
    final store = ref.read(keyValueStoreProvider);
    final draftKey = _draftKey(item.code);
    final uploadKey = '$draftKey.upload.$digest';
    final key = await LocalSerial.run(store, uploadKey, () async {
      final saved = await store.read(uploadKey);
      if (saved != null) return saved;
      final created = newIdempotencyKey('paper-photo');
      await store.write(uploadKey, created);
      return created;
    });
    if (!_active) return '';
    final upload = await api.createScanUpload(
      body: MediaUploadRequest(
        purpose: 'scan',
        mime: info.mime,
        sizeBytes: bytes.length,
        sha256: digest,
      ),
      idempotencyKey: '$key-reserve',
    );
    if (!_active) return '';
    if (_photoIds.contains(upload.mediaId)) return '这张照片已添加。';
    try {
      final stored = await api.uploadScanContent(
        mediaId: upload.mediaId,
        body: MediaBlobUpload(contentBase64: base64Encode(bytes)),
        idempotencyKey: '$key-content',
      );
      if (stored.mediaId != upload.mediaId || stored.sha256 != digest) {
        throw const FormatException();
      }
    } on ApiException catch (error) {
      if (!isNotFoundError(error)) rethrow;
      await LocalSerial.run(store, uploadKey, () => store.delete(uploadKey));
      return '照片上传已过期，请重新选择原图。';
    }
    if (!_active) return '';
    final photos = [..._photoIds, upload.mediaId];
    final draft = {
      'text': _transcript.text,
      ..._returnDetails,
      'photo_ids': photos,
    };
    await LocalSerial.run(
      store,
      draftKey,
      () => store.write(draftKey, jsonEncode(draft)),
    );
    if (_active) _photoIds = photos;
    return '已添加第 ${photos.length} 页，请核对顺序后回收。';
  }

  Future<String> _editPhotoOrder(int index, int? destination) async {
    final photos = List<String>.of(_photoIds);
    final photo = photos.removeAt(index);
    if (destination != null) photos.insert(destination, photo);
    final draft = {
      'text': _transcript.text,
      ..._returnDetails,
      'photo_ids': photos,
    };
    final store = ref.read(keyValueStoreProvider);
    final key = _draftKey(_item!.code);
    await LocalSerial.run(
      store,
      key,
      () => store.write(key, jsonEncode(draft)),
    );
    if (_active) _photoIds = photos;
    return destination == null ? '已移除第 ${index + 1} 页。' : '已调整作答页顺序。';
  }

  Future<String> _previewReturnPhoto(TutorApiClient api, int index) async {
    final id = _photoIds[index];
    final photo = await api.getScanUploadContent(mediaId: id);
    if (!mounted || !_active) return '';
    if (photo.mediaId != id || photo.contentBase64.length > 6990508) {
      throw const FormatException();
    }
    final bytes = base64Decode(photo.contentBase64);
    inspectScanImage(bytes);
    final image = MemoryImage(bytes);
    try {
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('第 ${index + 1} 页作答'),
          content: SizedBox(
            width: 480,
            height: 360,
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
    return '';
  }

  Future<void> _pickCompletionDay() async {
    final item = _item;
    final job = _job;
    final today = DateTime.now().toUtc().add(const Duration(hours: 8));
    final value = await showDatePicker(
      context: context,
      initialDate: DateTime.tryParse(_completedOn ?? '') ?? today,
      firstDate: DateTime(1900),
      lastDate: today,
    );
    if (value == null || !_active || _busy || item != _item || job != _job) {
      return;
    }
    setState(() {
      _completedOn = value.toIso8601String().split('T').first;
    });
    await _saveTranscript(_transcript.text);
  }

  Future<void> _saveTranscript(String text) async {
    final store = ref.read(keyValueStoreProvider);
    final key = _draftKey(_item!.code);
    final correctionBase = _correctionBase;
    final details = _returnDetails;
    try {
      await LocalSerial.run(
        store,
        key,
        () => store.write(
          key,
          jsonEncode({
            'text': text,
            ...details,
            if (correctionBase case final base?) ...{
              'returned': true,
              'correction_base': base,
            },
          }),
        ),
      );
    } catch (error) {
      if (_active && !_busy) setState(() => _message = describeError(error));
    }
  }

  Future<String> _correct(TutorApiClient api) async {
    final item = _item!;
    final job = _job!;
    final text = _transcript.text;
    if (text.trim().isEmpty) return '请输入纸笔作答内容。';
    final base = _correctionBase!;
    final store = ref.read(keyValueStoreProvider);
    final key = _draftKey(item.code);
    final requestKey = _returnKey ?? newIdempotencyKey('paper-correction');
    final details = _returnDetails;
    Future<void> save(Map<String, Object> data) => LocalSerial.run(
      store,
      key,
      () =>
          store.write(key, jsonEncode({'returned': true, ...details, ...data})),
    );
    await save({'text': text, 'key': requestKey, 'correction_base': base});
    if (!_active) return '';
    _returnKey = requestKey;
    LearningPackReturnRecord result;
    try {
      result = await api.correctLearningPackReturn(
        jobId: job,
        code: item.code,
        idempotencyKey: requestKey,
        body: LearningPackCorrection(expectedRevision: base, transcript: text),
      );
    } on ApiException catch (error) {
      if (error.code != 'paper_return_revision_conflict' ||
          !mounted ||
          !_active) {
        rethrow;
      }
      final cloud = LearningPackReturnRecord.fromJson(
        Map<String, dynamic>.from(error.details['server_return'] as Map),
      );
      final useCloud = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('转写已在其他设备更新'),
          content: SingleChildScrollView(
            child: Text('本机：$text\n\n云端：${cloud.transcript}'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('保留本机待提交'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('采用云端'),
            ),
          ],
        ),
      );
      if (useCloud == null || !_active) return '已保留本机修改。';
      if (!useCloud) {
        final revision = cloud.transcriptRevision ?? 0;
        await save({'text': text, 'correction_base': revision});
        if (_active) {
          _correctionBase = revision;
          _returnKey = null;
        }
        return '已保留本机修改，请核对后重新提交。';
      }
      result = cloud;
    }
    if (result.item.code != item.code ||
        result.item.revision != item.revision ||
        result.item.questionVersionId != item.questionVersionId) {
      throw const FormatException();
    }
    final revision = result.transcriptRevision ?? 0;
    await save({'text': result.transcript, 'revision': revision});
    if (_active) {
      _transcript.text = result.transcript;
      _transcriptRevision = revision;
      _correctionBase = null;
      _returnKey = null;
    }
    return '已保存转写版本 $revision。';
  }

  Future<String> _submitReturn(TutorApiClient api) async {
    final item = _item!;
    final text = _transcript.text;
    if (text.trim().isEmpty) return '请输入纸笔作答内容。';
    final store = ref.read(keyValueStoreProvider);
    final job = _job!;
    final key = _draftKey(item.code);
    final requestKey = _returnKey ?? newIdempotencyKey('paper-return');
    final details = _returnDetails;
    final body = LearningPackReturnRequest(
      transcript: text,
      completedOn: _completedOn,
      independence: _independence,
      photoIds: _photoIds.isEmpty ? null : List<String>.of(_photoIds),
    );
    await LocalSerial.run(
      store,
      key,
      () => store.write(
        key,
        jsonEncode({'text': text, 'key': requestKey, ...details}),
      ),
    );
    if (!_active) return '';
    _returnKey = requestKey;
    final LearningPackItem receipt;
    try {
      receipt = await api.submitLearningPackReturn(
        jobId: job,
        code: item.code,
        body: body,
        idempotencyKey: requestKey,
      );
    } on ApiException catch (error) {
      if (!isNotFoundError(error) || body.photoIds == null) rethrow;
      await LocalSerial.run(
        store,
        key,
        () => store.write(key, jsonEncode({'text': text, ...details})),
      );
      if (_active) _returnKey = null;
      return '纸包或照片已不可用。请核对纸包，移除过期照片后再提交。';
    }
    if (receipt.code != item.code ||
        receipt.revision != item.revision ||
        receipt.questionVersionId != item.questionVersionId) {
      throw const FormatException();
    }
    await LocalSerial.run(
      store,
      key,
      () => store.write(
        key,
        jsonEncode({'text': text, 'returned': true, ...details}),
      ),
    );
    if (_active) {
      _returnKey = null;
      _returned = true;
    }
    return '纸笔作答已回收。';
  }

  @override
  void dispose() {
    _minutes.dispose();
    _code.dispose();
    _transcript.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Section(
    title: '纸质学习包',
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 12,
      children: [
        TextField(
          controller: _minutes,
          enabled: !_busy && _pendingKey == null,
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: const InputDecoration(
            labelText: '同类学校作业占用分钟',
            floatingLabelBehavior: FloatingLabelBehavior.always,
          ),
        ),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          children: [
            OutlinedButton(
              onPressed: _busy ? null : () => _run(_generate),
              child: Text(_pendingKey == null ? '生成学习包' : '重试生成'),
            ),
            OutlinedButton(
              onPressed: _busy ? null : () => _run(_syncHistory),
              child: const Text('同步纸包历史'),
            ),
            OutlinedButton(
              onPressed: _busy ? null : () => _run(_showReviewSchedule),
              child: const Text('查看纸笔复测建议'),
            ),
            if (_historyCursor != null)
              OutlinedButton(
                onPressed: _busy
                    ? null
                    : () => _run((api) => _syncHistory(api, more: true)),
                child: const Text('加载更多纸包'),
              ),
            if (_job != null) ...[
              OutlinedButton(
                onPressed: _busy ? null : () => _run(_refresh),
                child: const Text('刷新状态'),
              ),
              if (_canCancel)
                OutlinedButton(
                  onPressed: _busy ? null : () => _run(_cancel),
                  child: const Text('取消生成'),
                ),
              OutlinedButton(
                onPressed: _busy || !_canOpenPack
                    ? null
                    : () => _run(_download),
                child: const Text('下载学生版 PDF'),
              ),
              OutlinedButton(
                onPressed: _busy || !_canOpenPack
                    ? null
                    : () => _run((api) => _download(api, solutions: true)),
                child: const Text('下载解析版 PDF'),
              ),
              TextButton(
                onPressed: _busy || !_canOpenPack ? null : () => _run(_abandon),
                child: const Text('主动结束独立作答'),
              ),
            ],
          ],
        ),
        if (_job != null) ...[
          if (_history.length > 1)
            DropdownButtonFormField<String>(
              key: ValueKey('paper-pack.$_job'),
              initialValue: _job,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: '选择纸包任务',
                floatingLabelBehavior: FloatingLabelBehavior.always,
              ),
              items: [
                for (var i = _history.length - 1; i >= 0; i--)
                  DropdownMenuItem(
                    value: _history[i],
                    child: Text('纸包 ${_history[i].split('-').first}'),
                  ),
              ],
              onChanged: _busy
                  ? null
                  : (id) => setState(() {
                      _job = id;
                      _code.clear();
                      _item = null;
                      _message = null;
                    }),
            ),
          TextField(
            controller: _code,
            keyboardType: TextInputType.number,
            inputFormatters: [
              FilteringTextInputFormatter.digitsOnly,
              LengthLimitingTextInputFormatter(3),
            ],
            decoration: const InputDecoration(
              labelText: '本包题目短码',
              floatingLabelBehavior: FloatingLabelBehavior.always,
            ),
            enabled: !_busy,
          ),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: [
              OutlinedButton(
                onPressed: _busy ? null : () => _run(_resolve),
                child: const Text('定位印刷题目'),
              ),
              OutlinedButton(
                onPressed: _busy ? null : () => _run(_pickItem),
                child: const Text('手动选题'),
              ),
              if (!kIsWeb &&
                  const {
                    TargetPlatform.android,
                    TargetPlatform.iOS,
                  }.contains(defaultTargetPlatform))
                OutlinedButton(
                  onPressed: _busy ? null : () => _run(_liveQr),
                  child: const Text('相机扫码'),
                ),
              OutlinedButton(
                onPressed: _busy
                    ? null
                    : () => _run((api) => _scanQr(api, ImageSource.gallery)),
                child: const Text('从照片读码'),
              ),
            ],
          ),
        ],
        if (_item case final item?) ...[
          Text('第 ${item.revision} 版 · ${item.code} 号题'),
          if (!_returned) ...[
            Wrap(
              spacing: 8,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                OutlinedButton(
                  onPressed: _busy || _returnKey != null
                      ? null
                      : () => _run(
                          (api) => _addReturnPhoto(api, ImageSource.camera),
                        ),
                  child: const Text('拍照添加作答页'),
                ),
                OutlinedButton(
                  onPressed: _busy || _returnKey != null
                      ? null
                      : () => _run(
                          (api) => _addReturnPhoto(api, ImageSource.gallery),
                        ),
                  child: const Text('选图添加作答页'),
                ),
                if (_photoIds.isNotEmpty) ...[
                  Text('已添加 ${_photoIds.length} 页'),
                  for (var i = 0; i < _photoIds.length; i++) ...[
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () => _run((api) => _previewReturnPhoto(api, i)),
                      child: Text('预览第 ${i + 1} 页'),
                    ),
                    PopupMenuButton<String>(
                      tooltip: '调整第 ${i + 1} 页',
                      enabled: !_busy && _returnKey == null,
                      onSelected: (action) => _run(
                        (_) => _editPhotoOrder(i, switch (action) {
                          'up' => i - 1,
                          'down' => i + 1,
                          _ => null,
                        }),
                      ),
                      itemBuilder: (_) => [
                        if (i > 0)
                          const PopupMenuItem(value: 'up', child: Text('前移一页')),
                        if (i + 1 < _photoIds.length)
                          const PopupMenuItem(
                            value: 'down',
                            child: Text('后移一页'),
                          ),
                        const PopupMenuItem(
                          value: 'remove',
                          child: Text('移除此页'),
                        ),
                      ],
                    ),
                  ],
                ],
              ],
            ),
            Wrap(
              children: [
                TextButton(
                  onPressed: _busy || _returnKey != null
                      ? null
                      : _pickCompletionDay,
                  child: Text('作答日期：${_completedOn ?? '未知'}'),
                ),
                if (_completedOn != null)
                  TextButton(
                    onPressed: _busy || _returnKey != null
                        ? null
                        : () {
                            setState(() => _completedOn = null);
                            _saveTranscript(_transcript.text);
                          },
                    child: const Text('清除日期'),
                  ),
              ],
            ),
            DropdownButtonFormField<String>(
              key: ValueKey('paper-independence.${item.code}.$_independence'),
              initialValue: _independence ?? 'unknown',
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: '作答情况（自报）',
                floatingLabelBehavior: FloatingLabelBehavior.always,
              ),
              items: [
                for (final entry in _independenceLabels.entries)
                  DropdownMenuItem(value: entry.key, child: Text(entry.value)),
              ],
              onChanged: _busy || _returnKey != null
                  ? null
                  : (choice) {
                      setState(() => _independence = choice);
                      _saveTranscript(_transcript.text);
                    },
            ),
          ],
          TextField(
            controller: _transcript,
            enabled:
                !_busy &&
                (!_returned || _correctionBase != null) &&
                _returnKey == null,
            maxLength: 8000,
            minLines: 2,
            maxLines: 5,
            onChanged: _saveTranscript,
            decoration: const InputDecoration(
              labelText: '纸笔作答转写',
              floatingLabelBehavior: FloatingLabelBehavior.always,
            ),
          ),
          if (_returned) ...[
            const Text('已回收'),
            OutlinedButton(
              onPressed: _busy
                  ? null
                  : () {
                      if (_correctionBase == null) {
                        setState(() => _correctionBase = _transcriptRevision);
                      } else {
                        _run(_correct);
                      }
                    },
              child: Text(_correctionBase == null ? '校正转写' : '保存校正'),
            ),
          ] else
            OutlinedButton(
              onPressed: _busy ? null : () => _run(_submitReturn),
              child: Text(_returnKey == null ? '确认并回收作答' : '重试回收'),
            ),
        ],
        if (_busy) const LinearProgressIndicator(),
        if (_message case final message?) Text(message),
      ],
    ),
  );
}
