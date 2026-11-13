import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/core/idempotency.dart';

/// 服务端只接受 8~128 位的字母、数字和 `. _ : -`（Idempotency-Key）。
final RegExp valid = RegExp(r'^[A-Za-z0-9._:-]{8,128}$');

void main() {
  group('幂等键', () {
    test('不管标签里有什么，生成的键都合法', () {
      for (final label in [
        'submit',
        'redeem:abcde 23456',
        '撤销：中文',
        'a b/c?d=e&f',
        'x' * 300,
        '',
        ' ',
      ]) {
        final key = newIdempotencyKey(label);
        expect(valid.hasMatch(key), isTrue, reason: '"$label" → $key');
      }
    });

    test('每次生成的键都不一样', () {
      final keys = {for (var i = 0; i < 50; i++) newIdempotencyKey('submit')};
      expect(keys.length, 50);
    });

    test('同一个动作没成功之前重试复用同一个键，成功后换新的', () {
      final keys = PendingKeys();
      final first = keys.keyFor('submit');
      expect(keys.keyFor('submit'), first);
      expect(keys.keyFor('revoke'), isNot(first), reason: '不同的动作不共用键');
      keys.done('submit');
      expect(keys.has('submit'), isFalse);
      expect(keys.keyFor('submit'), isNot(first));
    });

    test('动作名里带着用户输入时，用标签起键：键里没有它', () {
      final keys = PendingKeys();
      final key = keys.keyFor('redeem:abcde 23456', label: 'redeem');
      expect(key, startsWith('redeem-'));
      expect(key.toLowerCase(), isNot(contains('abcde')));
      expect(keys.keyFor('redeem:abcde 23456', label: 'redeem'), key);
      expect(keys.keyFor('redeem:other', label: 'redeem'), isNot(key));
    });
  });
}
