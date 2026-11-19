import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/errors.dart';
import '../../core/idempotency.dart';
import '../../core/local_serial.dart';
import '../../core/providers.dart';

class SchoolMaterialCandidateEditor extends ConsumerStatefulWidget {
  const SchoolMaterialCandidateEditor({
    required this.owner,
    required this.job,
    required this.revision,
    required this.candidates,
    required this.onConfirmed,
    super.key,
  });

  final String owner;
  final String job;
  final String revision;
  final List<SchoolMaterialCandidate> candidates;
  final VoidCallback onConfirmed;

  @override
  ConsumerState<SchoolMaterialCandidateEditor> createState() =>
      _SchoolMaterialCandidateEditorState();
}

class _QuestionDraft {
  _QuestionDraft(SchoolMaterialConfirmedItem item)
    : text = TextEditingController(text: item.text),
      pages = item.pages;

  final TextEditingController text;
  final List<int> pages;

  SchoolMaterialConfirmedItem get item =>
      SchoolMaterialConfirmedItem(text: text.text, pages: pages);
}

class _SchoolMaterialCandidateEditorState
    extends ConsumerState<SchoolMaterialCandidateEditor> {
  final _drafts = <_QuestionDraft>[];
  final _retired = <_QuestionDraft>[];
  bool _busy = true;
  String? _error;
  String? _key;

  String get _storageKey =>
      'u/${widget.owner}/school-material/${widget.job}/${widget.revision}/questions';
  bool get _active => mounted && ref.read(userIdProvider) == widget.owner;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    try {
      final store = ref.read(keyValueStoreProvider);
      final raw = await LocalSerial.run(
        store,
        _storageKey,
        () => store.read(_storageKey),
      );
      if (!_active) return;
      if (raw == null) {
        _drafts.addAll(
          widget.candidates.map(
            (candidate) => _QuestionDraft(
              SchoolMaterialConfirmedItem(
                text: candidate.text,
                pages: {
                  for (final location in candidate.locations) location.page,
                }.toList(),
              ),
            ),
          ),
        );
      } else {
        final record = jsonDecode(raw) as Map<String, dynamic>;
        final body = SchoolMaterialConfirmationRequest.fromJson(
          record['body'] as Map<String, dynamic>,
        );
        _key = record['key'] as String?;
        _drafts.addAll(body.items.map(_QuestionDraft.new));
      }
    } catch (error) {
      if (_active) _error = describeError(error);
    } finally {
      if (_active) setState(() => _busy = false);
    }
  }

  SchoolMaterialConfirmationRequest get _body =>
      SchoolMaterialConfirmationRequest(
        sourceRevision: widget.revision,
        items: _drafts.map((draft) => draft.item).toList(),
      );

  Future<void> _persist(SchoolMaterialConfirmationRequest body) {
    final snapshot = jsonEncode({'body': body.toJson(), 'key': _key});
    final store = ref.read(keyValueStoreProvider);
    return LocalSerial.run(
      store,
      _storageKey,
      () => store.write(_storageKey, snapshot),
    );
  }

  void _change(VoidCallback change) {
    if (!_active || _busy) return;
    setState(() {
      change();
      _key = null;
      _error = null;
    });
    _persist(_body).catchError((Object error) {
      if (_active) setState(() => _error = describeError(error));
    });
  }

  void _split(int index) {
    final draft = _drafts[index];
    final cursor = draft.text.selection;
    final text = draft.text.text;
    final offset = cursor.start;
    if (!cursor.isCollapsed ||
        offset <= 0 ||
        offset >= text.length ||
        text.substring(0, offset).trim().isEmpty ||
        text.substring(offset).trim().isEmpty) {
      setState(() => _error = '请把光标放在两个题目的分界处。');
      return;
    }
    _change(() {
      draft.text.text = text.substring(0, offset).trimRight();
      _drafts.insert(
        index + 1,
        _QuestionDraft(
          SchoolMaterialConfirmedItem(
            text: text.substring(offset).trimLeft(),
            pages: draft.pages,
          ),
        ),
      );
    });
  }

  void _merge(int index) {
    _change(() {
      final first = _drafts[index];
      final next = _drafts.removeAt(index + 1);
      _retired.add(first);
      _retired.add(next);
      _drafts[index] = _QuestionDraft(
        SchoolMaterialConfirmedItem(
          text: [
            first.text.text,
            next.text.text,
          ].where((text) => text.trim().isNotEmpty).join('\n'),
          pages: {...first.pages, ...next.pages}.toList()..sort(),
        ),
      );
    });
  }

  bool get _valid =>
      _drafts.isNotEmpty &&
      _drafts.length <= 200 &&
      _drafts.every(
        (draft) =>
            draft.pages.isNotEmpty &&
            draft.text.text.trim().isNotEmpty &&
            draft.text.text.runes.length <= 4000,
      );

  Future<void> _confirm() async {
    if (!_active || _busy || !_valid) return;
    final api = ref.read(apiClientProvider);
    final store = ref.read(keyValueStoreProvider);
    final body = _body;
    final key = _key ??= newIdempotencyKey('school-confirm');
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await _persist(body);
      if (!_active) return;
      final receipt = await api.confirmSchoolMaterialCandidates(
        jobId: widget.job,
        body: body,
        idempotencyKey: key,
      );
      if (receipt.sourceRevision != widget.revision ||
          receipt.itemCount != body.items.length) {
        throw StateError('分题确认回执与本机草稿不一致。');
      }
      await LocalSerial.run(
        store,
        _storageKey,
        () => store.delete(_storageKey),
      );
      if (_active) widget.onConfirmed();
    } catch (error) {
      if (_active) setState(() => _error = describeError(error));
    } finally {
      if (_active) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    for (final draft in [..._drafts, ..._retired]) {
      draft.text.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      for (final (index, draft) in _drafts.indexed)
        Column(
          key: ObjectKey(draft),
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: draft.text,
              enabled: !_busy,
              minLines: 2,
              maxLines: 6,
              onChanged: (_) => _change(() {}),
              decoration: InputDecoration(
                labelText: '题目 ${index + 1}',
                helperText: '页码 ${draft.pages.join('、')}',
              ),
            ),
            Wrap(
              children: [
                TextButton(
                  onPressed: _busy || _drafts.length >= 200
                      ? null
                      : () => _split(index),
                  child: const Text('从光标处拆题'),
                ),
                if (index + 1 < _drafts.length)
                  TextButton(
                    onPressed: _busy ? null : () => _merge(index),
                    child: const Text('与下一题合并'),
                  ),
              ],
            ),
          ],
        ),
      if (_error case final error?) Text(error),
      if (_busy) const LinearProgressIndicator(),
      FilledButton(
        onPressed: _busy || !_valid ? null : _confirm,
        child: const Text('确认分题'),
      ),
    ],
  );
}
