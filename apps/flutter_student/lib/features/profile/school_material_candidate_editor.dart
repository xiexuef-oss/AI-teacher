import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/errors.dart';
import '../../core/idempotency.dart';
import '../../core/local_serial.dart';
import '../../core/providers.dart';
import 'school_material_region_preview.dart';

class SchoolMaterialCandidateEditor extends ConsumerStatefulWidget {
  const SchoolMaterialCandidateEditor({
    required this.owner,
    required this.job,
    required this.revision,
    required this.candidates,
    required this.onSelectRegion,
    required this.onConfirmed,
    super.key,
  });

  final String owner;
  final String job;
  final String revision;
  final List<SchoolMaterialCandidate> candidates;
  final Future<SchoolMaterialRegion?> Function(int, List<SchoolMaterialRegion>)
  onSelectRegion;
  final VoidCallback onConfirmed;

  @override
  ConsumerState<SchoolMaterialCandidateEditor> createState() =>
      _SchoolMaterialCandidateEditorState();
}

class _QuestionDraft {
  _QuestionDraft(SchoolMaterialConfirmedItem item)
    : text = TextEditingController(text: item.text),
      teacherMarks = TextEditingController(text: item.teacherMarks),
      teacherScore = TextEditingController(text: item.teacherScore?.toString()),
      maxScore = TextEditingController(text: item.maxScore?.toString()),
      regions = [...?item.regions],
      pages = item.pages;

  final TextEditingController text;
  final TextEditingController teacherMarks;
  final TextEditingController teacherScore;
  final TextEditingController maxScore;
  final List<int> pages;
  final List<SchoolMaterialRegion> regions;

  bool get hasTeacherDetails =>
      teacherMarks.text.trim().isNotEmpty ||
      teacherScore.text.isNotEmpty ||
      maxScore.text.isNotEmpty;

  bool get hasAnnotations => hasTeacherDetails || regions.isNotEmpty;

  String? get scoreProblem {
    final score = double.tryParse(teacherScore.text);
    final maximum = double.tryParse(maxScore.text);
    if (maximum == null) return null;
    if (maximum <= 0) return '原件满分必须大于零';
    if (score != null && score > maximum) return '教师评分不能超过原件满分';
    return null;
  }

  SchoolMaterialConfirmedItem get item => SchoolMaterialConfirmedItem(
    text: text.text,
    pages: pages,
    teacherMarks: teacherMarks.text.trim().isEmpty
        ? null
        : teacherMarks.text.trim(),
    teacherScore: double.tryParse(teacherScore.text),
    maxScore: double.tryParse(maxScore.text),
    regions: regions.isEmpty ? null : regions,
  );

  void dispose() {
    text.dispose();
    teacherMarks.dispose();
    teacherScore.dispose();
    maxScore.dispose();
  }
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
            draft.text.text.runes.length <= 4000 &&
            draft.scoreProblem == null,
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

  Future<void> _addRegion(_QuestionDraft draft, int page) async {
    if (!_active || _busy || draft.regions.length >= 20) return;
    setState(() => _busy = true);
    SchoolMaterialRegion? region;
    try {
      region = await widget.onSelectRegion(page, draft.regions);
    } catch (error) {
      if (_active) setState(() => _error = describeError(error));
    } finally {
      if (_active) setState(() => _busy = false);
    }
    if (region case final selected?) _change(() => draft.regions.add(selected));
  }

  @override
  void dispose() {
    for (final draft in [..._drafts, ..._retired]) {
      draft.dispose();
    }
    super.dispose();
  }

  Widget _scoreField(
    TextEditingController controller,
    String label, {
    String? error,
  }) {
    return TextField(
      controller: controller,
      enabled: !_busy,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      inputFormatters: [
        TextInputFormatter.withFunction((oldValue, newValue) {
          return RegExp(r'^(?:\d{1,5}(?:\.\d{0,2})?)?$').hasMatch(newValue.text)
              ? newValue
              : oldValue;
        }),
      ],
      onChanged: (_) => _change(() {}),
      decoration: InputDecoration(labelText: label, errorText: error),
    );
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
            PopupMenuButton<int>(
              enabled:
                  !_busy && draft.pages.isNotEmpty && draft.regions.length < 20,
              onSelected: (page) => _addRegion(draft, page),
              itemBuilder: (_) => [
                for (final page in draft.pages)
                  PopupMenuItem(value: page, child: Text('第 $page 页')),
              ],
              child: const Padding(
                padding: EdgeInsets.all(12),
                child: Text('框选原件区域'),
              ),
            ),
            if (draft.regions.isNotEmpty)
              Wrap(
                spacing: 8,
                children: [
                  for (final region in draft.regions)
                    InputChip(
                      label: Text(
                        '第 ${region.page} 页 ${schoolMaterialRegionLabels[region.kind]}',
                      ),
                      onDeleted: _busy
                          ? null
                          : () => _change(() => draft.regions.remove(region)),
                    ),
                ],
              ),
            Wrap(
              children: [
                TextButton(
                  onPressed:
                      _busy || _drafts.length >= 200 || draft.hasAnnotations
                      ? null
                      : () => _split(index),
                  child: const Text('从光标处拆题'),
                ),
                if (index + 1 < _drafts.length)
                  TextButton(
                    onPressed:
                        _busy ||
                            draft.hasAnnotations ||
                            _drafts[index + 1].hasAnnotations
                        ? null
                        : () => _merge(index),
                    child: const Text('与下一题合并'),
                  ),
              ],
            ),
            ExpansionTile(
              title: const Text('教师批注与原件分数'),
              initiallyExpanded: draft.hasTeacherDetails,
              children: [
                const Text('拆题或合并后再记录教师批注。原件没有分数时可留空。'),
                TextField(
                  controller: draft.teacherMarks,
                  enabled: !_busy,
                  maxLength: 4000,
                  minLines: 1,
                  maxLines: 4,
                  onChanged: (_) => _change(() {}),
                  decoration: const InputDecoration(labelText: '教师批注'),
                ),
                _scoreField(draft.teacherScore, '教师评分'),
                _scoreField(draft.maxScore, '原件满分', error: draft.scoreProblem),
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
