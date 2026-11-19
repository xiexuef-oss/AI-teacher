import '../../core/storage.dart';
import '../parent/parent_command_store.dart';
import '../solve/resource_journal_store.dart';
import '../solve/draft_store.dart';
import 'profile_journal_store.dart';

Future<Map<String, dynamic>> exportLocalRecoveryRecords(
  KeyValueStore store,
  String owner, {
  int limit = 1000,
}) async {
  if (limit < 1) throw ArgumentError('Invalid export limit');
  final profile = await ProfileJournalStore(store, owner).exportSnapshot();
  final authorization = await ParentCommandStore(
    store,
    owner,
    'student',
  ).exportStudentSnapshot();
  final count =
      ((profile?['commands'] as List?)?.length ?? 0) +
      ((authorization?['commands'] as List?)?.length ?? 0);
  if (count > limit) throw StateError('Recovery export too large');
  final resources = await ResourceJournalStore(
    store,
    owner,
  ).exportSnapshot(limit: limit);
  final drafts = DraftStore(store, owner);
  final practice = await drafts.readExportWriteJournals(limit: limit);
  final questions = await drafts.readExportQuestionCache(limit: limit);
  if (count +
          resources.fold<int>(0, (n, r) => n + (r['commands'] as List).length) +
          practice.fold<int>(0, (n, r) => n + (r['record_count'] as int)) +
          questions.length >
      limit) {
    throw StateError('Recovery export too large');
  }
  return {
    'format_version': 1,
    'scope': 'local_student_recovery_records',
    'owner_id': owner,
    'history_complete': false,
    'consistent_snapshot': false,
    'profile': profile,
    'authorization': authorization,
    'resources': resources,
    'practice': practice,
    'question_cache': questions,
  };
}
