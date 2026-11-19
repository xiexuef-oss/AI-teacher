import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/scan/scan_draft.dart';

void main() {
  test('late writes from a replaced page cannot overwrite new input', () async {
    final memory = MemoryStore();
    final old = ScanDraftStore(memory, 'student');
    await old.save(ScanDraft()..stem = 'old');
    final current = ScanDraftStore(memory, 'student');
    await current.save(ScanDraft()..stem = 'new');
    await expectLater(old.save(ScanDraft()..scanId = 'late'), throwsStateError);
    expect((await current.load()).stem, 'new');
  });
  test('unknown and corrupt versions remain untouched', () async {
    for (final raw in ['{"version":99}', 'not json']) {
      final memory = MemoryStore({'scan.student.draft': raw});
      final local = ScanDraftStore(memory, 'student');
      await expectLater(local.load(), throwsA(anything));
      await expectLater(local.save(ScanDraft()), throwsA(anything));
      expect(memory.data['scan.student.draft'], raw);
    }
  });
  test('scan text retry keys survive restart isolated by student', () async {
    final store = MemoryStore();
    final a = ScanDraftStore(store, 'a');
    final d = ScanDraft()
      ..stem = 'text'
      ..expressions = 'x^2'
      ..scanId = 'scan-1';
    final key = d.key('confirm');
    await a.save(d);
    final r = await a.load();
    expect(r.stem, 'text');
    expect(r.expressions, 'x^2');
    expect(r.scanId, 'scan-1');
    expect(r.key('confirm'), key);
    expect((await ScanDraftStore(store, 'b').load()).stem, '');
    expect(store.data.values.single, isNot(contains('content_base64')));
  });
}
