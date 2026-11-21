@TestOn('browser')
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/core/paper_photo_storage_web.dart';
import 'package:tutor_student/core/storage.dart';

void main() {
  test('restores a photo larger than local storage and scopes keys', () async {
    final fallback = MemoryStore({'student-a.legacy': 'old photo'});
    final store = paperPhotoStorage(fallback);
    final photo = 'A' * 6990512;
    await store.write('student-a.batch', photo);
    try {
      final reopened = paperPhotoStorage(fallback);
      expect(await reopened.read('student-a.batch'), photo);
      expect(await reopened.keys('student-a.'), [
        'student-a.batch',
        'student-a.legacy',
      ]);
      expect(await reopened.keys('student-b.'), isEmpty);
      expect(await reopened.read('student-a.legacy'), 'old photo');
      await reopened.delete('student-a.legacy');
      expect(await reopened.read('student-a.legacy'), isNull);
    } finally {
      await store.delete('student-a.batch');
    }
    expect(await store.read('student-a.batch'), isNull);
  });
}
