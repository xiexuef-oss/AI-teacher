import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/profile/local_recovery_export.dart';
import 'package:tutor_student/features/profile/student_data_export_section.dart';
import 'package:tutor_student/features/solve/draft_store.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';
import 'practice_journal_export_test.dart' show prepared;

Question question() =>
    Question.fromJson(Fixtures.load().value('question_single_choice'));

class ChangedCache extends MemoryStore {
  bool foreign = false;
  bool disappear = false;
  bool readForeign = false;
  @override
  Future<List<String>> keys(String prefix) async {
    final keys = await super.keys(prefix);
    if (prefix.endsWith('/question/') && keys.isNotEmpty) {
      if (disappear) data.remove(keys.first);
      if (foreign) return [keys.first.replaceFirst('u/alice/', 'u/other/')];
    }
    return keys;
  }

  @override
  Future<String?> read(String key) async {
    if (key.startsWith('u/other/')) readForeign = true;
    return super.read(key);
  }
}

void main() {
  test(
    'exports root and scoped received question caches, not another owner',
    () async {
      final disk = MemoryStore();
      final q = question();
      final root = DraftStore(disk, 'alice');
      await root.writeQuestion(q);
      await root.forAttempt('attempt-one').writeQuestion(q);
      await root.forLocal('local-one').writeQuestion(q);
      await DraftStore(disk, 'bob').writeQuestion(q);
      final before = Map.of(disk.data);
      final data = await exportLocalRecoveryRecords(disk, 'alice');
      final records = data['question_cache'] as List;
      expect(records, hasLength(3));
      expect(records.map((r) => r['workspace']), [
        null,
        'attempt/attempt-one',
        'local/local-one',
      ]);
      expect(
        records.every(
          (r) =>
              r['question_id'] == q.id &&
              jsonEncode(r['question']) == jsonEncode(q.toJson()),
        ),
        isTrue,
      );
      expect(data['history_complete'], isFalse);
      expect(data['consistent_snapshot'], isFalse);
      expect(disk.data, before);
    },
  );

  test(
    'empty cache is explicit without initializing or writing storage',
    () async {
      final disk = MemoryStore();
      expect(
        (await exportLocalRecoveryRecords(disk, 'alice'))['question_cache'],
        isEmpty,
      );
      expect(disk.data, isEmpty);
    },
  );

  test(
    'exports generated public fields only, including nested content',
    () async {
      final disk = MemoryStore();
      final raw = question().toJson();
      raw['answer'] = 'PRIVATE-ANSWER';
      (raw['content'] as Map)['private_token'] = 'PRIVATE-TOKEN';
      disk.data['u/alice/question/${question().id}'] = jsonEncode(raw);
      final before = Map.of(disk.data);
      final result = await exportLocalRecoveryRecords(disk, 'alice');
      expect(jsonEncode(result), isNot(contains('PRIVATE')));
      expect(
        (result['question_cache'] as List).single['question'],
        question().toJson(),
      );
      expect(disk.data, before);
    },
  );

  for (final damage in [
    'json',
    'identity',
    'version',
    'zero_version',
    'missing_title',
    'scope',
    'trailing',
  ]) {
    test(
      'invalid cache $damage fails whole file without changing bytes',
      () async {
        final disk = MemoryStore();
        final q = question();
        var key = 'u/alice/question/${q.id}';
        final raw = q.toJson();
        if (damage == 'identity') raw['id'] = 'another-question';
        if (damage == 'version') raw['version'] = 1.5;
        if (damage == 'zero_version') raw['version'] = 0;
        if (damage == 'missing_title') raw.remove('title');
        if (damage == 'scope') key += '/session/s';
        if (damage == 'trailing') key += '/attempt/a/extra';
        disk.data[key] = damage == 'json' ? '{' : jsonEncode(raw);
        final before = Map.of(disk.data);
        await expectLater(
          exportLocalRecoveryRecords(disk, 'alice'),
          throwsFormatException,
        );
        expect(disk.data, before);
      },
    );
  }

  for (final changed in ['foreign', 'disappear']) {
    test(
      'cache enumeration $changed fails before leaking or inventing a record',
      () async {
        final disk = ChangedCache()
          ..foreign = changed == 'foreign'
          ..disappear = changed == 'disappear';
        await DraftStore(disk, 'alice').writeQuestion(question());
        await expectLater(
          exportLocalRecoveryRecords(disk, 'alice'),
          throwsFormatException,
        );
        expect(disk.readForeign, isFalse);
      },
    );
  }

  test(
    'cache rows count toward the shared limit with other recovery commands',
    () async {
      final disk = MemoryStore();
      final root = DraftStore(disk, 'alice');
      await root.writeQuestion(question());
      await root.forAttempt('one').writeQuestion(question());
      final before = Map.of(disk.data);
      await expectLater(
        exportLocalRecoveryRecords(disk, 'alice', limit: 1),
        throwsStateError,
      );
      expect(disk.data, before);
    },
  );

  test('cache and practice share the combined limit', () async {
    final disk = MemoryStore();
    await prepared(disk);
    final store = DraftStore(disk, 'alice');
    await store.writeQuestion(question());
    final practice = await store.readExportWriteJournals();
    final count = practice.fold<int>(
      0,
      (n, r) => n + (r['record_count'] as int),
    );
    expect(count, greaterThan(0));
    final before = Map.of(disk.data);
    await expectLater(
      exportLocalRecoveryRecords(disk, 'alice', limit: count),
      throwsStateError,
    );
    expect(disk.data, before);
  });

  testWidgets(
    'cache-only recovery file can be saved offline from existing entry',
    (tester) async {
      final disk = MemoryStore();
      await DraftStore(disk, 'student').writeQuestion(question());
      final h = AppHarness(store: disk)
        ..signInAs(role: 'student', userId: 'student');
      h.backend.offline = true;
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection.recovery(
              save: (bytes) async {
                final data = jsonDecode(utf8.decode(bytes)) as Map;
                expect(data['practice'], isEmpty);
                expect(data['question_cache'], hasLength(1));
                saves++;
                return 'saved';
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final before = Map.of(h.store.data);
      await tester.tap(find.byKey(const ValueKey('profile.exportRecovery')));
      await tester.pumpAndSettle();
      expect(saves, 1);
      expect(h.store.data, before);
    },
  );
}
